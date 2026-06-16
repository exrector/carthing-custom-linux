# Live intervention log — 2026-05-28
Agent: Claude (Opus 4.7) via Claude Code CLI
Target: Car Thing Q917 via IPv6 link-local fe80::70eb:dff:fe28:4a54%en18

## Steps
[16:43:35] step 1: backup /etc/init.d/S04-usbgadget on device
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
cp: can't create '/tmp/S04-usbgadget.orig-claude-20260528': Read-only file system
[16:43:35] step 2: remount root rw
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
/dev/root on / type ext4 (rw,relatime,data=ordered)
[16:43:35] step 3: copy backup into /etc/init.d for posterity (Codex can diff later)
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
-rwxr-xr-x    1 root     root          9665 Jan  1 00:25 /etc/init.d/S04-usbgadget
-rwxr-xr-x    1 root     root          9665 Jan  1 00:16 /etc/init.d/S04-usbgadget.orig-claude-20260528
[16:43:35] step 4: scp PATCHED S04 onto device
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
sh: /usr/libexec/sftp-server: not found
scp: Connection closed
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
-rwxr-xr-x    1 root     root          9665 Jan  1 00:25 /etc/init.d/S04-usbgadget
50c430ae4e9222a30942b15d7d68413f55deb6f273908bb24d7409c2b10a8b33  /etc/init.d/S04-usbgadget
[16:43:36] step 5: verify patched file matches local
[16:43:36] local sha256: 801a03e76de8074f3932e1357205cb4f51dccda4dcdc7334199b953d1e920293
[16:43:49] step 4 (retry): upload PATCHED via cat | ssh
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
801a03e76de8074f3932e1357205cb4f51dccda4dcdc7334199b953d1e920293  /etc/init.d/S04-usbgadget
[16:43:49] local PATCHED sha256: 801a03e76de8074f3932e1357205cb4f51dccda4dcdc7334199b953d1e920293
[16:44:05] step 6: baseline configfs + S04 log BEFORE profile switch
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
=== configfs ===
/sys/kernel/config/usb_gadget/g1/configs/c.1/:
MaxPower
bmAttributes
ncm.usb0
strings

/sys/kernel/config/usb_gadget/g1/functions/:
ncm.usb0

=== S04 log ===
[S04-usbgadget] start
[S04-usbgadget] using UDC: ff400000.dwc2_a
[S04-usbgadget] composite active: mode=ncm enabled=ncm udc=ff400000.dwc2_a
[S04-usbgadget] done: gadget active
[S04-usbgadget] end

=== usb-profile get ===
ncm

=== current usid ===
8559RP88Q917
[16:44:15] step 7: trigger profile switch: ncm -> ncm,audio (USB renumerate expected)
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
[16:44:15] issued; waiting 6s for renumerate
[16:44:21] discover new IPv6 LL on en18
16 bytes from fe80::1c8a:7781:1afb:69fa%en18, icmp_seq=1 hlim=64 time=0.465 ms

--- ff02::1 ping6 statistics ---
2 packets transmitted, 2 packets received, +1 duplicates, 0.0% packet loss
round-trip min/avg/max/std-dev = 0.465/11.043/16.686/7.485 ms
[16:44:23] candidate new device IPv6: 
fe80::1c8a:7781:1afb:69fa%en18          5e:9:d:51:23:61     en18 permanent R      
[16:44:35] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:36] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:37] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:38] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:39] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:40] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:41] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:42] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:44] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:45] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:46] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:44:47] CarThing seen=3  en18 LL=fe80::1c8a:7781:1afb:69fa%en18  device LLs=
[16:45:26] step 8: UAC2 function attributes on device
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
  p_chmask=3
  p_srate=48000
  p_ssize=2
  c_chmask=3
  c_srate=64000
  c_ssize=2
  c_sync=
  function_name=
  c_mute_present=
  c_volume_present=
  c_volume_min=
  c_volume_max=
  c_volume_res=
  p_mute_present=
  p_volume_present=
  p_volume_min=
  p_volume_max=
  p_volume_res=
