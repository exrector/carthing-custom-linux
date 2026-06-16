# Buildroot Bring-Up

This repository does not vendor Buildroot itself.

It provides a `br2-external` tree that can be attached to a normal Buildroot checkout.

## Goal Of This Stage

Build a custom rootfs that:

- keeps the existing Superbird boot ABI
- does not include `systemd`
- does not include `bluetoothd`
- does not include `bluez5_utils`
- uses our own small Bluetooth attach path instead of target-side BlueZ tools

At this stage we are only replacing userspace. We are not replacing the bootloader, kernel, or dtb.

That is still consistent with the project goal of "custom Linux":

- the practical ownership boundary we want first is the whole rootfs/userspace
- the inherited low boot layer stays in place until userspace is stable
- kernel or dtb replacement is a later step, not a prerequisite for the current milestone

## Inputs You Need

- a Buildroot checkout
- this repository
- a GNU host compiler, e.g. Homebrew `gcc-15`
- GNU `patch`, ideally available as `gpatch` or `patch`
- Broadcom firmware blobs copied into:
  - `overlay/usr/share/carthing/firmware/brcm/BCM.hcd`
  - `overlay/usr/share/carthing/firmware/brcm/BCM20703A2.hcd`

If GNU host utilities are missing on macOS, install the project-local host tool set:

```sh
./scripts/install-buildroot-host-tools.sh
```

## Configure Buildroot

```sh
./scripts/configure-buildroot.sh /path/to/buildroot /path/to/buildroot/output-carthing
```

This applies:

- `buildroot-external/configs/carthing_superbird_rootfs_defconfig`
- `buildroot-external/board/carthing/superbird/post-build.sh`
- `buildroot-external/patches/`
- the rootfs overlay from `overlay/`

On macOS the helper scripts also:

- strip PATH entries containing spaces before invoking Buildroot
- prefer Homebrew GNU `gcc`/`g++` over Apple clang when both exist
- prepend project-local `host-tools/bin` when present
- prefer GNU `patch` from the project-local install when present
- otherwise prefer GNU `patch` from `gpatch` when it is available
- create an ASCII-only symlinked repo path for Buildroot to avoid Kconfig/package path breakage on Cyrillic directories

This avoids the host-side failures already confirmed on this machine: Xcode Beta PATH entries, Buildroot rejecting Apple clang as `gcc`, missing GNU `patch`, missing GNU `find`, and missing `flock`.

## Build The Rootfs

```sh
./scripts/build-rootfs.sh /path/to/buildroot /path/to/buildroot/output-carthing
```

Expected initial outputs:

- `output-carthing/images/rootfs.ext2`
- `output-carthing/images/rootfs.tar`

These outputs are only the custom rootfs layer. They do not replace the existing Superbird kernel, dtb, or bootloader contract.

## Verify The Target Rootfs

```sh
./scripts/verify-target-rootfs.sh /path/to/buildroot/output-carthing
```

This verifies two things before any flash attempt:

- required Car Thing runtime files are present
- forbidden target artifacts such as `systemd`, `bluetoothd`, `btattach`, and `bluez` tools are absent

## Prepare A Flash Bundle

```sh
./scripts/prepare-flash-bundle.sh \
  /path/to/buildroot/output-carthing \
  ./artifacts/flash-device1
```

This reuses the known-good Superbird flash contract from the original `flash/` directory:

- keep `bootfs.bin`
- keep `env.txt`
- keep `meta.json`
- replace only `rootfs.img`

That is the first safe migration step because it does not change the bootloader, kernel, dtb, or boot ABI.

## What This Rootfs Should Contain

- BusyBox init
- Dropbear
- `iproute2`
- `libgpiod`
- Python 3
- `carthing-bt-fwload`
- `carthing-btattach-mini`
- our init scripts under `/etc/init.d`

## What This Rootfs Should Not Contain

- `systemd`
- `bluetoothd`
- `bluez5_utils`
- any automatic BlueZ bring-up policy

## Next Validation Step

The first hardware validation target is device `№1`.

Success criteria for that step:

- boots with the existing Superbird boot ABI
- brings up `usb0`
- allows SSH
- stages BCM firmware
- resets the Bluetooth chip
- attaches the Broadcom UART controller without BlueZ tooling
- brings the app up on `hci-socket:0`
