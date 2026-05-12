# Session Freeze 2026-05-12

This note captures the current working state so the project can be resumed after a reboot, a new session, or a long pause.

## Project Goal Reminder

- the project goal is a custom Linux system on the device
- at the current stage that means our own Buildroot rootfs and userspace
- the inherited Superbird bootloader, kernel, dtb, and boot ABI are intentionally still reused
- kernel or dtb replacement is a later decision, not the current migration step

## Live State Verified On Device `№1`

After flashing the cleanup bundle and booting `normal boot`, the following were manually verified live:

- `NCM Gadget` appears on macOS
- host-side access works after pinning `172.16.42.0/24` back to `en14`
- `172.16.42.77` replies to ICMP
- `22/tcp` is open and `ssh` key login works
- `ssh` password login works with root password `carthing`
- `8080/tcp` is open and BusyBox `httpd` responds
- `2323/tcp` is open and BusyBox `telnetd` gives a shell prompt
- the reverse control agent completes commands successfully

One practical host-side caveat remains:

- on reconnect, macOS may route `172.16.42.0/24` to `utun4` instead of `en14`
- if that happens, the device is still fine; the host needs manual bring-up again
- the manual recovery is:

```sh
sudo ifconfig en14 inet 172.16.42.1 netmask 255.255.255.0 up
sudo route -n delete -net 172.16.42.0/24 || true
sudo route -n add -net 172.16.42.0/24 -interface en14
```

## Verified Access Commands

```sh
ssh -i ~/.ssh/id_rsa root@172.16.42.77
sshpass -p carthing ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no root@172.16.42.77
telnet 172.16.42.77 2323
open http://172.16.42.77:8080/
```

## Flashed Working Rootfs

The bundle that was flashed and then verified live is:

- `artifacts/flash-device1-next/rootfs.img`
- SHA-256: `46f6531bfdda96d0eaa036706a257ff85fc67d2a9b1512e8defcee4da14b67c7`

The older bundle snapshot still preserved for comparison is:

- `artifacts/flash-device1/rootfs.img`
- SHA-256: `e52e92c693fc40a14043413c978990487fcc8b9cd8c4d65dec37bc06b15c2b14`

## Preserved Local Artifacts

The main preservation root is:

- `artifacts/preservation-20260512/`

It contains:

- `carthing-buildroot-case-20260512.sparseimage`
  - clone of the mounted `/Volumes/carthing-buildroot-case` backing image
- `carthing-custom-linux-master.bundle`
  - full git bundle for the repository history
- `bundles/flash-device1/`
  - preserved older live bundle snapshot
- `bundles/flash-device1-next/`
  - preserved cleanup bundle that was flashed and verified
- `carthing-control-server/`
  - reverse-agent queue state and logs
- `private-tmp/`
  - copied recovery trees, diagnostic images, and flash logs from `/private/tmp`
- `recovery-20260512/`
  - earlier recovery snapshot gathered before the final cleanup flash

## Important Caveat About `private-tmp`

When copying `private-tmp`, two temporary files under:

- `carthing-rootfs-stage-rootowned/etc/dropbear/`

were unreadable:

- `dropbear_ed25519_host_key`
- `dropbear_rsa_host_key`

This is not a new regression. Those were temporary staging keys and do not block recovery because the final verified access path already uses the cleaned flashed image and runtime-generated working keys.

## Working Runtime Shape On Device

The runtime state on the device is now intentionally minimal:

- `dropbear`
- BusyBox `httpd`
- BusyBox `telnetd`
- `reverse-agent`

The old bring-up noise files like:

- `reverse-agent.probe.trace`
- `reverse-agent.version`
- `s09-late-report`
- `reverse-agent-command.*`

were confirmed absent from `/run/carthing` after the final boot.

## Key Commits To Start From

- `95fe9d0` `Checkpoint clean access docs and reverse-control hygiene`
- `3bf8c79` `Checkpoint simplify local-open service path`
- `6a31bd2` `Checkpoint clean fallback image install path`
- `d8b690c` `Checkpoint clarify staged custom Linux goal`

## Next Likely Direction

The ingress problem is solved. The next stage is no longer about access. The next stage is:

1. keep this local-open profile as the recovery baseline
2. use it to work on Bluetooth and the actual runtime
3. only revisit kernel or dtb replacement if userspace ownership stops being enough
