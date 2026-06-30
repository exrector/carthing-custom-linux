# Bluetooth maintenance

Day-to-day device updates use the existing CTSP Bluetooth L2CAP CoC session.
USB is required once to provision the shared key and remains the recovery path
for bootloader, kernel, and rootfs failures.

## One-time provisioning

```sh
./scripts/provision-bluetooth-maintenance.sh
```

The script copies the same random 32-byte key to:

- macOS: `~/Library/Application Support/CarThingBTLink/maintenance.key`
- Car Thing: `/var/lib/carthing/maintenance.key`

Maintenance messages are authenticated with HMAC-SHA256 and a random
per-runtime session nonce published in the signed CTSP bootstrap contract, so
captured commands cannot be replayed after a restart. The device accepts uploads
only below `/usr/lib/carthing`, up to 8 MiB, and verifies the declared SHA-256
before atomically replacing a file.

## Daily use

```sh
carthingctl status
carthingctl logs 100
carthingctl push overlay/usr/lib/carthing/screens.py \
  /usr/lib/carthing/screens.py
carthingctl restart
```

For one or more overlay files:

```sh
tools/deploy-bt \
  usr/lib/carthing/screens.py \
  usr/lib/carthing/gui_controller.py \
  --restart
```

`tools/deploy-bt` does not open SSH and does not use the USB network. It talks
to the running `CarThingBTLink.app` on localhost; the app serializes each file
into acknowledged 24 KiB blocks over the existing Bluetooth CTSP channel.
