## Bluetooth Fwload Toolchain Checkpoint (2026-05-17)

Goal of this checkpoint:
- confirm that `/Volumes/carthing-buildroot-case/output-55cad92-clean` contains a full usable target toolchain
- rebuild `carthing-bt-fwload` with the `565eea9` Launch RAM fix
- preserve the rebuilt binary and the better external Broadcom firmware blob for the next live run

What was confirmed:
- mounted toolchain is full, not stage1-only
- compiler used:
  - `/Volumes/carthing-buildroot-case/output-55cad92-clean/host/bin/aarch64-linux-gcc`
- sysroot used by that compiler:
  - `/Volumes/carthing-buildroot-case/output-55cad92-clean/host/aarch64-buildroot-linux-gnu/sysroot`
- `errno.h` exists there:
  - `/Volumes/carthing-buildroot-case/output-55cad92-clean/host/aarch64-buildroot-linux-gnu/sysroot/usr/include/errno.h`

Manual rebuild that succeeded:

```sh
rm -rf /private/tmp/carthing-bt-fwload-build
mkdir -p /private/tmp/carthing-bt-fwload-build
cp buildroot-external/package/carthing-bt-fwload/src/* /private/tmp/carthing-bt-fwload-build/
make -C /private/tmp/carthing-bt-fwload-build \
  CC=/Volumes/carthing-buildroot-case/output-55cad92-clean/host/bin/aarch64-linux-gcc \
  clean all
```

Result:
- rebuilt binary:
  - `/private/tmp/carthing-bt-fwload-build/carthing-bt-fwload`
- `file`:
  - `ELF 64-bit LSB pie executable, ARM aarch64, dynamically linked, interpreter /lib/ld-linux-aarch64.so.1`

Preserved local artifacts:
- directory:
  - `artifacts/bluetooth-20260517-fwload-test`
- rebuilt binary:
  - `artifacts/bluetooth-20260517-fwload-test/carthing-bt-fwload`
- external firmware blob:
  - `artifacts/bluetooth-20260517-fwload-test/BCM20703A1-0a5c-6410.hcd`

Checksums:
- `carthing-bt-fwload`
  - `db67d3bbd5cde1053b0d3f33a68d6f0e010a41c735f90d118e6deb072243e6ac`
- `BCM20703A1-0a5c-6410.hcd`
  - `e526fd12cd3529b7e01c0076f69189b7e2d9a0124a91e7583c6ddefecdbe0599`

Next live run, when USB/NCM is actually up:

```sh
ssh -i ~/.ssh/id_rsa root@172.16.42.77 'cat > /run/carthing-bt-fwload' \
  < artifacts/bluetooth-20260517-fwload-test/carthing-bt-fwload

ssh -i ~/.ssh/id_rsa root@172.16.42.77 'cat > /run/BCM20703A1-0a5c-6410.hcd' \
  < artifacts/bluetooth-20260517-fwload-test/BCM20703A1-0a5c-6410.hcd

ssh -i ~/.ssh/id_rsa root@172.16.42.77 '
  chmod 0755 /run/carthing-bt-fwload &&
  echo 493 > /sys/class/gpio/export 2>/dev/null || true &&
  echo out > /sys/class/gpio/gpio493/direction &&
  echo 0 > /sys/class/gpio/gpio493/value &&
  usleep 100000 &&
  echo 1 > /sys/class/gpio/gpio493/value &&
  usleep 200000 &&
  /run/carthing-bt-fwload \
    --device /dev/ttyS1 \
    --firmware /run/BCM20703A1-0a5c-6410.hcd \
    --download-baud 115200 \
    --baudrate 3000000 \
    --debug
'
```

Live blocker at the end of this checkpoint:
- device was reattached on USB, `NCM Gadget` was visible in `ioreg`
- but host-side `en14` stayed `inactive`
- route to `172.16.42.77` stayed pinned to `utun13`
- therefore the rebuilt binary was not uploaded to the device in this session
