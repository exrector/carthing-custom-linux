#!/usr/bin/env python3
"""[CLAUDE 2026-06-02] Псевдо-источник A2DP: Car Thing сам кормит Fosi SBC-тоном (/run/tone.sbc).
Запускать с ОСТАНОВЛЕННЫМ рантаймом, транспорт hci-socket:0.
БРОНЯ: при ЛЮБОМ исходе — чистый disconnect (иначе провал подвешивает Fosi на следующий заход).
Discover с коротким таймаутом (быстрый фейл вместо 20с виса)."""
import asyncio
import logging
import os
import sys
import time as _t

if (
    os.environ.get("CARTHING_BUMBLE_QUARANTINE", "1") != "0"
    or os.environ.get("CARTHING_ALLOW_BUMBLE_RUN", "0") != "1"
):
    raise SystemExit(
        "[fosi-pseudo-source] Bumble A2DP test quarantined; set "
        "CARTHING_BUMBLE_QUARANTINE=0 CARTHING_ALLOW_BUMBLE_RUN=1 for a manual lab run"
    )

sys.path.insert(0, "/usr/lib/carthing")
sys.path.insert(0, "/usr/lib/carthing/vendor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FOSI = "C4:A9:B8:70:2F:E5"
SBC_FILE = "/run/tone.sbc"
SBC_FRAME = 47
FRAMES_PER_RTP = 7
SAMPLES_PER_FRAME = 128
SAMPLE_RATE = 44100


async def _disconnect_all(device, why):
    try:
        conns = device.connections
        items = list(conns.values() if hasattr(conns, "values") else conns)
    except Exception:
        items = []
    for c in items:
        try:
            await c.disconnect()
            print(f">>> disconnected {getattr(c,'peer_address','?')} ({why})")
        except Exception:
            pass


async def main():
    from ble_transport import init_ble
    from bumble.core import BT_BR_EDR_TRANSPORT
    from bumble import avdtp
    from bumble.avdtp import MediaPacket
    from bumble.a2dp import (
        SbcMediaCodecInformation, A2DP_SBC_CODEC_TYPE,
        SBC_JOINT_STEREO_CHANNEL_MODE, SBC_SNR_ALLOCATION_METHOD,
    )

    def _cfg(device):
        device.classic_enabled = True
        device.classic_ssp_enabled = True
        from bumble.smp import PairingConfig, PairingDelegate
        device.pairing_config_factory = lambda conn: PairingConfig(
            sc=True, mitm=False, bonding=True,
            delegate=PairingDelegate(io_capability=PairingDelegate.NO_OUTPUT_NO_INPUT))

    device, _t2 = await init_ble(configure_device=_cfg)

    async def lk(addr):
        ks = device.keystore
        if ks is None:
            return None
        base = str(addr).split("/")[0]
        for c in (str(addr), base, f"{base}/P"):
            try:
                k = await ks.get(c)
            except Exception:
                k = None
            if k is not None and getattr(k, "link_key", None) is not None:
                return k.link_key.value
        return None
    device.host.link_key_provider = lk

    conn = None
    try:
        await _disconnect_all(device, "stale on start")
        print(">>> connecting Fosi")
        conn = await asyncio.wait_for(device.connect(FOSI, transport=BT_BR_EDR_TRANSPORT), timeout=15)
        try:
            await asyncio.wait_for(device.authenticate(conn), timeout=15)
            await asyncio.wait_for(device.encrypt(conn), timeout=15)
        except Exception as e:
            print(">>> auth/encrypt:", e)
        print(">>> encrypted=", getattr(conn, "is_encrypted", "?"))

        try:
            version = await asyncio.wait_for(avdtp.find_avdtp_service_with_connection(device, conn), timeout=10)
        except Exception:
            version = None
        version = version or (1, 3)
        protocol = await asyncio.wait_for(avdtp.Protocol.connect(conn, version=version), timeout=10)
        print(">>> AVDTP connected, discovering (short timeout)...")
        await asyncio.wait_for(protocol.discover_remote_endpoints(), timeout=8)

        sbc_sink = None
        for ep in protocol.remote_endpoints.values():
            if "A2DP_SBC_CODEC_TYPE" in str(ep) and getattr(ep, "tsep", None) in (1, getattr(avdtp, "AVDTP_TSEP_SNK", 1)):
                sbc_sink = ep
                print(f">>> SBC sink seid={getattr(ep,'seid','?')}")
                break
        if sbc_sink is None:
            print(">>> НЕТ SBC sink"); return

        sbc_info = SbcMediaCodecInformation.from_discrete_values(
            sampling_frequency=44100, channel_mode=SBC_JOINT_STEREO_CHANNEL_MODE,
            block_length=16, subbands=8, allocation_method=SBC_SNR_ALLOCATION_METHOD,
            minimum_bitpool_value=17, maximum_bitpool_value=17)
        cap = avdtp.MediaCodecCapabilities(avdtp.AVDTP_AUDIO_MEDIA_TYPE, A2DP_SBC_CODEC_TYPE, sbc_info)
        source = protocol.add_source(cap, None)
        source.configuration = [
            avdtp.ServiceCapabilities(avdtp.AVDTP_MEDIA_TRANSPORT_SERVICE_CATEGORY),
            avdtp.MediaCodecCapabilities(avdtp.AVDTP_AUDIO_MEDIA_TYPE, A2DP_SBC_CODEC_TYPE, sbc_info)]
        stream = await protocol.create_stream(source, sbc_sink)
        await stream.open()
        await stream.start()
        rtp = stream.rtp_channel
        print(f">>> A2DP_STREAMING_OK rtp={rtp} — кормлю SBC-тоном 15с")

        frames = open(SBC_FILE, "rb").read()
        n = len(frames) // SBC_FRAME
        seq = ts = i = 0
        dt = (FRAMES_PER_RTP * SAMPLES_PER_FRAME) / SAMPLE_RATE
        deadline = _t.monotonic() + 15.0
        while _t.monotonic() < deadline:
            chunk = b""
            for _ in range(FRAMES_PER_RTP):
                off = (i % n) * SBC_FRAME
                chunk += frames[off:off + SBC_FRAME]; i += 1
            payload = bytes([FRAMES_PER_RTP & 0x0F]) + chunk
            pkt = MediaPacket(2, 0, 0, 0, seq & 0xFFFF, ts & 0xFFFFFFFF, 0, [], 96, payload)
            try:
                rtp.send_pdu(bytes(pkt))
            except Exception as e:
                print(">>> send failed:", e); break
            seq += 1; ts += FRAMES_PER_RTP * SAMPLES_PER_FRAME
            await asyncio.sleep(dt)
        print(">>> tone done, sent", seq, "packets")
        try:
            await stream.stop()
        except Exception:
            pass
    except Exception as e:
        import traceback
        print(f">>> FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        await _disconnect_all(device, "clean teardown")
        try:
            await device.power_off()
        except Exception:
            pass
        print(">>> CLEAN EXIT (Fosi released)")


asyncio.run(main())
