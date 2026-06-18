# Resource Policy Proof — QN19 — 2026-06-17

Scope: first optimization wave after `carthing-next-wave-backlog-2026-06-17`.

## Implemented

- `resource_policy.py` owns mode-aware CPU governor selection and resource
  diagnostics.
- Runtime publishes `bt.resource_policy` with CPU governor/frequency data and
  zram state.
- Play Now requests `schedutil`.
- Коммутатор can request `performance` when the kernel exposes it.
- `S11-zram` enables optional 128 MB `/dev/zram0` swap.
- Safe unplug now enters central Play Now teardown before finalizer launch.
- Bake guards now agree on runtime tree sha1:
  `e3e456c79ad0712a3c54549b71acd97dc4e7b6b1`.
- Runtime publishes TMD2772 ALS/proximity diagnostics, but does not yet change
  brightness automatically. Follow-up 2026-06-18 enabled the DTB proximity
  engine (`enable-proxy=true`); userspace wake/dim policy is still pending.

## Local Gates

- `python3 -m py_compile` passed for changed Python files and bake scripts.
- `scripts/check-operation-mode-contract.py` passed.
- `scripts/check-bake-readiness.sh` passed.
- `sh -n overlay/etc/init.d/S11-zram` passed.
- `git diff --check` passed before live proof.

## Live QN19 Proof

After deploy and reboot:

```text
swaps:
/dev/zram0 partition 131068 0 -1

governor:
/sys/devices/system/cpu/cpufreq/policy0 schedutil
available: interactive performance schedutil

runtime:
operation_mode=playnow
mode_resources.speaker_standby=false
mode_resources.receiver_stream=false
mode_resources.route_patchbay=false
mode_resources.speaker_scan=false
resource_policy.zram.active=true
resource_policy.zram.disksize_bytes=134217728
resource_policy.zram.swap_size_kb=131068
resource_policy.sensors.als_prox_present=true
resource_policy.sensors.tmd2772.illuminance_input=1
resource_policy.sensors.tmd2772.proximity_raw=0
Traceback count in carthing-remote.log: 0
```

Boot profile tail after reboot:

```text
gui.ready proc_uptime_s=11.530 runtime_s=0.844
ble.init_start proc_uptime_s=11.530 runtime_s=0.844
ble.init_ready proc_uptime_s=14.690 runtime_s=4.005 attempt=1
mode.applied proc_uptime_s=14.760 runtime_s=4.078 mode=playnow reason=boot
runtime.ready proc_uptime_s=15.000 runtime_s=4.315
```

## Bake

Local bake completed:

```text
bundle: flash-bake-unified-stable-20260617-235414
bootfs.bin sha256: 6e99a75c57e38acab5be5b818f559132a4b7a167e7ccfa80e4e3ce1aedd7df3e
rootfs.img sha256: 362c4290d37cb7a5b1a93c2def85d9c0bd4d504487f7cfaa943bc327535ec17e
env.txt sha256: 622490729632aeb3eff2fffe89da6fc13b800f51eda77791e27d89225363fb69
meta.json sha256: 121f3ea3327d5a6ae2575d54c5d8e2cf1cd3a1b1d48a3c5760fdff3017b1b56c
```

This bundle has not been flashed in full.

## Remaining

- A1 is now proven by the 2026-06-18 route-load proof:
  `docs/ROUTE-LOAD-PROOF-2026-06-18.md` shows Play Now `schedutil`,
  Коммутатор `performance`, then Play Now `schedutil`.
- A3 is still `PARTIAL`: safe-unplug code is deployed, but actual physical USB
  removal proof should be done only with the owner present.
- A4 is `PARTIAL`: sensor readings are published; product auto-brightness or
  wake/dim thresholds are not enabled yet.
- A5 is `DONE`: final artifact
  `artifacts/route-load-20260618-013706/proof.json`.
