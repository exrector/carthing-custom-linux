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

Follow-up live result:
- host-side bring-up had to be forced manually on macOS:
  - `sudo ifconfig en14 inet 172.16.42.1 netmask 255.255.255.0 up`
  - `sudo route -n add -net 172.16.42.0/24 -interface en14`
- waiting for `en14` or `utun*` routing to self-heal was the wrong move
- after host-side bring-up:
  - `ssh`, `http`, and `telnet` came back
  - rebuilt `carthing-bt-fwload` was uploaded to `/run`
  - external `BCM20703A1-0a5c-6410.hcd` was uploaded to `/run`

What the live run proved:
- the rebuilt binary is valid on target
- firmware upload now gets through the full HCD stream again
- the old double-launch bug was real:
  - the HCD blob already contains `0xFC4E`
  - sending an extra manual `Launch RAM` after the stream was wrong
- after removing the duplicate `Launch RAM`, the stop moved to a narrower point:
  - a single successful `0xFC4E` launch sequence
  - then a post-launch `HCI_RESET` times out

Tail of the decisive live sequence:

```text
=> 01 4e fc 04 ff ff ff ff
<= 04 0e 04 01 4e fc 00
=> 01 03 0c 00
timed out waiting for UART data
short HCI event
post-launch reset failed at 115200, retrying at 3000000 baud
=> 01 03 0c 00
timed out waiting for UART data
short HCI event
```

Further source-side narrowing that was added after this run:
- `carthing-bt-fwload` now has explicit runtime controls for the two disputed
  areas, so the next experiments do not require new recompiles each time:
  - `--post-launch-delay-us <usec>`
  - `--post-launch-reset both|download|controller|none`
  - `--hw-flow-control`
- `S20-bt-init` already supports arbitrary `CARTHING_BT_FWLOAD_ARGS`, so these
  experiments can be driven through normal boot once the desired defaults are
  chosen.

What the next live experiments showed:
- enabling `--hw-flow-control` made things worse on this hardware revision:
  the loader then failed earlier at `DOWNLOAD_MINIDRIVER` instead of at the
  post-launch reset
- keeping hardware flow control off and using baseline `--post-launch-reset both`
  reproduced the same narrow stop as above
- using `--post-launch-reset none` on a clean run reached `Launch RAM` without
  printing a new loader-side error after the `0xFC4E` completion
- after several back-to-back manual runs, the UART/chip state became dirty
  enough that later direct retries could fail even on the very first
  `HCI_RESET`; that state should not be mistaken for a regression of the
  `skip reset` experiment itself

Current next step:
- keep the host-side bring-up rule fixed in docs and scripts
- keep default `fwload` behavior conservative in the image for now
- on the next clean device cycle, test the standard boot path with:

```sh
CARTHING_BT_FIRMWARE=/run/BCM20703A1-0a5c-6410.hcd \
CARTHING_BT_FWLOAD_ARGS="--post-launch-reset none" \
/etc/init.d/S20-bt-init
```

- if that path consistently succeeds, promote the chosen firmware blob and
  `CARTHING_BT_FWLOAD_ARGS` into the normal device configuration

New live frontier after the `skip reset` experiments:
- a clean `fwload` run with:

```sh
/run/carthing-bt-fwload \
  --device /dev/ttyS1 \
  --firmware /run/BCM20703A1-0a5c-6410.hcd \
  --download-baud 115200 \
  --baudrate 3000000 \
  --post-launch-reset none
```

  now exits `0` on target
- after that, a direct Bumble probe can already open the serial transport:
  - `open_transport_or_link('serial:/dev/ttyS1,3000000')` succeeds
  - `open_transport_or_link('serial:/dev/ttyS1,3000000,rtscts')` also succeeds
- but `device.power_on()` still times out on the very first HCI command:
  - first at `host.reset()` (`HCI_Reset_Command`)
  - and even with a temporary monkey-patch that skips `host.reset()`, the next
    command (`HCI_Read_BD_ADDR_Command`) still times out

What this means:
- the frontier is no longer "can the loader upload firmware?"
- and no longer "can Bumble open the serial transport?"
- the current narrow stop is:
  - post-upload controller state does not answer regular HCI commands yet

Negative results also confirmed:
- longer quiet time after `Launch RAM` did not fix `device.power_on()`
- enabling `rtscts` only on the Bumble transport side did not fix
  `device.power_on()`

Most likely next direction:
- compare our post-launch behavior against the exact controller state expected
  by the original Broadcom init path
- focus on post-upload controller readiness / first-HCI-command semantics, not
  on host-side USB, toolchain, or simple serial-open logic
