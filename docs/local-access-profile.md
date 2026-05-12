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

On this Mac host, bring the USB link up with:

```sh
./scripts/bring-up-device1-normal-boot-macos.sh
```

That should assign:

- host IP `172.16.42.1/24`
- route `172.16.42.0/24` pinned to the NCM interface

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
