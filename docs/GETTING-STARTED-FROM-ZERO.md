# Getting started from zero

This is the canonical start-to-device runbook for this repository.

Audience:

- a developer who has a Spotify Car Thing / Superbird device;
- a macOS or Linux host;
- this repository plus the binary release artifacts described below.

The goal is not to install a Linux distribution on the host. The host is only a
workstation used to bake images and talk to the Car Thing boot ROM/U-Boot over
USB.

## Key terms

### superbird-tool

`superbird-tool` is the public Car Thing / Superbird USB bootloader toolkit. It
uses `pyamlboot` to talk to the Amlogic boot ROM/U-Boot path and can identify
boot modes, enter burn mode, dump partitions, restore partitions, and send
U-Boot commands.

Use it to understand and verify the upstream Superbird flashing model. This
repository vendors the necessary manual/flasher pieces in `image/manual/` and
wraps the actual product flashing in `tools/flash.py`.

Preferred upstream for new installs:

- `https://github.com/ThingLabsOSS/superbird-tool`

Original upstream:

- `https://github.com/bishopdynamics/superbird-tool`

### e2tools

`e2tools` is a host-side toolkit for editing ext2/ext3/ext4 filesystem images
without mounting them. In this project it lets macOS modify `rootfs.img`
directly:

- `e2cp` copies files into or out of the ext4 image;
- `e2mkdir` creates directories inside the image;
- `e2rm` removes files inside the image;
- `e2ls` lists files inside the image.

Why this matters: `image/rootfs.img` is an ext4 filesystem image for the
device's p2 rootfs. macOS cannot mount Linux ext4 natively in the normal safe
way, so the bake process edits it as an image file.

`e2fsck` is separate from `e2tools`. We run it after `e2cp` writes because
`e2cp` can leave ext4 block group checksums in a state the kernel repairs at
boot. Running `e2fsck -f -y rootfs.img` makes boot fast and predictable.

### GE2D

GE2D is Amlogic's hardware 2D graphics engine. On this Car Thing SoC it can
accelerate operations like fills, blits, scaling, and color conversion.

In this project:

- the current `image/bootfs.bin` contains a kernel with GE2D enabled;
- the live QN19 device exposes `/dev/ge2d`;
- `overlay/usr/lib/carthing/ge2d.py` and `ge2d_test.py` are the current Python
  userspace probe/wrapper;
- full GUI integration is still a follow-up task, not a reason to redesign the
  storage architecture.

### P1/P2 product architecture

Current product baseline uses two Linux-visible partitions:

| Partition | Filesystem | Role |
|-----------|------------|------|
| p1 `/dev/mmcblk0p1` | FAT32 | U-Boot-readable boot files plus small runtime state |
| p2 `/dev/mmcblk0p2` | ext4 | readonly Buildroot rootfs |

Do not introduce p3 unless the architecture is explicitly reopened. Prior p3
work is research/rejected for the current product baseline.

## Required artifacts

The git repository alone is not enough if large binaries are excluded by
`.gitignore`. A reproducible public release must provide these artifacts either
as GitHub Release assets or another explicit download bundle:

```text
image/bootfs.bin
image/rootfs.img
image/env.txt
image/bootlogos.bin
image/boot/
image/manual/
source/base-bundle/rootfs.img
source/base-bundle/bootfs.bin
source/base-bundle/env.txt
source/base-bundle/meta.json
```

The tracked checksum file is:

```text
image/SHA256SUMS
```

For a public GitHub release, publish a `carthing-release-bundle-YYYYMMDD.tar.zst`
or similar asset containing the git checkout plus the binary artifact paths
above. Without those binaries a user can read and modify source, but cannot
flash the same product image.

## Host setup on macOS

Install command-line tools:

```sh
xcode-select --install
```

Install Homebrew packages:

```sh
brew install libusb e2tools e2fsprogs
```

Create a Python virtualenv:

```sh
cd /path/to/carthing-release-integration
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install pyusb 'pyamlboot @ git+https://github.com/superna9999/pyamlboot'
```

Optional upstream probe tool:

```sh
cd /tmp
git clone https://github.com/ThingLabsOSS/superbird-tool
cd superbird-tool
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install pyusb 'pyamlboot @ git+https://github.com/superna9999/pyamlboot'
python3 superbird_tool.py --find_device
```

On Apple Silicon, if USB access is flaky, install PyUSB from git:

```sh
python3 -m pip install 'pyusb @ git+https://github.com/pyusb/pyusb'
```

## Host setup on Linux

Install packages. Names vary by distro; this is the Debian/Ubuntu shape:

```sh
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip libusb-1.0-0 e2tools e2fsprogs
```

Create a Python virtualenv:

```sh
cd /path/to/carthing-release-integration
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install pyusb 'pyamlboot @ git+https://github.com/superna9999/pyamlboot'
```

If USB access is denied, add a udev rule for Amlogic burn mode:

