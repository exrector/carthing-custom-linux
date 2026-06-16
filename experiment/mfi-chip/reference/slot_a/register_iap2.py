#!/usr/bin/env python3
"""
register_iap2.py — Регистрирует iAP2 профиль через gdbus
Вызывается перед запуском iap2_agent
"""
import subprocess
import sys
import os

IAP2_UUID = "00000000-deca-fade-deca-deafdecacaff"
PROFILE_PATH = "/org/bluez/profile/iap2"
IAP2_RFCOMM_CHANNEL = 1

SDP_RECORD = (
    '<?xml version="1.0" encoding="UTF-8" ?>'
    '<record>'
    '  <attribute id="0x0001">'
    '    <sequence><uuid value="00000000-deca-fade-deca-deafdecacaff"/></sequence>'
    '  </attribute>'
    '  <attribute id="0x0004">'
    '    <sequence>'
    '      <sequence><uuid value="0x0100"/><uint16 value="0x0001"/></sequence>'
    '      <sequence><uuid value="0x0003"/><uint8 value="1"/></sequence>'
    '    </sequence>'
    '  </attribute>'
    '  <attribute id="0x0009">'
    '    <sequence>'
    '      <sequence><uuid value="00000000-deca-fade-deca-deafdecacaff"/><uint16 value="0x0002"/></sequence>'
    '    </sequence>'
    '  </attribute>'
    '  <attribute id="0x0100"><text value="iAP2"/></attribute>'
    '</record>'
)

def main():
    # gdbus call: gdbus call --system --dest org.bluez --object-path /org/bluez
    #   --method org.bluez.ProfileManager1.RegisterProfile
    #   OBJPATH UUID "{'ServiceRecord': <'...'>, 'Role': <'server'>, 'Channel': <1>}"
    
    opts = "{'ServiceRecord': <'" + SDP_RECORD + "'>, 'Role': <'server'>, 'Channel': <" + str(IAP2_RFCOMM_CHANNEL) + ">}"
    
    cmd = [
        "gdbus", "call", "--system",
        "--dest", "org.bluez",
        "--object-path", "/org/bluez",
        "--method", "org.bluez.ProfileManager1.RegisterProfile",
        PROFILE_PATH,
        IAP2_UUID,
        opts
    ]
    
    print(f"[register_iap2] Registering iAP2 profile...", flush=True)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and "()" in result.stdout:
            print(f"[register_iap2] ✓ iAP2 profile registered", flush=True)
            return 0
        else:
            print(f"[register_iap2] Failed: {result.stderr.strip()}", flush=True)
            print(f"[register_iap2] stdout: {result.stdout.strip()}", flush=True)
            return 1
    except subprocess.TimeoutExpired:
        print(f"[register_iap2] Timeout", flush=True)
        return 1
    except Exception as e:
        print(f"[register_iap2] Error: {e}", flush=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
