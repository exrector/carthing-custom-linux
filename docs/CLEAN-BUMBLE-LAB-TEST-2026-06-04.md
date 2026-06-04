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

## Result 2026-06-04 — Row 1, Pure BLE media remote

Runtime was launched manually with:

```sh
CARTHING_GUI_ENABLE=0
CARTHING_TRANSFER_ENABLE=0
CARTHING_A2DP_BRIDGE_ENABLE=0
CARTHING_IAP2_ENABLE=0
CARTHING_POST_PAIR_CLASSIC_PROBE=0
CAR_THING_AUTO_PAIRING=1
```

Observed on device:
- `carthing_runtime.py` started from `/run/run-clean-bumble.sh`;
- GUI must be disabled for the lab; iPhone Settings is the source of truth, not
  the device screen;
- `transfer disabled by CARTHING_TRANSFER_ENABLE=0 for clean Bumble lab`;
- `iAP2 disabled by default for clean dual-mode audio pairing`;
- BLE advertising started with flags `0x1a`;
- iPhone connected over BLE as current RPA `75:29:2F:66:20:DA`;
- AMS, ANCS, CTS all came up successfully;
- Bumble keystore has one bond identity: `10:A2:D3:83:82:50/P`;
- `state.json` has one trusted source: `source:10:A2:D3:83:82:50`;
- legacy `trusted-devices.json` remains empty.

Interpretation:
- Row 1 did not create two device-side trusted records.
- The apparent two-address situation is BLE privacy: active RPA versus stored
  identity address.
- The current state merger still gives the bonded source potential
  `audio_input/classic_a2dp_sink` capabilities even when transfer is disabled
  for the lab. That is acceptable for production route planning, but it makes
  row 1 less visually pure and should be accounted for when reading the GUI.

Open question from user-facing observation:
- If iPhone Settings itself shows two persistent rows after exiting and
  re-entering Bluetooth, that is not explained by device-side storage and must
  be treated as an iOS-visible advertising/persona problem.
- If only the Car Thing GUI/technical list shows two addresses, it is most
  likely RPA-vs-identity presentation and should be normalized in the UI.

## Result 2026-06-04 — LE-only control after dual-mode cache

Runtime was restarted headless with Classic completely disabled:

```sh
CARTHING_GUI_ENABLE=0
CARTHING_TRANSFER_ENABLE=0
CARTHING_CLASSIC_ENABLE=0
CARTHING_A2DP_BRIDGE_ENABLE=0
CARTHING_IAP2_ENABLE=0
CARTHING_POST_PAIR_CLASSIC_PROBE=0
CAR_THING_AUTO_PAIRING=1
```

Observed on device:
- `classic disabled by CARTHING_CLASSIC_ENABLE=0 for LE-only lab`;
- advertising flags became `0x06 LE General,No BR/EDR`;
- iPhone connected briefly over BLE as `63:CF:FF:2F:7D:B3`;
- device requested pairing;
- no completed bond was written: `keys.json` stayed `{}`;
- `state.json` stayed empty;
- runtime state stayed `source=none`, `connected=false`.

Observed by user on iPhone:
- one of the two old trusted rows first became disconnected but remained listed;
- the other row changed/appeared as plain `Car Thing`;
- the disconnected old row eventually disappeared;
- only plain `Car Thing` remained;
- later that remaining `Car Thing` also became `Not Connected`.

Interpretation:
- LE-only control appears to make iOS collapse or rewrite the previous dual-mode
  cache, but it did not complete a fresh bond on the device in this run.
- This supports separating two issues:
  1. the dual-mode Bumble/CTKD presentation creates two iOS-visible rows;
  2. after switching to LE-only, iOS can collapse stale rows, but a new clean
     bond still needs to be explicitly created and verified.
