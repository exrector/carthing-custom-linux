# macOS VPN / NCM Route Runbook

Date: 2026-06-19

## Rule

On this Mac, failed SSH to Car Thing over USB/NCM is not enough evidence that
the device is gone.

When VPN/Tailscale is enabled, macOS can move `172.16.42.0/24` routing to
`utun*`, `tun*`, `en0`, or another wrong interface. The `enXX` NCM interface can
also disappear and come back under a new BSD name after reconnects.

Fix host routing first.

## One-line Recovery

If the current NCM BSD interface is known:

```sh
./scripts/bring-up-device1-normal-boot-macos.sh --bsd en14
```

If the interface name may have changed:

```sh
./scripts/bring-up-device1-normal-boot-macos.sh
```

The script discovers `Exrector QN19`, assigns `172.16.42.1/24`, clears stale
ARP, and pins `172.16.42.0/24` back to the USB/NCM interface.

## Diagnostic Order

1. Check normal-boot/NCM state:

```sh
./scripts/check-device1-normal-boot-macos.sh
```

2. If `Exrector QN19` exists, run the one-line recovery above immediately.

3. Only after that, test SSH:

```sh
ssh -i ~/.ssh/id_ed25519 root@172.16.42.77
```

## Stop Rule For Agents

Do not repeat SSH loops, ping loops, or interface guessing while VPN/Tailscale is
active. If `route get 172.16.42.77` points to `utun*`, `tun*`, `en0`, or any
non-NCM interface, run `bring-up-device1-normal-boot-macos.sh` first.

Do not claim that the device is absent until the project check script fails to
find `Exrector QN19` / NCM BSD interface after the host route has been repaired.
