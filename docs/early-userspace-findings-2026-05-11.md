# Early Userspace Findings 2026-05-11

This note locks in the current diagnosis for device `№1` after the latest `rootfs-only` bring-up runs.

It is intentionally scoped to:

- `Buildroot` image construction
- `BusyBox` init and early service orchestration
- embedded Python startup in stage-2 userspace

It is not a device-model note and it is not a SoC note.

## Live Observations Locked In

- The current failure is **not** at the chip, kernel, or USB gadget layer:
  - `NCM Gadget` appears on macOS as `en14`
  - host-side `172.16.42.1/24` and route pinning to `en14` work
  - `172.16.42.77` responds
  - `172.16.42.84` responds
- The current failure is **not** a total stage-2 networking failure:
  - stage-2 network is alive
  - ARP resolves to a stable target MAC
- The current failure is still above stage-2 networking:
  - `22/tcp`, `8080/tcp`, and `2323/tcp` on `172.16.42.77` return `Connection refused`
  - the reverse control queue remains in host-side `pending/`
  - no agent poll or result arrives at the host
- The latest diagnostic image adds `.189` and that marker now responds:
  - `172.16.42.189` = module-level probe failed before `main()`
- Host beacon logs show repeated:
  - `s07-started`
  - `s08-started`
  - `s09-module-probe-failed`
  - repeating roughly every `5-6` seconds

## What The Sources Confirm

### Buildroot

Buildroot explicitly treats target ownership and permissions as a `fakeroot`/post-fakeroot concern, not something to leave to host filesystem metadata.

That matches the earlier real regression where a host-owned fallback image (`uid 501/gid 20`) destabilized early boot and the `root:root` rebuild restored the old `.77/.84/.185` behavior.

Source:

- https://buildroot.org/downloads/manual/manual.html

### BusyBox

BusyBox documentation confirms:

- `httpd -f -p [IP:]PORT -h HOME` is a valid applet invocation
- `telnetd -F -p PORT -l LOGIN` is a valid applet invocation

That means our `S07-debug-http` and `S08-debug-telnet` scripts are not failing because they use impossible BusyBox flags.

BusyBox FAQ also reinforces a broader point:

- BusyBox is not the whole system
- the real system behavior comes from shell scripts, config, filesystem layout, and boot orchestration around it

That matches the current repo state: the most suspicious behavior is in our own init/orchestration layer, not in BusyBox itself.

Sources:

- https://busybox.net/BusyBox.html
- https://busybox.net/FAQ.html

### Python `runpy`

`runpy.run_path()` executes a script's top-level code before any guarded `if __name__ == "__main__"` entrypoint logic.

That means the `.189` marker is highly informative:

- the failure happens while importing/initializing the module namespace
- it happens before `main()`
- it is therefore most likely in top-level config loading, parsing, or import-time assumptions

Source:

- https://docs.python.org/3.15/library/runpy.html

## Current Local Conclusions

The current problem is best modeled as an early-userspace orchestration failure of our own making, not as a hardware mystery.

The two strongest suspects are:

1. `init-wrapper` retries `S05..S09` in a background loop every `5` seconds for `18` attempts.
2. `reverse-agent.py` performs config loading and integer parsing at module top-level.

Those map directly to the code:

- [overlay/usr/libexec/carthing/init-wrapper](overlay/usr/libexec/carthing/init-wrapper:69)
- [overlay/usr/libexec/carthing/reverse-agent.py](overlay/usr/libexec/carthing/reverse-agent.py:31)

The repeated beacons are consistent with the `init-wrapper` retry loop, not with a single clean boot attempt.

The `.189` marker is consistent with module-top-level failure in `reverse-agent.py`, not with a runtime failure inside the polling loop.

## Cleanup Order

The next cleanup pass should be conservative and should reduce noise before adding new diagnostics:

1. Remove or disable the `init-wrapper` retry loop so `S07/S08/S09` do not keep relaunching in the background.
2. Move `reverse-agent.py` config loading and numeric parsing out of module top-level and into runtime code.
3. Temporarily disable `S07-debug-http` and `S08-debug-telnet` while narrowing `S09`, so ingress noise does not mask the reverse-agent path.
4. Keep one narrow diagnostic path that records the exact module-probe exception, not just the `.189` marker.

## What This Means Practically

The next step should not be another blind flash cycle.

The next step should be a cleanup-first patch set that:

- reduces early boot churn
- removes self-inflicted relaunch noise
- makes Python startup deterministic
- only then re-tests ingress
