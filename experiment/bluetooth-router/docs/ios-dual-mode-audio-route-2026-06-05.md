# iPhone Unified Dual-Mode Audio Route Experiment

Date: 2026-06-05

## Proven

- One iPhone user-visible Bluetooth row can represent the Car Thing BLE and
  Classic transports.
- One Bumble keystore identity contains the iPhone `ltk`, `irk`, and Classic
  `link_key`.
- The Classic link derived by CTKD/CT2 authenticates and encrypts.
- BLE AMS, ANCS, and CTS reconnect and work.
- The iPhone accepts AVCTP/AVRCP.
- The iPhone initiates AVDTP, configures AAC 44.1 kHz stereo at 256 kbps, and
  opens the Car Thing A2DP Sink.

This proves that the remaining failure is not basic dual-mode identity, CTKD,
Classic authentication, AVRCP connectivity, or AVDTP reachability.

## Remaining Failure

The iPhone still does not publish Car Thing as an audio output in Control
Center. After opening AVDTP, it closes the stream channel about ten seconds
later without sending `START`.

## Defects Found And Fixed

- Bumble `PairingConfig` did not expose or negotiate CT2. The local vendor copy
  now does.
- The headless runtime did not provide an `AppState` to Transfer and could not
  find the bonded source without the GUI.
- The Classic EIR exposed iAP2 even when iAP2 was disabled.
- AVRCP SDP existed without a live AVCTP/AVRCP listener.
- The upgraded Bumble codec API was not integrated.
- Bumble's AudioSink SDP helper omitted A2DP `SupportedFeatures (0x0311)`.
  Car Thing now identifies the sink as a speaker (`0x0002`).
- The incoming A2DP Sink exposed only optional AAC. A conforming A2DP Sink must
  also expose SBC, so Car Thing now exposes AAC and SBC endpoints.

## Current Runtime Evidence

The temporary hardware test runtime is under `/run/carthing-dual-mode-lab`.
It is intentionally not baked into rootfs yet.

The preserved logs and checksums are under:

`artifacts/dual-mode-20260605/`

The latest device log is:

`/run/carthing/dual-mode-speaker-sdp-sbc.log`

Expected markers:

```text
A2DP SDP records installed: AudioSink(Speaker) + AVRCP Controller/Target
A2DP source sink endpoint installed: codec=AAC seid=1
A2DP source sink endpoint installed: codec=SBC seid=2
A2DP_SOURCE_SET_CONFIGURATION codec=AAC
A2DP_SOURCE_OPEN codec=AAC
```

## Next Controlled Test

The current iPhone pairing may retain the old SDP image. The next test must be
one clean first-pair run with the complete profile already active:

1. Disable the immediate post-pair Classic probe.
2. Clear the Car Thing iPhone bond only after the user forgets Car Thing on the
   iPhone.
3. Start pairing with the complete AudioSink(Speaker), AAC+SBC, AVRCP
   Controller/Target, CoD `0x240414`, CTKD/CT2 profile.
4. Let the first pair settle before dialing Classic.
5. Enable the Classic probe, verify one iPhone row, and check Control Center.

Do not change several profile variables during this test. If it still fails,
the next isolated comparison is Classic-first pairing versus BLE-first CTKD.

## Primary Specification Notes

- Bluetooth A2DP 1.3.2 requires an A2DP Sink to support SBC.
- The A2DP Sink SDP record defines `SupportedFeatures (0x0311)`; bit `0x0002`
  identifies a speaker.
- A2DP 1.3.2 requires Delay Reporting support from a Sink. Bumble's local Sink
  endpoint currently does not advertise or initiate Delay Reporting. This is a
  remaining standards-compliance gap to evaluate after the clean-pair test.

## Classic-First CTKD And AVRCP Handshake Result

The Classic-first pairing test derived the LE bond through SMP over BR/EDR in
one user pairing action. The resulting identity contains an authenticated
Classic link key, LTK, and IRK. This proves the unified dual-mode bond itself is
working.

The follow-up reconnect test preserved that pair and added the missing AVRCP
session behavior:

- Car Thing's AVRCP Target advertises `VOLUME_CHANGED` and accepts Absolute
  Volume commands.
