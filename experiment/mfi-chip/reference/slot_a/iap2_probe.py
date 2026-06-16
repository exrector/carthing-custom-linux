#!/usr/bin/env python3
"""
iap2_probe.py — iAP2 протокол зонд для Car Thing
Подключается к iPhone RFCOMM ch 1, логирует весь трафик.

Запуск через ADB:
  adb push slot_a/iap2_probe.py /tmp/iap2_probe.py
  adb shell python3 /tmp/iap2_probe.py

Редактировать на Mac → пушить за секунды → наблюдать в ADB shell.
"""

import socket
import struct
import time
import sys

IPHONE_MAC  = "10:A2:D3:83:82:50"
RFCOMM_CH   = 1
TIMEOUT_SEC = 30

# ── iAP2 link-layer helpers ───────────────────────────────────────────────────

def cksum(data: bytes) -> int:
    s = sum(data) & 0xFF
    return ((~s) + 1) & 0xFF

def make_pkt(ctl: int, sid: int, seq: int, ack: int, payload: bytes = b"") -> bytes:
    """Build one raw iAP2 link packet."""
    plen = 8 + len(payload) + (1 if payload else 0)
    hdr = bytearray([
        0xFF,
        (plen >> 8) & 0xFF, plen & 0xFF,
        ctl, sid, seq, ack,
        0x00   # placeholder for header checksum
    ])
    hdr[7] = cksum(hdr[:7])
    if payload:
        return bytes(hdr) + payload + bytes([cksum(payload)])
    return bytes(hdr)

def make_syn(seq: int = 0) -> bytes:
    """iAP2 SYN with mandatory link synchronisation parameters.
    Without this payload iPhone silently ignores the SYN.
    Format (10 bytes):
      Version(1)=1  MaxOutstandingPkts(1)=7  MaxPktLen(2)=0x0800
      RetxTimeout(2)=250ms  CumAckTimeout(2)=25ms
      MaxRetx(1)=3  MaxCumAck(1)=1
    """
    params = struct.pack(">BBHHHBB",
        0x01,   # version
        0x07,   # MaxOutstandingPackets
        0x0800, # MaxPacketLength (2048)
        0x00FA, # RetransmissionTimeout  250 ms
        0x0019, # CumulativeAckTimeout    25 ms
        0x03,   # MaxRetransmissions
        0x01,   # MaxCumAck
    )
    return make_pkt(0x80, 0, seq, 0, params)  # CTL_SYN

def parse_pkt(buf: bytearray):
    """Return (pkt_len, ctl, sid, seq, ack, payload) or None if incomplete."""
    if len(buf) < 8:
        return None
    if buf[0] != 0xFF:
        return None
    pkt_len = (buf[1] << 8) | buf[2]
    if pkt_len < 8 or len(buf) < pkt_len:
        return None
    ctl = buf[3]; sid = buf[4]; seq = buf[5]; ack = buf[6]
    payload = bytes(buf[8:pkt_len-1]) if pkt_len > 9 else b""
    return pkt_len, ctl, sid, seq, ack, payload

def hex_dump(data: bytes, prefix="") -> str:
    hex_str = " ".join(f"{b:02x}" for b in data)
    try:
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    except Exception:
        asc = ""
    return f"{prefix}{hex_str}  |{asc}|"

# ── Control session message parser ───────────────────────────────────────────

MSG_NAMES = {
    0x1D00: "StartIdentification",
    0x1D01: "IdentificationAccepted",
    0x1D02: "IdentificationRejected",
    0x1D50: "AuthCertRequest",
    0x1D51: "AuthCertResponse",
    0x1D52: "AuthChallengeRequest",
    0x1D53: "AuthChallengeResponse",
    0x1D54: "AuthenticationFailed",
    0x1D55: "AuthenticationSucceeded",
    0x4800: "NowPlayingUpdate",
    0x6800: "HIDReport",
}

def parse_control_msg(payload: bytes):
    if len(payload) < 4:
        return
    msg_len = (payload[0] << 8) | payload[1]
    msg_id  = (payload[2] << 8) | payload[3]
    name    = MSG_NAMES.get(msg_id, f"0x{msg_id:04X}")
    params  = payload[4:msg_len] if msg_len > 4 else b""
    print(f"  [ctrl] {name} ({msg_len} bytes total, {len(params)} bytes params)")
    if params:
        print(hex_dump(params, "         "))

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[probe] Connecting RFCOMM to {IPHONE_MAC} ch {RFCOMM_CH}...")
    try:
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                             socket.BTPROTO_RFCOMM)
        sock.settimeout(15)
        sock.connect((IPHONE_MAC, RFCOMM_CH))
    except Exception as e:
        print(f"[probe] Connection failed: {e}")
        sys.exit(1)

    print("[probe] ✓ Connected!")
    sock.settimeout(TIMEOUT_SEC)

    seq = 0
    buf = bytearray()

    # iAP2 over BT: iPhone is the HOST — it sends SYN first.
    # We wait; if nothing arrives in 3s, we try sending SYN ourselves.
    print("[probe] Waiting for iPhone SYN (iPhone should speak first)...")
    sock.settimeout(3)
    try:
        first = sock.recv(4096)
        if first:
            print(f"[probe] ← iPhone spoke first! {len(first)} bytes:")
            print(hex_dump(first, "  "))
            buf.extend(first)
    except socket.timeout:
        print("[probe] iPhone silent for 3s → sending SYN ourselves")
        syn = make_syn(seq)
        print(f"[probe] → SYN  {syn.hex()}")
        sock.sendall(syn)

    sock.settimeout(TIMEOUT_SEC)

    try:
        while True:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                print("[probe] Timeout waiting for data")
                break
            if not data:
                print("[probe] Connection closed by remote")
                break

            print(f"\n[probe] ← {len(data)} bytes raw:")
            print(hex_dump(data, "  "))
            buf.extend(data)

            # Parse packets
            while True:
                # Re-sync to SOF
                while buf and buf[0] != 0xFF:
                    print(f"[probe] skip non-SOF byte: {buf[0]:02x}")
                    buf.pop(0)

                result = parse_pkt(buf)
                if result is None:
                    break
                pkt_len, ctl, sid, seq_r, ack, payload = result
                buf = buf[pkt_len:]

                ctl_str = []
                if ctl & 0x80: ctl_str.append("SYN")
                if ctl & 0x40: ctl_str.append("ACK")
                if ctl & 0x20: ctl_str.append("EAK")
                if ctl & 0x10: ctl_str.append("RST")
                if not ctl_str: ctl_str.append("DATA")

                print(f"  PKT ctl={'+'.join(ctl_str)} sid={sid} seq={seq_r} "
                      f"ack={ack} payload={len(payload)}b")

                if ctl == 0x80:  # SYN from iPhone
                    seq += 1
                    synack = make_pkt(0xC0, 0, seq, seq_r + 1)  # SYN+ACK
                    print(f"[probe] → SYN+ACK  {synack.hex()}")
                    sock.sendall(synack)

                elif ctl == 0x00 and sid == 0:  # DATA on control session
                    # Send ACK
                    seq += 1
                    ack_pkt = make_pkt(0x40, 0, seq, seq_r + 1)
                    sock.sendall(ack_pkt)
                    print(f"[probe] → ACK (seq={seq_r+1})")
                    parse_control_msg(payload)

    except KeyboardInterrupt:
        print("\n[probe] Interrupted")
    finally:
        sock.close()
        print("[probe] Done")

if __name__ == "__main__":
    main()
