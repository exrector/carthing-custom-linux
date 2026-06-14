# Слои: от кремния до Control Center

Как РЕАЛЬНО работает Bluetooth-стек Car Thing. Дополняет SYSTEM-STATE-2026-06-10.md.

## Слоёный пирог

```
iPhone / Fosi                    ← их стеки на той стороне эфира
────────── эфир 2.4 ГГц ──────────
BCM4345C0 (combo-чип)            ← Baseband/LL/LMP/AES в кремнии; ОДИН радиотракт
  ↕ UART /dev/ttyS1, H4, 3 Mbps  ← потолок пропускной; firmware BCM4345C0.hcd
ядро Linux: hci0 (N_HCI)         ← ТОЛЬКО транспорт: HCI_CHANNEL_USER, стек ядра в стороне
Bumble (Python, vendored 0.0.229)← ВЕСЬ Bluetooth-host: HCI/L2CAP/SMP/SDP/GATT/AVDTP/AVRCP
наш слой                         ← orchestrator (персона/фазы/CTKD-фабрика),
                                   a2dp_bridge (труба/per-peer AVRCP/SDS),
                                   carthing_runtime (дирижёр/тумблер), transfer_control
```

## Ключевые следствия архитектуры

1. **Один радиотракт**: page/inquiry/advertising/RTP конкурируют за слоты.
   Отсюда: ретраи classic-дозвона (3/8/15 c), гейт «колонка ДО iPhone»,
   backoff пейджей (12→300 c), возрождение рекламы после инквайри (инвариант 4).
2. **HCI_CHANNEL_USER** = монопольный сырой доступ. Чип занят одним процессом
   (ошибка «HCI busy»); kill только по PID; всё выше Baseband — наша
   ответственность в Bumble (поэтому вендорные баги L2CAP были НАШИ баги).
3. **Python в data path**: каждый RTP-пакет трубы проходит интерпретатор
   (~50 пакетов/с при AAC 256k) — для S905D2 незаметно. Транскодирования нет —
   пакеты пересылаются байт-в-байт (поэтому кодеки входа/выхода должны совпадать).
4. **CTKD в SMP**: h6/h7-деривация связывает LE LTK и classic link key в одну
   запись keystore. Направление важно: LE-пара РАЗДАЁТ link key; SMP поверх
   BR/EDR — выводит LTK ИЗ link key и не смеет раздавать link key обратно.
5. **Keystore/state на ext4 p3** — переживают прошивку rootfs и ребут. p1 остаётся только boot FAT.

## Трассировка сценариев

**Труба**: iPhone(AAC)→эфир→чип→UART→Bumble L2CAP→`forward_packet`(Python)→
L2CAP канала Fosi→UART→чип→эфир→Fosi. Условие: канал к Fosi открыт ДО потока.

**Кнопка пульта Fosi**: ИК→Fosi→AVRCP passthrough (classic AVCTP)→Bumble→
`on_key_event`(peer=колонка)→backchannel→AMS RemoteCommand = GATT-запись по
**BLE** → iPhone. Один сценарий использует ОБА транспорта — суть коммутатора.

**Тумблер ON**: route-cmd→`connect_source`→HCI Create Connection (page)→
auth по link key из keystore→L2CAP AVDTP/AVCTP→iOS читает SDP (с C1 — каждый
коннект)→выход в Control Center. OFF: закрыть AVDTP-сигналинг (L2CAP
Disconnection Request) → iOS каскадно прибирает каналы (reason 0x13 «remote
user terminated», НЕ 0x08 timeout) → пауза и мгновенный возврат маршрута.

**Пара BLE-first**: iOS коннектится на рекламу→SMP (LE Secure Connections,
numeric auto)→ключи LTK+IRK+(CTKD)link key→GATT-подписки AMS/ANCS. Classic
потом поднимается ЭТИМ же ключом без второй пары. ⚠️ classic-first (лаб):
LE-ключи выводятся, но iOS сам LE-соединение НЕ поднимает — AMS мёртв.
