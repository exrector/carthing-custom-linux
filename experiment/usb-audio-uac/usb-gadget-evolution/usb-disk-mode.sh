#!/bin/sh
# /usr/libexec/carthing/usb-disk-mode
# CLAUDE 2026-05-29 (for Codex) -- permanent "USB Disk mode" (Level 2).
#
# Exposes the raw boot/state partition (/dev/mmcblk0p1, FAT ~33MB) to the USB
# host as a real removable mass-storage device, so bootargs.txt / profiles /
# keys.json can be edited from macOS Finder WITHOUT reflashing.
#
# Safety model:
#   * default RO ("enter" or "enter ro") -- host cannot write, zero risk.
#   * RW only on explicit "enter rw" / "rw".
#   * before exporting, the Linux side UNMOUNTS /run/carthing-state so there is
#     never a double-writer (Linux rw + host rw) -> no FAT corruption.
#   * if the partition is busy and umount fails, we ABORT and stay normal.
#
# Switch-back (host cannot trigger Linux while it owns the disk):
#   * over SSH:            usb-disk-mode exit
#   * physical button:     see "watch" (reads /dev/input/event0 gpio-keys)
#   * reboot:              S03-runtime-state remounts, S04 boots ncm only.
#
# Override mechanism relies on /etc/default/carthing using ${VAR:-default}
# (patched 2026-05-29) so the env we export here wins.
#
# TODO(Codex runtime/compositor): draw a guard screen while $FLAG exists.
#   The compositor can poll $FLAG (/run/carthing/usb-disk-active); its content
#   is "ro" or "rw". Pausing/replacing the UI is the only missing piece -- the
#   gadget/mount plumbing below is complete and tested.

set -u

STATE_MOUNT=/run/carthing-state
STATE_DEV=/dev/mmcblk0p1
FLAG=/run/carthing/usb-disk-active
USB_PROFILE=/usr/libexec/carthing/usb-profile
README="$STATE_MOUNT/USB-DISK-README.txt"
EVDEV=/dev/input/event0   # gpio-keys (6 physical buttons)

log(){ echo "[usb-disk-mode] $*"; }

is_mounted(){ awk -v t="$STATE_MOUNT" '$2==t{f=1} END{exit(f?0:1)}' /proc/mounts; }

write_readme(){
  cat > "$README" 2>/dev/null <<EOF
Car Thing (SN Q917) -- USB Disk mode
====================================
This is the device BOOT/STATE partition (FAT, ~33 MB).

Safe to edit:
  bootargs.txt
  carthing/profiles/*     (usb, bt, audio, sensor, debug)
  carthing/keys.json      (BLE keystore -- {} resets pairing)

DO NOT delete or truncate:
  Image  initrd  superbird.dtb
  -> the device will NOT boot without them.

Return the device to NORMAL mode by ONE of:
  * press the physical MENU/BACK button on the device
  * reboot the device
  * over SSH:  /usr/libexec/carthing/usb-disk-mode exit
EOF
  sync
}

enter(){
  mode="${1:-ro}"
  [ "$mode" = "rw" ] || mode="ro"
  if [ -f "$FLAG" ]; then log "already in USB Disk mode ($(cat "$FLAG"))"; return 0; fi
  [ "$mode" = "rw" ] && ro=0 || ro=1

  if is_mounted; then write_readme; fi

  sync
  if is_mounted; then
    if ! umount "$STATE_MOUNT" 2>/run/carthing/usb-disk-umount.err; then
      log "umount failed (partition busy) -- aborting, staying in normal mode:"
      cat /run/carthing/usb-disk-umount.err 2>/dev/null
      return 1
    fi
  fi

  if ! CARTHING_USB_STORAGE_FILE="$STATE_DEV" CARTHING_USB_STORAGE_RO="$ro" \
       "$USB_PROFILE" set ncm,storage; then
    log "gadget switch failed -- remounting state, back to normal"
    is_mounted || mount -t vfat "$STATE_DEV" "$STATE_MOUNT"
    return 1
  fi

  echo "$mode" > "$FLAG"
  log "ENTER ok (mode=$mode ro=$ro). Host now sees raw $STATE_DEV."
}

leave(){
  "$USB_PROFILE" set ncm || log "warn: back-to-ncm returned nonzero"
  if ! is_mounted; then
    mount -t vfat "$STATE_DEV" "$STATE_MOUNT" || log "warn: remount failed"
  fi
  rm -f "$FLAG"
  for d in bt audio sensor debug; do
    [ -x /usr/libexec/carthing/profilectl ] && \
      /usr/libexec/carthing/profilectl "$d" apply >/dev/null 2>&1 || true
  done
  log "EXIT ok. Normal mode restored, state remounted."
}

status(){
  if [ -f "$FLAG" ]; then echo "usb-disk: ACTIVE (mode=$(cat "$FLAG"))"
  else echo "usb-disk: inactive"; fi
  echo "profile: $("$USB_PROFILE" get 2>/dev/null)"
  is_mounted && echo "state: mounted (normal)" || echo "state: UNMOUNTED (exported to host)"
}

# Block until any gpio-key is pressed, then exit disk mode.
# evdev event = 16 bytes (2.6+ 32-bit time): we just wait for a KEY-down.
watch(){
  [ -f "$FLAG" ] || { log "not in disk mode"; return 0; }
  log "watching $EVDEV for a button press to exit..."
  # read raw events; any EV_KEY value=1 triggers exit
  python3 - "$EVDEV" <<'PY' || log "watch: python3 missing, use 'exit' over SSH"
import struct,sys
# 32-bit ARM input_event: tv_sec(i) tv_usec(i) type(H) code(H) value(i) = 16B
f=open(sys.argv[1],"rb")
while True:
    d=f.read(16)
    if len(d)<16: break
    _,_,etype,code,val=struct.unpack("iiHHi",d)
    if etype==1 and val==1:   # EV_KEY, key down
        break
PY
  leave
}

case "${1:-}" in
  enter) shift; enter "${1:-ro}";;
  rw)    enter rw;;
  ro)    enter ro;;
  exit|leave) leave;;
  status) status;;
  watch)  watch;;
  *) echo "usage: usb-disk-mode {enter [ro|rw] | rw | ro | exit | status | watch}"; exit 2;;
esac
