# Merge handoff for Codex — 2026-05-20

Single point of reference so the two trees do not silently diverge before the
unified-firmware merge.

## The three commits that matter

```
135c00b  tag device1-v1-working-20260518   COMMON ANCESTOR (git merge-base)
   |                                         "freeze v1 working baseline"
   ├── master                a9db13b  tag merge-anchor-master-20260520
   |        (Codex: iAP2 experiments)
   └── fix/ancs-solicitation-reconnect  22a294c  tag merge-anchor-ui-20260520
            (UI/BLE branch — starts heavy UI work AFTER this commit)
```

`git merge-base master fix/ancs-solicitation-reconnect` = **135c00b**. This is the
single origin both trees share; git uses it as the 3-way merge base.

## The key fact (makes the merge cheap)

At BOTH anchor tags the entire `overlay/usr/lib/carthing/` tree is **byte-identical**:

```
git rev-parse merge-anchor-ui-20260520:overlay/usr/lib/carthing
git rev-parse merge-anchor-master-20260520:overlay/usr/lib/carthing
# both -> 42021b614a30c0ce61de40aa50ba2fa9f4d51a62
```

So as of 2026-05-20 the Python userspace has NOT diverged. It already contains
master's full reconnect solution (directed + bonded-only advertising +
accept-list) and the bumble `device.py` uplift — Codex does not need to re-port
those.

## Merge contract (keep it conflict-free)

| Domain | Owner | Files |
|---|---|---|
| BLE/AMS/UI Python userspace | this branch | `overlay/usr/lib/carthing/*.py` (+ vendored bumble) |
| iAP2 experiment | master (Codex) | `buildroot-external/package/carthing-iap2-mini/**` + related C/buildroot |

This branch will add a lot **after** `merge-anchor-ui-20260520`: visual design,
buttons, screen modes, menus — all inside `overlay/usr/lib/carthing/*.py`.

If Codex keeps iAP2 changes OUT of `overlay/usr/lib/carthing/*.py`, the two
trees touch disjoint file sets and merge cleanly off base `135c00b`.

## What is NOT in git yet

The fix is currently a **hot deploy** on device #2 (`172.16.42.77`) only — the
flash bundle (`carthing-custom-linux/artifacts/releases/device1-v1-working-20260518/`)
was deliberately NOT rebuilt (shared build volume rule). Rebuild happens in a
controlled moment during the unified-platform assembly, not ad hoc.
