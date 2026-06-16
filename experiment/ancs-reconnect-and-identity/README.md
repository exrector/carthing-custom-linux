# Надёжный reconnect/visibility + factory-identity (результат)

**Что это:** два связанных результата, которые сделали свою систему не просто рабочей, а стабильной в быту — чем редко может похвастаться кастом на этом железе:

1. **Factory-identity** — устройство само определяет имя из **efuse** (`/sys/class/efuse/usid`) в рантайме: `8559RP88Q917` → **«Car Thing (SN: Q917)»**. Не зависит от MAC, переживает повреждённый `state.json`. Видимое имя и BT-идентичность стабильны на каждой загрузке.
2. **Reconnect/visibility stabilization** — надёжное переподключение и видимость: HID-пара переживает холодную загрузку, видимость корректно проходит фазы pairing/transfer, реконнект после A2DP стабилизирован, reliability-pass закрыл «отваливания».

Готовый результат: документированные фиксы + где это в рантайме.

## Что доказано

- Имя из efuse применяется на каждой загрузке; не теряется при пустом/битом state.
- HID-pair сохраняется после cold boot (`checkpoint-2026-05-18-hid-pair-cold-boot`).
- Видимость и реконнект стабильны после A2DP (`runtime-visibility-stabilization-2026-05-23`).
- Reliability-pass устранил нестабильность линка (`device1-reliability-pass-2026-05-18`).

## Документы

| Док | Что |
|---|---|
| `factory-identity-2026-05-22.md` | имя из efuse usid, переживает битый state |
| `runtime-visibility-stabilization-2026-05-23.md` | стабилизация видимости/реконнекта |
| `device1-reliability-pass-2026-05-18.md` | проход по надёжности линка |
| `checkpoint-2026-05-18-hid-pair-cold-boot.md` | HID-пара после холодной загрузки |

## Где в коде
Имя-из-efuse и реконнект-логика живут в рантайме (`identity_service.py`, `hardware_inventory.py`, `ble_transport.py`, `accessory_orchestrator.py`) — см. основной образ и `../bluetooth-router/`.
