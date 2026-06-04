# Bumble upgrade to v0.0.229

Date: 2026-06-05

The 2021-2022 vendored Bumble snapshot was replaced with official upstream
`v0.0.229`, commit `72d821b1f64cd8a4626e3175430dac0d7aafd6c0`.

Why the replacement was required:

- the old CTKD implementation failed the official h6/h7 test vectors;
- its CT2 path used an invalid 160-bit salt and raised an AES key-size error;
- newer upstream releases contain CTKD, link-key persistence, identity, and RPA
  fixes that were absent from the old snapshot.

Local compatibility patches kept on top of upstream:

- `transport/hci_socket.py` supplies Linux ABI constants because Car Thing's
  minimal Python build omits `socket.AF_BLUETOOTH` and `socket.BTPROTO_HCI`;
- `device.py` retains the advertising filter-policy argument required by the
  bonded-only reconnect policy.

Hardware verification on Car Thing:

- installed Bumble reports `0.0.229`;
- official CTKD h6 and h7 vectors pass;
- Classic controller initialization succeeds with Classic discovery disabled;
- the existing BLE iPhone bond reconnects automatically;
- AMS, ANCS, and CTS operate successfully.

The existing bond is BLE-only and intentionally remains without a Classic
`link_key`. A clean iPhone pairing is still required to validate the upgraded
single-pair CTKD plus A2DP path.

Build invariant:

- `scripts/bake-unified-runtime-rootfs.py` removes the old Bumble directory and
  copies the complete `overlay/usr/lib/carthing/vendor` tree into every baked
  rootfs;
- `scripts/check-bumble-vendor.py` verifies the pinned version, CTKD vectors,
  and runtime imports.