[16:45:26] step 9: macOS view of Car Thing USB descriptor (after switch)
  | | }
  | | 
  | +-o Car Thing@01100000  <class IOUSBHostDevice, id 0x100005148, registered, matched, active, busy 0 (247 ms), retain 43>
  |     {
  |       "kUSBSerialNumberString" = "8559RP88Q917"
  |       "bDeviceClass" = 0
  |       "UsbLinkSpeed" = 480000000
  |       "bDeviceSubClass" = 0
  |       "iSerialNumber" = 3
  |       "IOServiceDEXTEntitlements" = (("com.apple.developer.driverkit.transport.usb"))
  |       "iProduct" = 2
  |       "USB Serial Number" = "8559RP88Q917"
  |       "USB Vendor Name" = "Spotify AB"
  |       "USBSpeed" = 3
  |       "IOPowerManagement" = {"PowerOverrideOn"=Yes,"DevicePowerState"=2,"CurrentPowerState"=2,"CapabilityFlags"=32768,"MaxPowerState"=2,"DriverPowerState"=0}
  |       "bNumConfigurations" = 1
  |       "kUSBProductString" = "Car Thing"
  |       "kUSBVendorString" = "Spotify AB"
  |       "USB Product Name" = "Car Thing"
  |       "iManufacturer" = 1
  |       "idVendor" = 1317
  |       "Device Speed" = 2
  |       "kUSBCurrentConfiguration" = 1
  |       "idProduct" = 42145
  |       "bcdDevice" = 256
  |       "UsbDeviceSignature" = <2505a1a40001383535395250383851393137000000020d000a0001010120010220>
  |       "sessionID" = 417772302542
  |       "USB Address" = 1
  |       "IOCFPlugInTypes" = {"9dc7b780-9ec0-11d4-a54f-000a27052861"="IOUSBHostFamily.kext/Contents/PlugIns/IOUSBLib.bundle"}
  |       "USBPortType" = 5
  |       "UsbDeviceFunction" = 6
  |       "bDeviceProtocol" = 0
  |       "locationID" = 17825792
  |       "kUSBAddress" = 1
  |       "bcdUSB" = 512
  |       "UsbPowerSinkAllocation" = 250
  |       "bMaxPacketSize0" = 64
  |     }
  |     
  +-o AppleT8112USBXHCI@00000000  <class AppleT8112USBXHCI, id 0x1000004ad, registered, matched, active, busy 0 (19 ms), retain 37>
      {
        "IOClass" = "AppleT8112USBXHCI"
        "kUSBSleepPortCurrentLimit" = 3000
--- USB audio device on host? ---

          Manufacturer: Spotify AB
          Output Channels: 2
          Current SampleRate: 64000
          Transport: USB
          Output Source: Default

        Capture Inactive:

          Input Channels: 2
          Manufacturer: Spotify AB
          Current SampleRate: 48000
          Transport: USB
          Input Source: Default

        Микрофон MacBook Pro:

          Default Input Device: Yes
          Input Channels: 1
          Manufacturer: Apple Inc.
          Current SampleRate: 44100
          Transport: Built-in
          Input Source: Микрофон MacBook Pro

        Динамики MacBook Pro:

--- ALSA card visible to macOS would be in Audio MIDI Setup; checking ioreg for AppleUSBAudio ---
    | |   | | {
    | |   | |   "tunable_CIO_LN1_AUSPMA_RX_SHM" = <1c000020c00ffc07000cc0012400002000c0000000c000002800002000060000000600002c0000207000000050000000380000200000801f000000133c00002000000007000000075c000020000400000004000080000020ffffffff000000088c00002000001c000000100084000020ffff0f001fd70e00>
    | |   | |   "function-dock_parent" = <8301000050636361>
    | |   | |   "tunable_ATC0AXI2AF" = <000000200300000001000000040000200000003f000000080c000020ffff0f000d00000010000020ffff0f000c00000014000020ff0f00000100000018000020ff0f0000010000001c000020ff0f00000300000020000020ff0f00000300000024000020ff0f00000300000028000020ff0f0000030000002c000020ff0f0000030000000801002003000000010000000c010020ffff0f000d00000010010020ffff0f000c00000014010020ff0f00000100000018010020ff0f0000010000001c010020ff0f00000300000020010020ff0f00000300000024010020ff0f00000300000028010020ff0f0000030000002c010020ff0f00000300000000040020ff0301c0020301c0000a0020ffffff01ffffff01000d00200300000000000000300d00200300000000000000>
--
    | |   | | |   | |   "USB Product Name" = "Car Thing"
    | |   | | |   | |   "locationID" = 17825792
    | |   | | |   | |   "bInterfaceClass" = 1
    | |   | | |   | |   "bInterfaceSubClass" = 1
    | |   | | |   | |   "IOCFPlugInTypes" = {"2d9786c6-9ef3-11d4-ad51-000a27052861"="IOUSBHostFamily.kext/Contents/PlugIns/IOUSBLib.bundle"}
    | |   | | |   | |   "UsbExclusiveOwner" = "pid 41322, usbaudiod"
    | |   | | |   | |   "USBPortType" = 5
    | |   | | |   | |   "kUSBString" = "Topology Control"
    | |   | | |   | |   "bInterfaceNumber" = 2
    | |   | | |   | |   "bConfigurationValue" = 1
    | |   | | |   | |   "USB Vendor Name" = "Spotify AB"
    | |   | | |   | |   "idVendor" = 1317
    | |   | | |   | |   "IOServiceDEXTEntitlements" = (("com.apple.developer.driverkit.transport.usb"))
    | |   | | |   | |   "bNumEndpoints" = 0
    | |   | | |   | |   "USB Serial Number" = "8559RP88Q917"
    | |   | | |   | |   "IOGeneralInterest" = "IOCommand is not serializable"
    | |   | | |   | | }
    | |   | | |   | | 
    | |   | | |   | +-o AppleUSBAudioControlNub  <class AppleUSBAudioControlNub, id 0x10000515c, registered, matched, active, busy 0 (3 ms), retain 5>
    | |   | | |   | |   {
    | |   | | |   | |     "IOProbeScore" = 50000
--
    | |   | | |   | |   "bInterfaceProtocol" = 32
    | |   | | |   | |   "bAlternateSetting" = 0
    | |   | | |   | |   "idProduct" = 42145
    | |   | | |   | |   "bcdDevice" = 256
    | |   | | |   | |   "AppleUSBAudioStreamPropertiesReady" = "Yes"
    | |   | | |   | |   "USB Product Name" = "Car Thing"
    | |   | | |   | |   "locationID" = 17825792
    | |   | | |   | |   "bInterfaceClass" = 1
    | |   | | |   | |   "bInterfaceSubClass" = 2
    | |   | | |   | |   "IOCFPlugInTypes" = {"2d9786c6-9ef3-11d4-ad51-000a27052861"="IOUSBHostFamily.kext/Contents/PlugIns/IOUSBLib.bundle"}
    | |   | | |   | |   "UsbExclusiveOwner" = "pid 41322, usbaudiod"
    | |   | | |   | |   "USBPortType" = 5
    | |   | | |   | |   "kUSBString" = "Playback Inactive"
[16:46:08] step 10: trigger downgrade: ncm,audio -> ncm (THE CRITICAL TEST)
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
[16:46:13] step 11: probe state
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
=== S04 log tail ===
[S04-usbgadget] unbind existing UDC: ff400000.dwc2_a
[S04-usbgadget] composite active: mode=ncm,audio enabled=ncm,uac2 udc=ff400000.dwc2_a
[S04-usbgadget] done: gadget active
[S04-usbgadget] end
[S04-usbgadget] start
[S04-usbgadget] using UDC: ff400000.dwc2_a
[S04-usbgadget] unbind existing UDC: ff400000.dwc2_a
[S04-usbgadget] composite active: mode=ncm enabled=ncm udc=ff400000.dwc2_a
[S04-usbgadget] done: gadget active
[S04-usbgadget] end

=== configfs functions ===
ncm.usb0
uac2.usb0
=== configfs c.1 ===
MaxPower
bmAttributes
ncm.usb0
strings
=== UDC state ===
configured
=== usb-profile get ===
ncm
[16:46:13] step 12: macOS view — UAC2 должен ИСЧЕЗНУТЬ
--- count of AppleUSBAudioControlNub matching Car Thing ---
0
[16:46:48] step 13: third cycle — re-enable ncm,audio (idempotency test)
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
[16:46:53] step 14: probe state after re-enable
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
=== S04 log tail ===
[S04-usbgadget] done: gadget active
[S04-usbgadget] end
[S04-usbgadget] start
[S04-usbgadget] using UDC: ff400000.dwc2_a
[S04-usbgadget] unbind existing UDC: ff400000.dwc2_a
[S04-usbgadget] composite active: mode=ncm,audio enabled=ncm,uac2 udc=ff400000.dwc2_a
[S04-usbgadget] done: gadget active
[S04-usbgadget] end

=== configfs c.1 ===
MaxPower
bmAttributes
ncm.usb0
strings
uac2.usb0
=== usb-profile ===
ncm,audio
[16:46:53] macOS AppleUSBAudioControlNub count for Car Thing
1
[16:46:54] step 15: restore ncm (default safe state) before remount ro
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
[S04-usbgadget] unbind existing UDC: ff400000.dwc2_a
[S04-usbgadget] composite active: mode=ncm enabled=ncm udc=ff400000.dwc2_a
[S04-usbgadget] done: gadget active
[S04-usbgadget] end
===
MaxPower
bmAttributes
ncm.usb0
strings
===
ncm
[16:46:59] step 16: remount root back to ro (clean exit)
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
/dev/root on / type ext4 (ro,relatime,data=ordered)
[16:46:59] step 17: final sanity check — SSH still works, dropbear running
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
 00:20:14 up 20 min,  load average: 1.07, 1.01, 0.76
4.9.113
Filesystem                Size      Used Available Use% Mounted on
/dev/root               485.6M     50.4M    431.2M  10% /
/dev/mmcblk0p1           31.9M     25.1M      6.8M  79% /run/carthing-state
  267 root     dropbear -F -E -p 22 -P /run/carthing/dropbear.pid -r /run/dropbear/dropbear_rsa_host_key
  294 root     /usr/bin/carthing-btattach-mini /dev/ttyS1 115200
  325 root     python3 /usr/lib/carthing/media_remote.py
  726 root     dropbear -F -E -p 22 -P /run/carthing/dropbear.pid -r /run/dropbear/dropbear_rsa_host_key
[16:46:59] DONE

## SUMMARY

**Patches applied to /etc/init.d/S04-usbgadget:**
- build_composite(): removed early-exit + added stale-symlink purge
- add_audio(): full duplex (c_chmask=3), sample rate, ssize, sync, volume/mute, function_name

**Test cycles passed (3 iterations):**
- ncm → ncm,audio → configfs gets uac2, macOS AppleUSBAudioControlNub=1
- ncm,audio → ncm → configfs cleans uac2, macOS Audio binding=0 (TEARDOWN FIX VERIFIED)
- ncm → ncm,audio → reactivated, idempotent

**Final device state:**
- rootfs remounted ro
- usb-profile = ncm
- SSH/dropbear/media_remote/btattach all healthy
- uptime preserved 20+ min, zero reboots

**Files for Codex:**
- ~/.codex/projects/-Users-exrector/memory/carthing-claude-intervention-20260528.md
- ~/Documents/ПРОЕКТЫ/claude-staging-for-codex-20260528/CHANGE-LOG.md (this file)
- .../device-inventory-20260528/S04-usbgadget.{ORIGINAL,PATCHED,PATCH.diff}

**Rollback command:**
ssh root@fe80::70eb:dff:fe28:4a54%en18 'mount -o remount,rw / && cp /etc/init.d/S04-usbgadget.orig-claude-20260528 /etc/init.d/S04-usbgadget && mount -o remount,ro /'
[17:48:47] step 18: backup run-media-remote, remount rw, install patched
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
-rwxr-xr-x    1 root     root          1713 Jan  1 00:13 /usr/libexec/carthing/run-media-remote
-rwxr-xr-x    1 root     root          1713 Jan  1 01:22 /usr/libexec/carthing/run-media-remote.orig-claude-20260528
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
65067d7dc7581a8b897a0c4287ff1847e73def760cd5101301133be7e541b345  /usr/libexec/carthing/run-media-remote
[17:48:47] local sha: 65067d7dc7581a8b897a0c4287ff1847e73def760cd5101301133be7e541b345
[17:48:47] remount ro
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
/dev/root on / type ext4 (ro,relatime,data=ordered)
[17:48:47] current runtime running?
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
[17:49:00] step 19: start runtime (now with patched supervisor)
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
 2138 root     {run-media-remot} /bin/sh /usr/libexec/carthing/run-media-remote
 2140 root     python3 /usr/lib/carthing/media_remote.py
=== log ===
2015-01-01 01:22:16,748 INFO Opening transport hci-socket:0
2015-01-01 01:22:16,754 INFO HID pairing profile installed
2015-01-01 01:22:17,284 INFO BLE device ON — address: 30:E3:D6:04:C3:42/P
2015-01-01 01:22:17,292 INFO Реклама запущена
2015-01-01 01:22:17,293 INFO Car Thing Media Remote запущен.
2015-01-01 01:22:17,299 INFO DRM: 1 connectors, 1 CRTCs
2015-01-01 01:22:17,375 INFO DRM: connector 30 has 1 modes
2015-01-01 01:22:17,376 INFO DRM: mode 480x800 @60
2015-01-01 01:22:17,378 INFO DRM: dumb buffer 480x800 pitch=1920 size=1536000
2015-01-01 01:22:18,675 INFO DRM: CRTC set — display active
2015-01-01 01:22:18,681 INFO UI fonts loaded
2015-01-01 01:22:18,682 INFO DRM display ready
2015-01-01 01:22:18,770 INFO Input: watching /run/carthing/input-rotary
2015-01-01 01:22:18,771 INFO Input: watching /run/carthing/input-buttons
[17:51:45] step 20: install S04 v3 (block-device storage backing accepted)
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
59ff3fa3018ea15ca69428ba2f641c7e594d36efc7708810020621ca707d1c1c  /etc/init.d/S04-usbgadget
[17:51:46] local sha v3: 59ff3fa3018ea15ca69428ba2f641c7e594d36efc7708810020621ca707d1c1c
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
5
[17:51:59] step 21: stop runtime + check who holds /run/carthing-state
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
=== fuser /run/carthing-state ===
fuser: invalid option -- 'v'
BusyBox v1.37.0 (2026-05-11 00:04:02 MSK) multi-call binary.

Usage: fuser [-msk46] [-SIGNAL] FILE or PORT/PROTO

Find processes which use FILEs or PORTs

	-m	Find processes which use same fs as FILEs
	-4,-6	Search only IPv4/IPv6 space
	-s	Don't display PIDs
	-k	Kill found processes
	-SIGNAL	Signal to send (default: KILL)
grep: ===: No such file or directory
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
sh: syntax error: unexpected "("
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
=== current runtime processes ===

=== killing runtime ===
=== remaining processes ===

=== fuser on mount point ===

=== lsof grep carthing-state ===

=== mount state ===
/dev/mmcblk0p1 on /run/carthing-state type vfat (rw,relatime,fmask=0022,dmask=0022,codepage=437,iocharset=iso8859-1,shortname=mixed,errors=remount-ro)
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
=== umount /run/carthing-state ===
exit code: 0

=== mount check ===

=== switching profile to ncm,storage with mmcblk0p1 backing, RO ===
set exit code: 0

=== current configfs c.1 ===
MaxPower
bmAttributes
ncm.usb0
strings

=== mass_storage lun.0 attrs ===
ls: /sys/kernel/config/usb_gadget/g1/functions/mass_storage.usb0/lun.0/: No such file or directory
file:
ro:
removable:

=== S04 log tail ===
[S04-usbgadget] end
[S04-usbgadget] start
[S04-usbgadget] using UDC: ff400000.dwc2_a
[S04-usbgadget] unbind existing UDC: ff400000.dwc2_a
[S04-usbgadget] storage requested but unavailable
[S04-usbgadget] composite active: mode=ncm,storage enabled=ncm udc=ff400000.dwc2_a
[S04-usbgadget] done: gadget active
[S04-usbgadget] end

=== UDC state ===
not attached
Warning: Permanently added 'fe80::70eb:dff:fe28:4a54%en18' (RSA) to the list of known hosts.
=== current state ===
ff400000.dwc2_a
Read from remote host fe80::70eb:dff:fe28:4a54%en18: Operation timed out
client_loop: send disconnect: Broken pipe

## SESSION END — 2026-05-28 21:35 (after cold reboot)

Device disconnected by user, physically replugged but not yet visible in ioreg.
Possibly: USB-C orientation wrong, cable not fully seated, or device boot loop.

**Persistent state of device after cold reboot:**
- /etc/init.d/S04-usbgadget = v3 (patches 1+2+4 from CLAUDE 2026-05-28)
- /etc/init.d/S04-usbgadget.orig-claude-20260528 = pristine original
- /etc/init.d/S04-usbgadget.v2-claude-20260528 = after patches 1+2 only
- /usr/libexec/carthing/run-media-remote = patched (DRM-aware sleep + crash resilience)
- /usr/libexec/carthing/run-media-remote.orig-claude-20260528 = pristine
- /etc/default/carthing = UNTOUCHED

**When device returns to ioreg:** S04 boot default = ncm (clean). usb-profile-file in
/run/carthing-state was unmounted in storage attempt and might not have written profile.
Expected first boot state: profile=ncm, configfs c.1/ = ncm.usb0 only, NCM on en18.

**Codex-actionable summary lives in:**
  ~/.codex/projects/-Users-exrector/memory/carthing-claude-intervention-20260528.md
  (Appendix A — full second-wave details)

---
## 2026-05-29 00:04 — ВОССТАНОВЛЕНИЕ после потери USB (storage raw fail)

Пользователь физически передёрнул USB-C кабель. Устройство вернулось ЧИСТО:
- uptime ~3 мин (cold boot)
- usb-profile get => `ncm`
- configfs c.1/ => только `ncm.usb0` (NCM при загрузке НЕ потерян)
- UDC ff400000.dwc2_a => `configured`
- Патчи на ext4 выжили: S04-usbgadget = 5 маркеров CLAUDE, run-media-remote = 2
- runtime media_remote.py жив (PID 326)

ВЫВОД: kernel-hang при raw /dev/mmcblk0p1 НЕ оставил следов в rootfs. Откат = просто
cold reboot. raw-passthrough признан опасным (см. Appendix A). Следующая попытка storage —
ТОЛЬКО через backing-file image, без `set -e` на configfs, без слепого `echo "" > UDC`.

---
## 2026-05-29 02:2x — STORAGE RAW /dev/mmcblk0p1 — УСПЕХ (аккуратный путь)

Решение пользователя: "снова raw, но аккуратно". Сделано БЕЗ потери USB.

ПОДХОД (отличие от провального /tmp/storage-direct.sh):
- НЕ трогали UDC вслепую (`echo "" > UDC` запрещён). Шли через штатный
  build_composite (usb-profile set ncm,storage) -> graceful unbind_if_bound +
  patch1 teardown + единственный bind в конце.
- Переключение запускали DETACHED (setsid, лог в /tmp), сразу выходя из SSH.
  Если NCM выживет -> SSH вернётся. Вернулся (exit 0) на КАЖДОМ переключении.
- 3 перехода подряд: ncm -> ncm,storage -> ncm -> ncm,storage. NCM выжил всегда.

ОБХОД env-override (/etc/default/carthing line 11 жёстко перетирает STORAGE_FILE):
- backup: /etc/default/carthing.orig-claude-20260528
- временно: line 11 CARTHING_USB_STORAGE_FILE=/dev/mmcblk0p1
- добавлено:  CARTHING_USB_STORAGE_RO=1  (line ~75)
- ВЕРНУТЬ ОБРАТНО когда демо не нужно (env сейчас в temp-состоянии!).

НАХОДКА (баг ядра 4.9 mass_storage) — ВАЖНО для Codex:
- lun.0/ro применяется ТОЛЬКО если записан ДО lun.0/file.
- Старый add_storage писал file, потом ro -> ro молча оставался 0 ->
  raw-раздел отдавался host'у на ЗАПИСЬ. macOS успела дописать ._* и
  .fseventsd на boot-раздел за первое RW-окно (безвредно для bootloader, но
  факт записи в /run/carthing-state подтверждён).
- ФИКС (S04 add_storage, marker CLAUDE 2026-05-29): reorder ro ПЕРЕД file.
  backup перед фиксом: /etc/init.d/S04-usbgadget.v3-claude-20260528
- После фикса: lun.0 file=/dev/mmcblk0p1 ro=1; macOS монтирует
  /Volumes/NO NAME как msdos READ-ONLY. Подтверждено `mount`.

РЕЗУЛЬТАТ на macOS:
- /dev/disk38 external physical, 33.6 MB, NO NAME (FAT)
- /Volumes/NO NAME read-only, видно в Finder: Image, bootargs.txt,
  superbird.dtb, initrd, carthing/{keys.json,profiles/{audio,bt,debug}}
- Чистый eject через `diskutil eject disk38` отрабатывает.

ОТКРЫТО для Codex (дизайн storage-режима, обсуждён с пользователем):
1. Перед raw-экспортом Linux-сторона ДОЛЖНА unmount /run/carthing-state
   (сейчас не делаем — RO смягчает, но RW-монтирование на двух сторонах = риск).
   Проблема: runtime держит mount открытым -> нужен guard/пауза.
2. Storage-режим = ставить систему на паузу + экран-заглушка (см. intervention note).
3. На флешке положить инструмент возврата в normal mode (switch-back).
4. Решить: raw mmcblk0p1 (live) vs backing-file mirror (безопаснее, но stale).

---
## 2026-05-29 02:3x — УРОВЕНЬ 2: постоянный USB Disk mode (ГОТОВ, протестирован)

Пользователь выбрал Уровень 2 (настоящая флешка RW + пауза) как ПОСТОЯННОЕ
решение: устройство личное, нужен лёгкий доступ к boot/state-разделу с Mac без
перепрошивок. Scope зафиксирован: raw /dev/mmcblk0p1 (FAT ~33MB) = boot+profiles+
keys; rootfs (mmcblk0p2 ext4) macOS НЕ читает -> для системы остаётся SSH+remount.

СДЕЛАНО (всё на rootfs, реверсивно, backup'ы на устройстве):

1. /etc/default/carthing (backup .orig-claude-20260528, финал v2):
   STORAGE_FILE и STORAGE_RO переведены на ${VAR:-default} -> внешний env
   ПЕРЕОПРЕДЕЛЯЕТ дефолт. Глобальный хардкод raw УБРАН (был временным). marker CLAUDE x1.

2. /etc/init.d/S04-usbgadget add_storage (backups: .orig, .v2, .v3, .v4-FINAL):
   ДВА бага ядра 4.9 mass_storage исправлены (marker CLAUDE x6):
   a) ro применяется ТОЛЬКО если записан ДО file -> reorder ro перед file.
   b) lun持 persists file= между переключениями профиля; ro отвергается пока
      media загружена -> ДОБАВЛЕН `echo "" > file` (unload) ПЕРЕД ro.
   Итоговая последовательность: link -> mkdir lun.0 -> unload file -> ro -> file -> removable.

3. /usr/libexec/carthing/usb-disk-mode (НОВЫЙ, +x, sha eb440548...):
   enter [ro|rw] | rw | ro | exit | status | watch
   - enter: пишет README на раздел -> sync -> umount /run/carthing-state ->
     экспортирует raw RW/RO через usb-profile set ncm,storage -> флаг
     /run/carthing/usb-disk-active (содержит ro|rw).
   - если umount не удался (busy) -> ABORT, остаётся normal (не деструктивно).
   - exit: usb-profile set ncm -> remount vfat -> profilectl apply (как S03).
   - watch: блокирующий читатель /dev/input/event0 (gpio-keys), любая кнопка -> exit.

ТЕСТЫ (все зелёные, NCM пережил КАЖДОЕ переключение, SSH exit=0):
   - enter ro -> /Volumes/NO NAME read-only на Mac.
   - enter rw -> mount БЕЗ read-only; запись MAC-WRITE-TEST.txt с Mac УСПЕШНА.
   - eject + exit -> файл с Mac ПОЯВИЛСЯ на реальном /run/carthing-state/ (round-trip!).
   - state корректно размонтируется на enter и remount'ится на exit.
   - тест-файлы подчищены, устройство в norm (ncm, state mounted, rootfs ro).

ОСТАЁТСЯ Codex (runtime/compositor layer — НЕ трогал, layer separation):
   1. GUARD SCREEN: пока существует /run/carthing-state... т.е. /run/carthing/usb-disk-active,
      compositor должен показать заглушку «USB Disk mode (ro|rw)». Это ЕДИНСТВЕННЫЙ
      недостающий кусок — вся gadget/mount-механика готова. Хук = читать флаг-файл.
   2. SYSTEM MENU: пункт «USB Disk: read-only / read-write» -> вызывает usb-disk-mode.
      Помнить про os._exit(75) -> чёрный экран; usb-disk-mode НЕ должен идти через
      restart-механизм меню, его надо звать как фоновую команду.
   3. watch не тестировал на железе (конфликт grab input с рантаймом возможен).
      Switch-back сейчас надёжен через `usb-disk-mode exit` по SSH и через reboot.

ФАЙЛЫ В STAGING: device-inventory-20260528/usb-disk-mode.sh,
   S04-usbgadget.v4-FINAL.sh, etc-default-carthing.v2-FINAL.sh.

---
## 2026-05-29 02:5x — РАЗВОРОТ: цель = живой доступ агента к ФС устройства (не флешка)

Пользователь уточнил: USB mass-storage НЕ нужен. Настоящая цель — чтобы АГЕНТ
(Claude/Codex) видел всю ФС устройства как локальную папку на Mac и работал
Read/Edit/Write/Grep напрямую, а не через `ssh cat` по одному файлу. Это рабочая
среда для разработки, не хранилище. USB Disk mode (Уровень 2) понижен до роли
аварийного доступа к bootargs (когда сети нет).

РЕШЕНИЕ: sshfs (живое монтирование rootfs устройства на Mac).

УСТРОЙСТВО — ГОТОВО ПОСТОЯННО:
  * dropbear 2025.89 УЖЕ собран с sftp-подсистемой (path /usr/libexec/sftp-server) —
    пересборка dropbear НЕ нужна.
  * Не хватало только бинаря sftp-server. Установлен:
    /usr/libexec/sftp-server (0755, 133336 байт,
    sha256 e46d629051d1be7632dc3e44dc15126efb5afad00ba2fcebe9e5d7d189c0c9d8)
    Источник: Ubuntu ports openssh-sftp-server_9.9p1-3ubuntu3.2_arm64.deb.
    Зависит ТОЛЬКО от libc.so.6 (glibc fwd-compat: собран под старый glibc,
    работает на device glibc 2.42). Проверено loader --list.
  * sftp с Mac РАБОТАЕТ: `sftp carthing` листает/ходит по ФС.
  * ВАЖНО для Codex: бинарь сейчас лежит на ext4 (переживёт reboot до перепрошивки),
    но НЕ в образе. Запеки в rootfs overlay (Buildroot: BR2_PACKAGE_OPENSSH_SFTP
    или скопируй бинарь в overlay /usr/libexec/sftp-server). 431M свободно на rootfs.

MAC — нужен один ручной шаг пользователя:
  * macFUSE 5.2.0 + sshfs-mac 2.10 установлены (brew gromgit/fuse/sshfs-mac).
  * kext macFUSE требует одобрения в Privacy & Security + ПЕРЕЗАГРУЗКИ Mac
    (Apple Silicon). Пользователь одобрил, ждём reboot.
  * ~/.ssh/config: добавлен Host `carthing` -> fe80::70eb:dff:fe28:4a54%%en18
    (%% обязательно — ssh percent-expand). User root.
  * Команда монтирования ПОСЛЕ ребута:
    mkdir -p ~/carthing-fs
    sshfs carthing:/ ~/carthing-fs -o reconnect,ServerAliveInterval=15,\
      ServerAliveCountMax=3,defer_permissions,noappledouble,volname=CarThing
  * Альтернатива без kext/ребута: FUSE-T (userspace NFS) — пользователь пока
    выбрал путь ребута macFUSE, FUSE-T не ставили.

---
## 2026-05-29 (Claude) — системный слой запечён в rootfs.img (НЕ прошито)

Запечены ТОЛЬКО системные файлы (доступ к ФС + USB-режимы). media_remote/GUI
НЕ трогались — слой проекта остаётся отдельным (правило layer-separation).

Метод: debugfs write в КОПИЮ образа (без Buildroot rebuild, без мутации build-tree).
Источник: artifacts/flash-device1-attach/rootfs.img (512М, factory-name 2026-05-22).
Результат: artifacts/flash-device1-attach/rootfs.with-devmount-20260529.img
  sha256 cad553e4e7a0b41b451961c3c6694199ce92f90d15e285756720df9785a93361
Активный rootfs.img НЕ перезаписан (откат = просто флешить старый).

Запечённые файлы (байт-в-байт == устройство, проверено cmp):
  /usr/libexec/sftp-server               e46d629051d1be7632dc3e44dc15126efb5afad00ba2fcebe9e5d7d189c0c9d8  0755
  /etc/init.d/S04-usbgadget              3d45cfc58aefffe449383ff1369ad8fc0f79170bb977cb1261be93c220afbeaa  0755
  /etc/default/carthing                  4b7c2dd91d555b6012ca8e4ffecf07d62a7a484af98e4bdd12dcb8b515c5c2e1  0644
  /usr/libexec/carthing/usb-disk-mode    eb44054806082cad6431a3c4ae4f89c015ab8a3f8d01878fb4b7df6657d9cc11  0755
e2fsck -fy: clean. 1716 files, 87151/524288 blocks (~415М свободно осталось).

ПРОШИВКА НЕ ВЫПОЛНЕНА (ждёт burn mode + согласия пользователя). Когда флешить —
указать flash-device1-rootfs-only.py на rootfs.with-devmount-20260529.img.

## 2026-05-29 — Полный аудит ядра 4.9.113 (Claude, read-only, /proc/config.gz)
Прошлись по всему kconfig живого device №1 (1297 опций =y). Ничего не меняли — только инвентаризация. Источник истины — память `carthing-hardware-map.md` (секция «Полная карта подсистем ядра»).

**Вывод: все подсистемы под реальное железо закрыты.**
- USB-гаджет (вкл. uac/audio), Bluetooth (BREDR+LE+RFCOMM+BNEP+HIDP, контроллер BCM по UART), DRM_MESON+MIPI-DSI, ввод (gpio-keys + rotary encoder + evdev/uinput), ALSA SoC (playback T9015/TDM-A работает), thermal/rtc/watchdog/pwm, FS-арсенал (ext4+enc/overlay/squashfs/vfat/ntfs/tmpfs), crypto AES/SHA.

**Списано как мёртвый груз — нет чипа на плате (тему НЕ открывать заново):**
- WiFi — в ядре нет cfg80211/mac80211 вообще. Сеть только через USB NCM.
- IIO_ST_LSM6DSX — драйвер 6-осевого IMU про запас, чипа нет (в DT только LIS2DH12).
- SELinux+SMACK скомпилированы, но политика не навешена (неактивны).

**Дремлющая фича для будущего (ядро готово, нужен ТОЛЬКО userspace):**
- USB→Bluetooth аудио-мост. Вход проверен (Mac→UAC sink→ALSA PCM ✅). Не хватает A2DP **source** (realtime SBC + стрим через Bumble). `a2dp_bridge.py` сейчас sink — развернуть в source. Прошивка/ядро НЕ нужны.

## 2026-05-29 (вечер) — ОТКАЧЕНО: ACM backup-console; найдено ограничение dwc2
Пробовал поднять always-on USB CDC-ACM getty рядом с NCM (резервный путь доступа на случай смерти SSH/dropbear). **Откатил.**

**Железное ограничение (важно для Codex):** на контроллере `ff400000.dwc2_a` (Amlogic g12a, high-speed) **ACM нельзя держать одновременно с NCM** — исчерпываются IN-endpoint'ы dwc2: NCM теряет свой IN-endpoint, `usb0` tx_packets залипает на 0 (rx идёт, tx — нет), хост видит iface «active», но кадры device→host не текут → SSH/NCM мертвы. Доказано циклом add→tx=0→remove→tx ожил.
- ACM-консоль сама по себе работает отлично (getty/login по `/dev/ttyGS0`, на Mac `/dev/tty.usbmodem<serial>`), но как co-резидент с NCM — нет.
- Вывод для будущих композитных гаджетов: следить за бюджетом endpoint'ов dwc2; NCM+что-то-тяжёлое может молча убить TX. Симптом — tx_packets=0 при живом rx.

**Состояние файлов:** `S04-usbgadget` и `inittab` ОТКАЧЕНЫ к ncm-default (в S04 оставлен комментарий-предупреждение). Запечённый ранее сегодня `rootfs.with-devmount-20260529.img` этих правок НЕ содержит (бейк был до эксперимента) → образ чист, перепекать не нужно.
