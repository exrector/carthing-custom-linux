# Local Access Profile

This project intentionally keeps local ingress simple.

The target is a home-lab style device on a private USB link, not an Internet-facing system.

## Default Access

Device `№1` on normal boot is expected to expose:

- `ssh` on `172.16.42.77:22`
- BusyBox `httpd` on `172.16.42.77:8080`
- BusyBox `telnetd` on `172.16.42.77:2323`
- reverse control agent polling the host at `172.16.42.1:8099`

The default `httpd` listener is only a simple local file server. A `404` on `/`
still proves that the listener is alive.

Default root password:

- `carthing`

Default SSH keys baked into the image:

- `overlay/root/.ssh/authorized_keys`

Current recovery key set includes:

- `id_ed25519.pub`
- `id_rsa.pub`

## Host Bring-Up

Normal rule on this Mac:

- keep `com.exrector.carthing.usb-route-watch` installed as a root LaunchDaemon
- it runs every 10 seconds, detects `Exrector QN19` in IORegistry, assigns
  `172.16.42.1/24` to the current USB BSD interface, and pins
  `172.16.42.0/24` to that interface
- it does not disable, stop, or reconfigure VPN; it only installs the more
  specific Car Thing USB route

Install or refresh it from the repo root:

```sh
scripts/install-carthing-usb-route-watch-macos.sh
```

Uninstall:

```sh
scripts/install-carthing-usb-route-watch-macos.sh --uninstall
```

Manual fallback:

- if device `№1` was replugged in normal boot, do not wait for `en14` or the route to recover by themselves
- force host-side bring-up first
- only after that decide whether the target itself is still broken

Run:

```sh
./scripts/bring-up-device1-normal-boot-macos.sh
```

That should assign:

- host IP `172.16.42.1/24`
- route `172.16.42.0/24` pinned to the NCM interface

Typical bad host-side state that still requires this script:

- `NCM Gadget` exists in `ioreg`
- `en14` exists but shows `status: inactive`
- route to `172.16.42.77` points to `utun*`

With the LaunchDaemon installed, these states should self-heal. If they do not,
run the manual fallback once and inspect:

```sh
launchctl print system/com.exrector.carthing.usb-route-watch
tail -50 /var/log/carthing-usb-route-watch.log
tail -50 /var/log/carthing-usb-route-watch.err
```

## Recommended Access Order

1. `ssh -i ~/.ssh/id_rsa root@172.16.42.77`
2. `ssh root@172.16.42.77` and enter password `carthing`
3. `telnet 172.16.42.77 2323`
4. `http://172.16.42.77:8080/`
5. reverse agent as fallback

Or check the whole local-open profile in one shot:

```sh
./scripts/check-device1-local-open-access-macos.sh
```

## Reverse-Agent Hygiene

The reverse control queue is file-backed under:

- `/tmp/carthing-control-server/pending/device1/`
- `/tmp/carthing-control-server/running/device1/`
- `/tmp/carthing-control-server/completed/device1/`

If old `running/` or `pending/` entries accumulate, archive and clear them with:

```sh
./scripts/reset-reverse-control-state.sh device1
```

Archived entries are moved under:

```text
/tmp/carthing-control-server/archive/<timestamp>/device1/
```

## Why This Is Open

This profile is intentionally local-open:

- no attempt is made to harden the device for hostile networks
- simple password access is acceptable
- extra local listeners are acceptable
- ease of bring-up is preferred over protection