- Car Thing's AVRCP Controller queries the iPhone's supported events and
  registers for playback-status notifications.
- The iPhone returned its AVRCP event set and an initial playback status.
- The iPhone again configured and opened the AAC A2DP endpoint.
- The delay report was accepted, correcting the earlier gap noted above.

The iPhone still did not send AVDTP `START`; it closed the AVDTP signaling
channel about ten seconds after `OPEN`. Therefore the remaining failure is
later than pairing, CTKD, Classic authentication, AVRCP setup, endpoint
selection, and Delay Reporting.

Evidence:

`artifacts/dual-mode-20260605/classic-first-avrcp-handshake.log`

## Resolved: L2CAP Flush Timeout Blocked The iPhone Media Channel

The final hardware comparison found the failure below AVDTP. The iPhone added
the L2CAP `FLUSH_TIMEOUT` option with value `0x00C8` when configuring the A2DP
media channel. Vendored Bumble rejected that known option with
`FAILURE_UNKNOWN_OPTIONS`, so the peers repeated L2CAP configuration and the
media channel never reached OPEN. Without an open media channel, iOS did not
send AVDTP `START` and did not publish Car Thing as an active Control Center
audio route.

The runtime fix:

- implements `HCI_Write_Automatic_Flush_Timeout_Command`;
- accepts the Classic L2CAP `FLUSH_TIMEOUT` option;
- records it as the peer sender's flush policy without incorrectly applying it
  to the local controller;
- replies to L2CAP configuration with success.

The full dual-mode runtime then proved the intended single-accessory behavior:

- the existing dual-mode pair was reused; no second user pairing was needed;
- Linux-side Classic audio activation made `Car Thing (SN: QN19)` connect and
  appear automatically in the iPhone Control Center;
- iOS selected AAC, opened the RTP channel, sent AVDTP `START`, and streamed
  real RTP packets;
- AVRCP Absolute Volume arrived from the iPhone.

The current route has no trusted output speaker selected, so the bridge
correctly drops the received packets after proving the iPhone input side.
Connecting and routing to a trusted speaker is the next independent route-graph
step, not part of this resolved iPhone dual-mode issue.

Preserved evidence:

- `artifacts/dual-mode-20260605/iphone-a2dp-sink-before-flush-fix.log`
- `artifacts/dual-mode-20260605/iphone-a2dp-sink-after-flush-fix.log`
- `artifacts/dual-mode-20260605/dual-mode-flush-fix-success.log`

Required success markers:

```text
dual-mode host enabled: LE + Classic + simultaneous + SMP/CTKD
A2DP_SOURCE_OPEN codec=AAC
A2DP_SOURCE_RTP_OPEN codec=AAC
AVRCP target absolute volume=56
A2DP_SOURCE_START codec=AAC
A2DP_BRIDGE_RTP
```

This result currently runs from the temporary lab runtime under
`/run/carthing-dual-mode-lab`. It is not persistent across reboot until the
release overlay is baked into rootfs and flashed.

## Specification-Correct Peer Flush Policy Rerun

A pre-commit protocol review found that the first working patch did one
unnecessary operation: it applied the iPhone's incoming L2CAP Flush Timeout to
the local HCI controller. That is incorrect because the incoming L2CAP value is
the remote sender's policy in milliseconds, while the HCI command controls the
local sender and uses 0.625 ms slots.

The final implementation therefore accepts and records the peer policy, replies
with Configure Success, and does not issue a local HCI command from that path.
The HCI command implementation remains available and serialization-tested for
future explicit local-controller policy.

The corrected full dual-mode runtime was restarted remotely with the same bond
and proved:

```text
dual-mode host enabled: LE + Classic + simultaneous + SMP/CTKD
classic audio reconnect ready: 10:A2:D3:83:82:50
A2DP_SOURCE_SET_CONFIGURATION codec=AAC
A2DP_SOURCE_OPEN codec=AAC
A2DP_SOURCE_RTP_OPEN codec=AAC
```

The iPhone was paused during this corrected rerun, so no new AVDTP `START` was
expected. The earlier full-stream run remains the evidence for `START`, RTP,
and Absolute Volume. Corrected-rerun evidence:

`artifacts/dual-mode-20260605/dual-mode-peer-flush-policy-success.log`
