#!/usr/bin/env python3
"""
iAP2 Button Reader — читает кнопки Car Thing и отправляет HID команды через iap2_agent
Связывает gpio-keys (event0) и rotary encoder (event1) с iAP2 HID usage codes
"""
import struct
import os
import select
import sys
import time
import threading

# ── HID Usage codes для Apple media control ────────────────────────────────
HID_PLAY_PAUSE = 0x00CD
HID_NEXT_TRACK = 0x00B6
HID_PREV_TRACK = 0x00B7
HID_VOL_UP     = 0x0080
HID_VOL_DOWN   = 0x0081

# ── Input events ───────────────────────────────────────────────────────────
EVENT_FMT  = 'llHHi'
EVENT_SIZE = struct.calcsize(EVENT_FMT)
EV_KEY, EV_REL = 1, 2

# ── Button mapping: event code → HID usage ────────────────────────────────
KEYMAP = {
    2:  HID_PLAY_PAUSE,     # preset1
    3:  HID_NEXT_TRACK,     # preset2
    4:  HID_PREV_TRACK,     # preset3
    5:  HID_PLAY_PAUSE,     # preset4
    28: HID_PLAY_PAUSE,     # encoder click
    50: HID_PLAY_PAUSE,     # mute
}

# ── Button mapping: event code → AVRCP method ────────────────────────────────
AVRCP_KEYMAP = {
    2:  'Play',             # preset1
    3:  'Next',             # preset2
    4:  'Previous',         # preset3
    5:  'Play',             # preset4
    28: 'Play',             # encoder click
    50: 'Play',             # mute
}

# ── Global iap2_agent connection ───────────────────────────────────────────
_iap2_conn = None
_iap2_lock = threading.Lock()

def connect_to_iap2():
    """Подключиться к iap2_agent через D-Bus и получить его объект."""
    global _iap2_conn
    try:
        import dbus
        bus = dbus.SystemBus()
        # Попытаемся найти iap2_agent по его объекту
        # TODO: это может не сработать если у iap2_agent нет D-Bus объекта
        # Для теста просто возвращаем дамми
        _iap2_conn = True
        print('[BTN] Connected to iap2_agent mock (D-Bus not available)')
        return True
    except Exception as e:
        print(f'[BTN] Warning: Could not connect to iap2_agent via D-Bus: {e}', file=sys.stderr)
        print('[BTN] Will use file-based IPC instead', file=sys.stderr)
        # TODO: реализовать file-based IPC (FIFO или сокет)
        return False

def send_hid_usage(usage_code):
    """Отправить HID usage code в iap2_agent через FIFO (text format)."""
    global _iap2_conn

    # Map HID codes to text commands
    code_map = {
        0x00CD: "play",         # Play/Pause
        0x00B6: "next",         # Next Track
        0x00B7: "prev",         # Previous Track
        0x0080: "volup",        # Vol Up
        0x0081: "voldown",      # Vol Down
    }

    cmd = code_map.get(usage_code, f"0x{usage_code:04X}")

    try:
        with open('/tmp/iap2_hid_cmd', 'w') as fifo:
            fifo.write(cmd + "\n")
        print(f'[BTN] HID usage 0x{usage_code:04X} → "{cmd}" sent via FIFO', flush=True)
        return True
    except Exception as e:
        print(f'[BTN] Error sending HID via FIFO: {e}', file=sys.stderr, flush=True)
        return False

# ── AVRCP via BlueZ MediaControl1 ─────────────────────────────────────────
_AVRCP_DEV_PATH = '/org/bluez/hci0/dev_10_A2_D3_83_82_50'

def send_avrcp(method):
    """Отправить команду через org.bluez.MediaControl1 (работает с iPhone)."""
    import subprocess
    try:
        result = subprocess.run(
            ['dbus-send', '--system', '--print-reply',
             '--dest=org.bluez', _AVRCP_DEV_PATH,
             f'org.bluez.MediaControl1.{method}'],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            print(f'[AVRCP] {method} OK', flush=True)
            return True
        else:
            print(f'[AVRCP] {method} failed: {result.stderr.strip()}', file=sys.stderr, flush=True)
            return False
    except Exception as e:
        print(f'[AVRCP] {method} error: {e}', file=sys.stderr, flush=True)
        return False

def read_buttons():
    """Читать события от gpio-keys (event0) и отправлять AVRCP команды."""
    try:
        fd = os.open('/dev/input/event0', os.O_RDONLY | os.O_NONBLOCK)
    except Exception as e:
        print(f'[BTN] Cannot open event0: {e}', file=sys.stderr)
        return
    
    print('[BTN] Listening to gpio-keys (event0)', flush=True)
    while True:
        r, _, _ = select.select([fd], [], [], 1.0)
        if not r:
            continue
        
        try:
            data = os.read(fd, EVENT_SIZE)
            if len(data) < EVENT_SIZE:
                continue
            
            _, _, typ, code, value = struct.unpack(EVENT_FMT, data)
            
            # Press event (value=1)
            if typ == EV_KEY and value == 1:
                method = AVRCP_KEYMAP.get(code)
                if method:
                    print(f'[BTN] Button code {code} → AVRCP {method}', flush=True)
                    send_avrcp(method)
                else:
                    print(f'[BTN] Unmapped button code {code}', flush=True)
        except Exception as e:
            print(f'[BTN] Read error: {e}', file=sys.stderr)
            time.sleep(0.1)

def read_encoder():
    """Читать события от rotary encoder (event1) и отправлять Vol Up/Down."""
    try:
        fd = os.open('/dev/input/event1', os.O_RDONLY | os.O_NONBLOCK)
    except Exception as e:
        print(f'[ENC] Cannot open event1: {e}', file=sys.stderr)
        return
    
    print('[ENC] Listening to rotary encoder (event1)', flush=True)
    accumulator = 0
    THRESHOLD = 3
    
    while True:
        r, _, _ = select.select([fd], [], [], 1.0)
        if not r:
            continue
        
        try:
            data = os.read(fd, EVENT_SIZE)
            if len(data) < EVENT_SIZE:
                continue
            
            _, _, typ, code, value = struct.unpack(EVENT_FMT, data)
            
            if typ == EV_REL:
                accumulator += value
                while accumulator >= THRESHOLD:
                    accumulator -= THRESHOLD
                    print('[ENC] Vol Up', flush=True)
                    send_avrcp('VolumeUp')

                while accumulator <= -THRESHOLD:
                    accumulator += THRESHOLD
                    print('[ENC] Vol Down', flush=True)
                    send_avrcp('VolumeDown')
        except Exception as e:
            print(f'[ENC] Read error: {e}', file=sys.stderr)
            time.sleep(0.1)

def main():
    print('[iap2_button_reader] Starting...', flush=True)
    
    connect_to_iap2()
    
    # Start button and encoder readers in separate threads
    btn_thread = threading.Thread(target=read_buttons, daemon=True)
    enc_thread = threading.Thread(target=read_encoder, daemon=True)
    
    btn_thread.start()
    enc_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('[iap2_button_reader] Shutting down...', flush=True)
        return 0

if __name__ == '__main__':
    sys.exit(main())
