# Code review: standby/reconnect + passport (Claude, 2026-06-13)

Review only, no rewrite. Scope: in-repo Bumble runtime. No BlueZ proposed.
Files read in full: `a2dp_bridge.py` (SpeakerRuntime, standby/receiver loops,
request/connect/setup_receiver, gate, persist), `app_state.py` (registry/route
selection/remove/revoke), `transfer_service.py` (forget/activate),
`virtual_connectors.py` (HciOperationGate), `carthing_runtime.py` (route apply).

Verdict: the card-catalog model (one `SpeakerRuntime` per output, per-card
standby/backoff, exclusive `active_route_output`, passport persist) is sound and
matches the owner's vision. Delete path (`forget_speaker_runtime` +
`remove_trusted` + `forget_peer_key`) is correct and complete. The live symptoms
trace to a few concrete bugs in backoff/serialization, below.

---

## P1-1 — AVDTP discover timeout instantly locks a card for 300 s; enrollment-incomplete cards (AirFly) can never collect codecs

- File/func: `a2dp_bridge.py::_connect_receiver` (≈1531-1536); passport persist
  `_persist_receiver_avdtp_profile` (≈1129) runs only on the full-success path
  after `setup_receiver` discovery+codec select (≈998).
- Behavior: on `"avdtp discover timeout"` the retry delay is forced to **300 s
  immediately**, bypassing progressive backoff:
  ```
  if "avdtp discover timeout" in connector.last_error.lower():
      delay = 300.0
  ```
- Risk / why it explains the symptom: AirFly gets an encrypted ACL but its AVDTP
  discovery is slow/flaky and times out once → card is frozen for 5 minutes →
  `_persist_receiver_avdtp_profile` never runs → the card stays without
  `avdtp_profile.supported_codecs` forever (exactly the observed AirFly state).
  A device that is *almost* enrolling is punished harder than an off device.
- Minimal fix: make the 300 s special-case apply only after **N consecutive**
  discover timeouts (e.g. ≥3). For a card whose passport has no
  `avdtp_profile.supported_codecs` yet, keep a **short** retry (e.g. 8–15 s) —
  enrollment-incomplete cards deserve faster retry, not slower. Progressive
  `12·2^failures` already exists for the general case; just don't shortcut it.
- Verify: power AirFly on after reboot; confirm it retries within ~15 s (not
  300 s) and that `avdtp_profile.supported_codecs` lands in its card; confirm an
  off device still climbs to the 300 s cap and does not hammer.

## P1-2 — single global HCI gate held for the full 20 s speculative page stalls all transport

- File/func: `virtual_connectors.py::HciOperationGate` (one `asyncio.Lock`);
  `a2dp_bridge.py::ensure_speaker_connection` wraps
  `device.connect(addr, BR_EDR)` in `_gate(...)` with `timeout=self.connect_timeout`
  (`connect_timeout=20.0`, ≈323).
- Behavior: every HCI op (source auth/encrypt, AVRCP, each speaker connect,
  AVDTP) serializes on one lock. A speculative standby page to an **off** speaker
  holds the lock until PAGE_TIMEOUT (~5 s) or 20 s. During that hold nothing else
  on the chip proceeds.
- Risk / why: after reboot the standby loop iterates Fosi/Maedhawk/AirFly each
  cycle; each off-device page monopolizes the chip, so the *online/selected*
  output and AVDTP discovery get starved → contributes to "everything in
  backoff/connecting after reboot", and lengthens AVDTP windows (feeds P1-1).
- Minimal fix: use a **short page timeout for speculative standby connects**
  (≈6–8 s, near the controller PAGE_TIMEOUT) distinct from the 20 s used for
  active-route/AVDTP ops; do not let a speculative page hold the gate for 20 s.
  Optionally page off-devices at most once per several standby cycles.
- Verify: with two off speakers + one online, confirm the online one reaches
  STREAMING without multi-second stalls; measure gate hold time in the log.

## P2-1 — two loops both drive paging of the selected speaker

- File/func: `speaker_standby_loop`→`ensure_trusted_speakers_connected` (≈739)
  and `receiver_loop` (≈833) both call `request_receiver_connection()` every
  `reconnect_interval`, both targeting the selected speaker.
- Risk: redundant page attempts and double backoff accounting; mostly deduped by
  `active_task()` and the page guard, but adds churn and makes reasoning hard.
- Minimal fix: make paging single-owner — `receiver_loop` should only **resume**
  an already-held selected session (`connector.stream` present), and delegate all
  cold paging to the standby loop. Keep one driver responsible for `request_*`.
- Verify: log shows exactly one connect task per address per cycle.

## P2-2 — page-serialization guard reopens too early (ACL up, AVDTP still running)

- File/func: `a2dp_bridge.py::_has_active_receiver_page` (≈451) returns True only
  while `connector.connection is None`.
- Behavior: once a card has its ACL (connection set) but is mid-AVDTP discovery,
  the guard returns False, so another card may start paging concurrently. Both
  serialize on the global gate, but a fresh page can then block the in-flight
  AVDTP discovery → discover timeout → P1-1.
- Minimal fix: treat "any runtime with an active connect_task that has not yet
  reached `rtp_channel`/STREAMING" as an active page for serialization, not just
  `connection is None`.
- Verify: while one card is in AVDTP discovery, confirm no second page starts.

## P3-1 — passport recorded only on full success; degraded cards look healthy

- File/func: `_persist_receiver_avdtp_profile` (≈1129) only on success path.
- Risk (prompt focus #4): a card that connects but never completes discovery is a
  trusted output with no `avdtp_profile`; GUI/route may treat it as usable with no
  visible "degraded" status.
- Minimal fix: persist partial evidence with explicit status
  (`classic_sdp_ready`, `acl_ok`, `avdtp_discover_failed`, `codecs: unknown`) and
  surface it via `speaker_statuses()`; never present an un-enrolled output as
  ready.
- Verify: AirFly before codec discovery shows `degraded/enrolling`, not `online`.

## P3-2 — missing tests for the invariants above

- `scripts/smoke-route-graph.py` exists but does not assert: (a) one discover
  timeout does not 300 s-lock an enrollment-incomplete card; (b) standby paging
  stays serialized and bounded; (c) `forget` clears runtime+keys+route+flags
  (the code is correct but untested); (d) OUT+/enrollment never mutates
  `active_route_output`.
- Minimal fix: add focused unit tests around `SpeakerRuntime` backoff and a
  fake-device standby cycle; assert route-selection isolation in `app_state`.

---

## Clean areas (verified, no action)

- Delete/remove: `transfer_service.forget_trusted` →
  `bridge.forget_speaker_runtime` (cancels task, clears standby/connector) +
  `state.remove_trusted` + `forget_peer_key`. Complete.
- Route-selection isolation: `_active_route_output` is set only by
  `select_active_route_output`, boot Play-Now, and remove/revoke→SELF. Enrollment
  does not touch it. Matches the constraint.
- Per-card standby: `ensure_trusted_speakers_connected` no longer suppresses
  non-selected outputs; selected is sorted first; backoff is per `SpeakerRuntime`.
