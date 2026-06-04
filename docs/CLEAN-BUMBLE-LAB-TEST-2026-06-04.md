# Clean Bumble Lab Test

Date: 2026-06-04

Purpose: isolate whether Bumble itself breaks iPhone dual-mode behavior, or
whether previous failures were caused by extra services/proxies/scripts around
it.

This is a lab-only test. It must not become release boot behavior.

## Preconditions

- Normal boot has Bumble quarantined.
- No `carthing_runtime.py`, `run-media-remote`, or `hci_proxy.py` process is
  running.
- iPhone has forgotten all previous Car Thing rows.
- Local/device keystore for the test is clean.
- Only one process owns HCI.
- iAP2/MFi RFCOMM surface is off unless this specific test asks for it.
- Post-pair Classic probe is off unless this specific test asks for it.

## Strict Test Matrix

Run tests one at a time, reboot or fully stop HCI owner between rows if HCI state
looks sticky.

1. Pure BLE media remote only
   - BLE advertising flags must be dual-mode capable, not BR/EDR-not-supported.
   - No A2DP SDP.
   - No AVRCP SDP.
   - Expected: one visible iPhone pairing surface, remote-control behavior only.

2. BLE media remote + Classic A2DP Sink + AVRCP Target
   - No iAP2.
   - No post-pair Classic probe.
   - Expected: one logical iPhone accessory; Control Center should show Car
     Thing as an audio output if iOS accepts the dual-mode image.

3. Same as row 2, then explicit post-pair Classic auth probe
   - Expected: if authentication fails, record exact HCI error and whether iOS
     creates a second visible row.

4. Same as row 2 + iAP2/MFi surface
   - Expected: check whether iOS creates generic `Accessory`/`Аксессуар` row.

## Pass/Fail Rules

Pass:
- iPhone pairing is done once.
- iPhone settings eventually collapse to one logical accessory row.
- Control Center audio output appears in the A2DP row.
- No third advertising/pairing surface remains visible after pairing settles.

Fail:
- user has to pair twice;
- iPhone shows a second persistent connected row;
- a third connectable row remains visible;
- Control Center never shows audio output in row 2;
- HCI authentication fails after CTKD with `0x05` or another reproducible code.

## Why This Exists

The release tree now quarantines Bumble because previous live tests mixed too
many moving parts: BLE, Classic SDP, CTKD, iAP2, A2DP bridge, HCI proxy, local
Mac runtime, and device-side scripts. A clean Bumble test may still be useful,
but only if it proves one layer at a time.

Do not remove quarantine for normal boot to run this. Use explicit lab override
only.