```sh
sudo sh -c 'printf "%s\n" '\''SUBSYSTEM=="usb", ATTRS{idVendor}=="1b8e", ATTRS{idProduct}=="c003", MODE="0666"'\'' > /etc/udev/rules.d/60-superbird.rules'
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Get the project and artifacts

```sh
git clone https://github.com/YOUR_ORG/carthing-release-integration
cd carthing-release-integration
```

If artifacts are distributed separately:

```sh
tar --extract --file carthing-release-bundle-YYYYMMDD.tar.zst
```

Then verify:

```sh
test -f image/bootfs.bin
test -f image/rootfs.img
test -f image/env.txt
test -f image/bootlogos.bin
test -d image/boot
test -d image/manual
(cd image && shasum -a 256 -c SHA256SUMS)
```

## Check the device mode

There are three states that matter for this project:

| State | USB VID:PID | Meaning |
|-------|-------------|---------|
| Amlogic USB / burn path | `1b8e:c003` | device can receive U-Boot/flashing commands |
| Custom Linux / USB NCM | `0525:a4a1` | product image is booted and exposes USB networking |
| Not found | none | cable, power, buttons, or host USB issue |

From this repository:

```sh
tools/check-device.sh
```

With upstream `superbird-tool`:

```sh
python3 superbird_tool.py --find_device
```

To enter the Amlogic USB path manually:

1. unplug USB;
2. hold preset buttons `1` and `4`;
3. plug USB while holding them;
4. wait about two seconds;
5. release buttons;
6. run `tools/check-device.sh`.

Expected result for flashing:

```text
MASKROM/BURN (1b8e:c003)
```

## Flash the product image

This repository's product flashing entrypoint is:

```sh
python3 tools/flash.py
```

It writes:

| Artifact | Target |
|----------|--------|
| `image/bootfs.bin` | sector `0` |
| `image/rootfs.img` | sector `352256` |
| `image/env.txt` | U-Boot env via `env import` + `saveenv` |
| `image/bootlogos.bin` | logo partition sector `319488` |

Do not use random `superbird-tool --restore_device` commands for this product
unless you have matched the same geometry and artifacts. `tools/flash.py` is the
documented product path.

After flashing, unplug and replug the device without holding buttons.

## Bring up USB networking

When the product image boots, it exposes USB NCM networking:

| Side | Address |
|------|---------|
| Car Thing | `172.16.42.77` |
| Host | `172.16.42.1` |

On macOS, first discover/check the NCM interface:

```sh
scripts/check-device1-normal-boot-macos.sh
```

Then bring the interface up. If the checker reports `en18`, use:

```sh
scripts/bring-up-device1-normal-boot-macos.sh --bsd en18
```

If unsure, run the script without `--bsd` first and read its output:

```sh
scripts/bring-up-device1-normal-boot-macos.sh
```

macOS may route `172.16.42.77` through a VPN `utun*` interface. The bring-up
script fixes that by assigning `172.16.42.1/24` to the NCM interface and pinning
the route back to that interface.

On the development Mac, install the persistent route watchdog once:

```sh
scripts/install-carthing-usb-route-watch-macos.sh
```

It runs as `com.exrector.carthing.usb-route-watch` and keeps the USB route
pinned without disabling VPN. The manual bring-up script remains the immediate
fallback.

## SSH into the device

After USB networking is up:

```sh
ssh-keygen -R 172.16.42.77
ssh root@172.16.42.77
```

Default credentials:

| Field | Value |
|-------|-------|
| user | `root` |
| password | `carthing` |
| address | `172.16.42.77` |

Read-only sanity commands:

```sh
hostname
uname -a
cat /etc/os-release
mount
ps w
tail -80 /run/carthing/carthing-remote.log
```

Expected system identity:

- Buildroot userspace;
- BusyBox init;
- rootfs mounted from `/dev/mmcblk0p2`;
- runtime state mounted at `/run/carthing-state`;
- `carthing_runtime.py` running;
- no `systemd`;
- no BlueZ userland tooling.

## Rebuild rootfs after source changes

Normal development changes `overlay/`, not the bootloader or kernel.

Run local gates:

```sh
scripts/check-bake-readiness.sh
```

If Python runtime files changed, update `EXPECTED_RUNTIME_TREE_SHA1` in both:

```text
tools/bake-rootfs.py
scripts/bake-unified-runtime-rootfs.py
```

The readiness script prints the expected SHA when it is out of date.

Bake:

```sh
python3 tools/bake-rootfs.py
```

The script:

- copies `source/base-bundle/rootfs.img`;
- overlays `overlay/`;
- removes retired runtime files;
- copies native runtime libraries;
- runs `e2fsck`;
- verifies the result.

Move the new rootfs into the flash image:

```sh
BUNDLE="$(ls -d flash-bake-unified-stable-* | sort | tail -1)"
cp "$BUNDLE/rootfs.img" image/rootfs.img
shasum -a 256 image/bootfs.bin image/rootfs.img image/env.txt image/bootlogos.bin | \
  sed 's|image/||g' > image/SHA256SUMS
(cd image && shasum -a 256 -c SHA256SUMS)
```

Only then decide whether to flash.

## Hot deploy for development

For fast iteration on an already booted device:

```sh
tools/deploy overlay/usr/lib/carthing/carthing_runtime.py --restart
```

This temporarily remounts rootfs writable, copies the file, and can restart the
runtime. Hot deploy is not a release state. Any useful hot-deployed change must
be baked into `image/rootfs.img`.

## What a GitHub user can reproduce today

With this repository plus the binary artifact bundle, a user can:

1. install host dependencies;
2. detect device boot mode;
3. flash the product image;
4. boot into Buildroot;
5. bring up USB NCM;
6. SSH into the device;
7. modify `overlay/`;
8. bake a new `rootfs.img`;
9. flash again.

What is not yet fully reproducible from source alone:

- the GE2D kernel rebuild provenance is incomplete until exact kernel config,
  command, toolchain, and artifact hashes are captured next to the kernel
  artifact;
- the binary `source/base-bundle/` inputs must be published as release assets
  if they stay gitignored;
- a fully source-built Buildroot+kernel pipeline is separate work from the
  current fast product bake pipeline.

## Safety rules

- Do not convert p1 from FAT to ext4.
- Do not introduce p3 for the product baseline without reopening architecture.
- Do not run Linux `poweroff`/`halt` as a product action.
- Do not reboot to test cosmetic changes while p1/vfat has a dirty warning.
- Do not treat archive folders as active source.
- Do not use BlueZ/`bluetoothd`/`bluetoothctl` as the product Bluetooth path.
