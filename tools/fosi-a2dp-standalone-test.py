#!/usr/bin/env python3
"""[CLAUDE 2026-06-02] Изолированный тест Car Thing -> Fosi как A2DP source.
Без айфона, без полного рантайма — эксклюзивно на HCI. Воспроизводит условия
доказанно-рабочего прогона 2026-05-21 (A2DP_STREAMING_OK). Запускать с ОСТАНОВЛЕННЫМ
рантаймом. Использует ТЕКУЩИЙ a2dp_bridge.setup_receiver + AVDTP/L2CAP debug-трейс."""
import asyncio
import logging
import os
import sys

if (
    os.environ.get("CARTHING_BUMBLE_QUARANTINE", "1") != "0"
    or os.environ.get("CARTHING_ALLOW_BUMBLE_RUN", "0") != "1"
):
    raise SystemExit(
        "[fosi-a2dp-standalone-test] Bumble A2DP test quarantined; set "
        "CARTHING_BUMBLE_QUARANTINE=0 CARTHING_ALLOW_BUMBLE_RUN=1 for a manual lab run"
    )

sys.path.insert(0, "/usr/lib/carthing")
sys.path.insert(0, "/usr/lib/carthing/vendor")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# Полный AVDTP/L2CAP-трейс — увидеть, отвечает ли Fosi на DISCOVER или молчит.
for _n in ("bumble.avdtp", "bumble.l2cap", "bumble.a2dp"):
    logging.getLogger(_n).setLevel(logging.DEBUG)

FOSI = "C4:A9:B8:70:2F:E5"


class Stub:
    """Минимальный state для setup_receiver/ensure_speaker_connection."""
    transfer_active = True
    trusted_sources = []
    trusted_speakers = [{"address": FOSI, "online": True, "connected": False}]

    def __init__(self):
        self.transfer_status = ""

    def route_speaker_address(self):
        return FOSI

    def is_trusted_speaker(self, a):
        return True

    def is_trusted_source(self, a):
        return False

    def set_speaker_connected(self, a, c=True):
        pass

    def set_connected_speaker(self, a):
        pass

    def __getattr__(self, k):
        def _noop(*a, **k):
            return None
        return _noop


async def main():
    from ble_transport import init_ble
    from a2dp_bridge import A2DPBridge

    # [CLAUDE 2026-06-02] classic + SSP ДО power_on (иначе Write_Simple_Pairing_Mode не уходит
    # на чип -> authenticate отдаёт PIN_OR_KEY_MISSING вместо SSP-пэйринга).
    def _cfg(device):
        device.classic_enabled = True
        device.classic_ssp_enabled = True
        try:
            from bumble.pairing import PairingConfig, PairingDelegate
            device.pairing_config_factory = lambda conn: PairingConfig(
                sc=True, mitm=False, bonding=True,
                delegate=PairingDelegate(io_capability=PairingDelegate.NO_OUTPUT_NO_INPUT),
            )
        except Exception as e:
            print(">>> pairing_config setup warn:", e)

    device, _t = await init_ble(configure_device=_cfg)

    b = A2DPBridge(device, Stub())
    b.install_sdp_records()
    b.install_safe_link_key_provider()

    print(">>> STANDALONE A2DP SOURCE TEST -> Fosi (no iPhone, exclusive HCI)")
    try:
        await b.setup_receiver(FOSI)
        ok = b.receiver_rtp_channel is not None
        print(f">>> setup_receiver done: rtp_channel={b.receiver_rtp_channel} "
              f"status={b.state.transfer_status} "
              f"{'A2DP_STREAMING_OK' if ok else 'NO_RTP_CHANNEL'}")
        if ok:
            print(">>> holding stream 20s (Fosi should be solid / connected)")
            await asyncio.sleep(20)
    except Exception as e:
        import traceback
        print(f">>> setup_receiver FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        # [CLAUDE 2026-06-02] ЧИСТО закрыть всё, чтобы не оставлять Fosi полу-открытые
        # L2CAP/ACL каналы (иначе у неё кончаются ресурсы -> NO_RESOURCES на след. заходе).
        try:
            for c in list(getattr(device, "connections", {}).values()
                          if hasattr(getattr(device, "connections", {}), "values")
                          else getattr(device, "connections", [])):
                try:
                    await c.disconnect()
                except Exception:
                    pass
            print(">>> connections disconnected cleanly")
        except Exception as e:
            print(">>> cleanup warn:", e)
        try:
            await device.power_off()
        except Exception:
            pass


asyncio.run(main())
