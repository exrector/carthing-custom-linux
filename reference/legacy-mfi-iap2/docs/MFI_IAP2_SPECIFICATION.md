# MFi / iAP2 Protocol — Полная Спецификация

## Spotify Car Thing (Superbird) — Reverse Engineering Documentation

**Device:** Spotify Car Thing "Superbird"  
**SoC:** Amlogic S905D2, ARM Cortex-A55, aarch64  
**MFi Coprocessor:** I2C address `3-0010`, version `0x07`  
**Kernel:** Linux 4.9.113  
**Kernel Modules:** `apple-mfi-auth.ko` + `apple-mfi-auth-i2c.ko`  
**Device Node:** `/dev/apple_mfi`

---

## Table of Contents

1. [/dev/apple_mfi IOCTL Reference](#1-devapplemfi-ioctl-reference)
2. [MFi Coprocessor Registers (I2C Level)](#2-mfi-coprocessor-registers-i2c-level)
3. [AA00-AA05 Authentication Flow](#3-aa00-aa05-authentication-flow)
4. [PKCS#7 Certificate Structure](#4-pkcs7-certificate-structure)
5. [Identification TLV Protocol](#5-identification-tlv-protocol)
6. [iAP2 Message Codes Complete Reference](#6-iap2-message-codes-complete-reference)
7. [HID Protocol](#7-hid-protocol)
8. [Error Codes & Rejection Reasons](#8-error-codes--rejection-reasons)
9. [Link Layer](#9-link-layer)
10. [Environment Variables](#10-environment-variables)
11. [Troubleshooting Guide](#11-troubleshooting-guide)
12. [Minimal Working Code Example](#12-minimal-working-code-example)

---

## 1. `/dev/apple_mfi` IOCTL Reference

### Device Access

```c
int fd = open("/dev/apple_mfi", O_RDWR);
if (fd < 0) {
    perror("Cannot open /dev/apple_mfi");
    exit(1);
}
```

**⚠️ Важно:** Userspace **НЕ** может обращаться к I2C чипу напрямую через `i2cget`/`i2ctransfer` — ядро монопольно владеет устройством `3-0010`. Все операции — **только через ioctl**.

### Buffer Structure

```c
struct mfi_buf {
    uint32_t len;   // размер буфера
    uint32_t pad;   // выравнивание (обычно 0)
    uint64_t ptr;   // указатель на userspace буфер
};
```

### IOCTL Commands

Все команды используют ioctl family `0x77`.

| Op | Macro | Name | Direction | Size | Challenge-Dep? | Description |
|----|-------|------|-----------|------|----------------|-------------|
| nr1 | `_IOR(0x77, 1, struct mfi_buf)` | `MFI_GET_VERSION` | Read | 1 byte | No | Версия чипа (`0x07`) |
| nr2 | `_IOR(0x77, 2, struct mfi_buf)` | — | Read | variable | No | Неизвестно, возвращает мусор |
| nr3 | `_IOR(0x77, 3, struct mfi_buf)` | — | Read | variable | No | Неизвестно, возвращает мусор |
| nr4 | `_IOR(0x77, 4, struct mfi_buf)` | `MFI_GET_CERTLEN` | Read | 2 bytes | No | Длина сертификата (big-endian, обычно 608) |
| nr5 | `_IOR(0x77, 5, struct mfi_buf)` | `MFI_GET_RESPONSE` | Read | 608 bytes | **No** | **PKCS#7 SignedData контейнер** (статичный) |
| nr6 | `_IOW(0x77, 6, struct mfi_buf)` | `MFI_SET_CHALLENGE` | Write | 32 bytes | N/A | Запись 32-байтного challenge в чип |
| nr7 | `_IOR(0x77, 7, struct mfi_buf)` | `MFI_GET_SIGNATURE` | Read | 64 bytes | **Yes** | **ECDSA подпись** для challenge (r\|\|s) |
| nr8 | `_IOR(0x77, 8, struct mfi_buf)` | `MFI_GET_SERIAL` | Read | variable | No | ASCII serial identifier |

### Helper Function

```c
static int mfi_ioctl(int fd, unsigned long req, void *buf, size_t len) {
    struct mfi_buf mb;
    mb.len = len;
    mb.pad = 0;
    mb.ptr = (uint64_t)(uintptr_t)buf;
    return ioctl(fd, req, &mb);
}
```

### Initialization Sequence

```c
// 1. Get version
uint8_t version = 0;
mfi_ioctl(fd, _IOR(0x77, 1, struct mfi_buf), &version, sizeof(version));
// version == 0x07

// 2. Get certificate length
uint16_t cert_len = 0;
mfi_ioctl(fd, _IOR(0x77, 4, struct mfi_buf), &cert_len, sizeof(cert_len));
// cert_len == 608 (big-endian, может потребоваться byte-swap)

// 3. Read full PKCS#7 certificate
uint8_t cert[608] = {0};
mfi_ioctl(fd, _IOR(0x77, 5, struct mfi_buf), cert, sizeof(cert));

// 4. (Later) Write challenge
uint8_t challenge[32] = { /* 32 bytes from iPhone AA02 */ };
mfi_ioctl(fd, _IOW(0x77, 6, struct mfi_buf), challenge, sizeof(challenge));

// 5. Read ECDSA signature response
uint8_t signature[64] = {0};
mfi_ioctl(fd, _IOR(0x77, 7, struct mfi_buf), signature, sizeof(signature));
```

### ⚠️ Критические Особенности

- **nr5 (0x05)** возвращает **статичный** PKCS#7 blob — это сертификат, **НЕ подпись**
- **nr7 (0x07)** возвращает **зависящую от challenge** 64-байтную ECDSA подпись
- **nr5 ≠ nr7** — это РАЗНЫЕ операции. Путаница между ними = провал аутентификации (AA04)
- nr5 = `MFI_GET_RESPONSE` = сертификат (608 байт)
- nr7 = `MFI_GET_SIGNATURE` = подпись (64 байта)

---

## 2. MFi Coprocessor Registers (I2C Level)

Для понимания того, что происходит на уровне ядра. Userspace **НЕ** может обращаться к этим регистрам напрямую.

| Register | Access | Size | Description |
|----------|--------|------|-------------|
| `0x30` | Read | 2 bytes | Длина сертификата |
| `0x31` | Read | variable | Данные сертификата |
| `0x4E` | Write | 32 bytes | Запись challenge |
| `0x12` | Read | 64 bytes | Чтение ECDSA подписи |
| `0x21` | Read | 1 byte | Проверка длины challenge (ожидает `0x20`) |

### I2C Address
- **Bus:** 3
- **Address:** `0x10`
- **Notation:** `3-0010`

### Kernel Log Messages
```
apple_mfi_auth 3-0010: MFI cert len: 608
```

### Sleep State
Чип может переходить в спящий режим. Ядро использует `retry_if_chip_is_sleeping()` для повторных попыток.

---

## 3. AA00-AA05 Authentication Flow

### Overview

Полный цикл MFi аутентификации:

```
┌─────────┐                              ┌────────┐
│  iPhone  │                              │Accessory│
└────┬─────┘                              └───┬────┘
     │                                        │
     │  AA00 RequestAuthenticationCertificate  │
     │────────────────────────────────────────>│
     │                                        │
     │  AA01 AuthenticationCertificate         │
     │  (608B PKCS#7 SignedData via param 0x0)│
     │<────────────────────────────────────────│
     │                                        │
     │  AA02 AuthenticationChallenge           │
     │  (32-byte random challenge)             │
     │────────────────────────────────────────>│
     │                                        │
     │  ioctl: SET_CHALLENGE(32B)             │
     │  ioctl: GET_SIGNATURE() → 64B          │
     │                                        │
     │  AA03 AuthenticationChallengeResponse   │
     │  (64-byte ECDSA signature r||s)         │
     │<────────────────────────────────────────│
     │                                        │
     │  AA05 AuthenticationResult (SUCCESS)    │
     │────────────────────────────────────────>│
     │                                        │
     │  или AA04 (FAILURE)                    │
     │────────────────────────────────────────>│
```

### AA00 — RequestAuthenticationCertificate

**Direction:** iPhone → Accessory  
**Message ID:** `0xAA00`  
**Payload:** None

iPhone запрашивает MFi сертификат аксессуара.

### AA01 — AuthenticationCertificate Response

**Direction:** Accessory → iPhone  
**Message ID:** `0xAA01`  
**Parameter Type:** `0x0000`  
**Payload:** 608-byte PKCS#7 SignedData container

```
Payload format:
[Param Type: 0x0000 (2 bytes)] [Length: 0x0260 (2 bytes)] [Data: 608 bytes]
```

**⚠️ КРИТИЧНО:** iPhone требует полный PKCS#7 SignedData контейнер (608 байт), а НЕ извлечённый X.509 сертификат (469 байт).

### AA02 — AuthenticationChallenge

**Direction:** iPhone → Accessory  
**Message ID:** `0xAA02`  
**Payload:** 32-byte random challenge

Случайные данные от iPhone, которые аксессуар должен подписать через MFi чип.

### AA03 — AuthenticationChallengeResponse

**Direction:** Accessory → iPhone  
**Message ID:** `0xAA03`  
**Payload:** 64-byte ECDSA signature (raw r||s concatenation, NOT ASN.1 wrapped)

```
Algorithm:
1. Write challenge to chip: ioctl(nr6, challenge, 32)
2. Read signature from chip: ioctl(nr7, signature, 64)
3. Send signature to iPhone in AA03
```

**⚠️ КРИТИЧНО:**
- Подпись **НЕ** в ASN.1 формате — это сырые конкатенированные r и s значения (32 + 32 = 64 байта)
- Для одного и того же challenge всегда возвращает одинаковую подпись
- Для разных challenge — разные подписи

### AA04 — AuthenticationFailure

**Direction:** iPhone → Accessory  
**Message ID:** `0xAA04`

Аутентификация провалена. Возможные причины:

| Причина | Когда возникает |
|---------|----------------|
| X.509 вместо PKCS#7 | Отправлен 469B X.509 cert в AA01 вместо 608B PKCS#7 |
| Неправильная подпись | Использован nr5 (статичный cert) вместо nr7 (подпись) в AA03 |
| Неверный challenge | Challenge не записан в чип перед чтением подписи |

### AA05 — AuthenticationResult (Success)

**Direction:** iPhone → Accessory  
**Message ID:** `0xAA05`

Аутентификация успешна. Переход к Identification фазе.

---

## 4. PKCS#7 Certificate Structure

### 608 байт vs 469 байт

| Размер | Источник | Формат | Работает? |
|--------|----------|--------|-----------|
| **608 байт** | `ioctl nr5` (`MFI_GET_RESPONSE`) | PKCS#7 SignedData container | ✅ **ДА** |
| 469 байт | Извлечённый X.509 из PKCS#7 | Bare X.509 certificate | ❌ Нет (AA04) |

### PKCS#7 SignedData Structure

Начало blob (первые байты):
```
30 82 02 5c  - ASN.1 SEQUENCE, length 0x025c (604 bytes follow)
  06 09 2a 86 48 86 f7 0d 01 07 02  - OID: PKCS#7 signedData (1.2.840.113549.1.7.2)
  ...
```

### Содержимое PKCS#7 контейнера

- PKCS#7 SignedData wrapper
- Встроенный X.509 сертификат (те самые 469 байт)
- Информация о подписанте (SignerInfo)
- Apple CA метаданные
- Криптографические метаданные

### ASN.1 Структура (упрощённо)

```
PKCS#7 SignedData {
  version
  digestAlgorithms
  contentType: signedData
  contentInfo
  certificates {
    X.509 certificate (469 bytes)  ← ЭТОГО НЕДОСТАТОЧНО
    Apple CA chain
  }
  signerInfo {
    issuerAndSerialNumber
    digestAlgorithm: ecdsa-with-SHA256
    signatureAlgorithm
    encryptedDigest (ECDSA signature)
  }
  ...
}
```

### Почему iPhone отвергает X.509

iPhone валидирует **весь PKCS#7 контейнер**, а не только встроенный сертификат. Отправка только X.509 (469B) вызывает немедленное отклонение на AA04.

### Legacy Mode

Переменная окружения `IAP2_CERT_X509_ONLY=1` принудительно использует 469B X.509 режим (только для отладки — всегда вызывает AA04).

---

## 5. Identification TLV Protocol

### Overview

После успешной AA05 аутентификации начинается фаза идентификации:

```
iPhone → Accessory:  0x1D00 (StartIdentification)
Accessory → iPhone:  0x1D01 (IdentificationInformation) — TLV payload
iPhone → Accessory:  0x1D02 (IdentificationAccepted)
                  или 0x1D03 (IdentificationRejected)
```

### TLV Format

Каждый параметр:
```
[Type: 2 bytes big-endian] [Length: 2 bytes big-endian] [Data: Length bytes]
```

Полный IdentificationInformation = конкатенация TLV параметров.

### Все известные параметры

| Type | Name | Required | Data Format | Notes |
|------|------|----------|-------------|-------|
| `0x0000` | AccessoryName | ✅ Да | NUL-terminated string | `"Spotify Car Thing\0"` |
| `0x0001` | ModelName | ✅ Да | NUL-terminated string | `"Car Thing\0"` |
| `0x0002` | Manufacturer | ✅ Да | NUL-terminated string | `"Spotify USA Inc.\0"` |
| `0x0003` | SerialNumber | ✅ Да | NUL-terminated string | Serial устройства |
| `0x0004` | FirmwareVersion | ✅ Да | NUL-terminated string | Версия прошивки |
| `0x0005` | HardwareVersion | ✅ Да | NUL-terminated string | Версия железа |
| `0x0006` | SupportedMessageIDs (outgoing) | ❌ **ПУСТО** | `NULL, 0` | Непустое значение = rejection |
| `0x0007` | SupportedMessageIDs (incoming) | ❌ **ПУСТО** | `NULL, 0` | Непустое значение = rejection |
| `0x0008` | PowerCapability | ✅ Да | 1 byte | `0x00` (self-powered) |
| `0x0009` | MaxCurrent | ✅ Да | 2 bytes | `{0x00, 0x64}` (100 mA) |
| `0x000A` | SupportedExternalAccessoryProtocol | ❌ **ПРОПУСТИТЬ** | N/A | Любой формат вызывает rejection |
| `0x000B` | Capabilities | ❌ **ПРОПУСТИТЬ** | N/A | Любое значение вызывает rejection |

### ⚠️ КРИТИЧНО для 0x0006 и 0x0007

Эти параметры **ДОЛЖНЫ быть пустыми**:
```c
// НЕПРАВИЛЬНО:
tlv_append(0x0006, some_message_ids, some_len);  // → 0x1D03 rejection

// ПРАВИЛЬНО:
tlv_append(0x0006, NULL, 0);  // empty
tlv_append(0x0007, NULL, 0);  // empty
```

### ⚠️ КРИТИЧНО для 0x000A

Параметр `SupportedExternalAccessoryProtocol` **ДОЛЖЕН БЫТЬ ПОЛНОСТЬЮ ОПУЩЕН**.

Все протестированные значения отклонены с кодом `00 04 00 0a`:
- `com.apple.nowplaying\0` (21 байт)
- `com.apple.nowplaying` (20 байт без null)
- `com.apple.pairedsync\0`
- `com.apple.mfi.audio\0`
- Несколько протоколов concatenated
- С/без null terminator

**Решение:** Полностью пропустить параметр `0x000A`.

### Рабочая конфигурация

Минимальный working IdentificationInformation (~173 байта):

```c
// Строковые параметры (NUL-terminated!)
tlv_string(0x0000, "Spotify Car Thing");  // AccessoryName
tlv_string(0x0001, "Car Thing");           // ModelName
tlv_string(0x0002, "Spotify USA Inc.");   // Manufacturer
tlv_string(0x0003, serial_number);         // SerialNumber
tlv_string(0x0004, "1.0.0");               // FirmwareVersion
tlv_string(0x0005, "1.0");                 // HardwareVersion

// Пустые списки
tlv_append(0x0006, NULL, 0);  // SupportedMessageIDs outgoing — ПУСТО
tlv_append(0x0007, NULL, 0);  // SupportedMessageIDs incoming — ПУСТО

// Питание
uint8_t power = 0x00;
tlv_append(0x0008, &power, 1);  // PowerCapability: self-powered

uint16_t current = 0x0064;
tlv_append(0x0009, &current, 2);  // MaxCurrent: 100 mA

// НЕ включать: 0x000A (SupportedExternalAccessoryProtocol)
// НЕ включать: 0x000B (Capabilities)
```

### Все строки NUL-terminated

Все строковые параметры **обязаны** заканчиваться нулём. iPhone строго проверяет это.

---

## 6. iAP2 Message Codes Complete Reference

### Link Layer

| Code | Name | Direction | Description |
|------|------|-----------|-------------|
| `FF 5A` | SOF (Start of Frame) | Both | Начало фрейма |
| — | SYN | Both | Initial handshake |
| — | SYN+ACK | Both | Response to SYN |
| — | ACK | Both | Normal acknowledgment |
| — | EAK (Explicit ACK) | iPhone→Accessory | Список seq номеров для ретрансмиссии |

### Authentication (AAxx Family)

| Code | Name | Direction | Description |
|------|------|-----------|-------------|
| `0xAA00` | RequestAuthenticationCertificate | iPhone→Accessory | Запрос MFi сертификата |
| `0xAA01` | AuthenticationCertificate | Accessory→iPhone | 608B PKCS#7 cert, param 0x0000 |
| `0xAA02` | AuthenticationChallenge | iPhone→Accessory | 32-byte random challenge |
| `0xAA03` | AuthenticationChallengeResponse | Accessory→iPhone | 64B ECDSA подпись (nr7) |
| `0xAA04` | AuthenticationFailure | iPhone→Accessory | Ошибка аутентификации |
| `0xAA05` | AuthenticationResult | iPhone→Accessory | Успех |

### Identification (1Dxx Family)

| Code | Name | Direction | Description |
|------|------|-----------|-------------|
| `0x1D00` | StartIdentification | iPhone→Accessory | Начало фазы идентификации |
| `0x1D01` | IdentificationInformation | Accessory→iPhone | TLV payload с информацией об устройстве |
| `0x1D02` | IdentificationAccepted | iPhone→Accessory | Идентификация успешна |
| `0x1D03` | IdentificationRejected | iPhone→Accessory | Отклонение с RejectedParameterID |

### Control Session

| Code | Name | Direction | Description |
|------|------|-----------|-------------|
| `0x4040` | CSM header prefix | Both | Префикс Control Session Message |

### NowPlaying (40xx/48xx Family)

| Code | Name | Direction | Description |
|------|------|-----------|-------------|
| `0x40C8` | StartNowPlayingUpdates | Accessory→iPhone | Подписка на метаданные NowPlaying |
| `0x4800` | NowPlayingUpdate | iPhone→Accessory | Метаданные (title, artist, album) — **НЕ ПРИХОДИТ** |

**⚠️ ВАЖНО:** `0x40C8` всегда получает ACK от iPhone, но `0x4800` **никогда не приходит**. Apple Music не поддерживает iAP2 NowPlaying protocol. Используйте AVRCP `MediaPlayer1` D-Bus API вместо этого.

### HID (68xx Family)

| Code | Name | Direction | Description |
|------|------|-----------|-------------|
| `0x6800` | StartHID | Accessory→iPhone | Инициализация HID подсистемы |
| `0x6801` | AccessoryHIDReport | Accessory→iPhone | HID отчёт (нажатие кнопки) |
| `0x6802` | DeviceHIDReport | iPhone→Accessory | Входящий HID отчёт от устройства |
| `0x6803` | StopHID | Accessory→iPhone | Остановка HID подсистемы |

---

## 7. HID Protocol

### HID Usage Codes

| Usage Code | Function | HID Mode | Результат |
|------------|----------|----------|-----------|
| `0x00CD` | Play/Pause | Все | Отправлено, ACK, **НЕТ эффекта на музыку** |
| `0x00B5` | Previous Track | Все | Отправлено, ACK, нет эффекта |
| `0x00B6` | Next Track | Все | Отправлено, ACK, нет эффекта |
| `0x00B0` | Volume Up | Все | Отправлено, ACK, нет эффекта |
| `0x00AE` | Volume Down | Все | Отправлено, ACK, нет эффекта |

### HID Packet Format (Mode 1 — default)

```
[Link: FF 5A ...] [MsgID: 68 01] [Usage Code BE: 2 bytes] ...
```

Пример Play/Pause (0x00CD):
```
FF 5A ... 68 01 ... 00 CD
```

### 6 HID Modes (обнаружено)

| Mode | Message ID | Usage Encoding | Report ID | Notes |
|------|-----------|----------------|-----------|-------|
| 1 | `0x6801` | Big-endian 16-bit | None | Default |
| 2 | `0x6801` | Big-endian | `0x02` | RID variant |
| 3 | `0x6802` | Big-endian | N/A | Legacy message |
| 5 | `0x6801` | Little-endian 16-bit | None | LE variant |
| 6 | `0x6801` | Little-endian 16-bit | `0x01` | LE + RID 0x01 |

Mode 4 не обнаружен.

### ⚠️ HID не управляет музыкой

**Проблема:** iPhone ACK'ит HID пакеты (отправляет EAK), но **не применяет** их к Spotify/Apple Music.

**Тестировалось:**
- Все доступные режимы (1, 5, 6)
- С открытым Apple Music (играет и не играет)
- С Spotify
- С разными usage codes

**Гипотезы:**
1. Неверный формат HID для данной iOS версии
2. Apple Music не поддерживает iAP2 HID control
3. Не выполнена prerequisite — NowPlaying subscription (но 0x40C8 ACK'нут)
4. Отсутствует capability negotiation в Identification
5. Нужен External Accessory session context, не только control session

### ✅ Альтернатива: AVRCP

Для управления медиа используйте **AVRCP** (PSM 0x17) через BlueZ `MediaControl1` D-Bus API — это работает стабильно.

```python
# Рабочий способ управления музыкой через AVRCP
import dbus
bus = dbus.SystemBus()
player = dbus.Interface(
    bus.get_object('org.bluez', player_path),
    'org.bluez.MediaControl1'
)
player.PlayPause()  # Работает!
player.Next()       # Работает!
player.Previous()   # Работает!
```

---

## 8. Error Codes & Rejection Reasons

### Authentication Errors

| Code | Name | Когда | Причина | Решение |
|------|------|-------|---------|---------|
| `AA04` | AuthenticationFailure | После AA01 | X.509 (469B) вместо PKCS#7 (608B) | Использовать nr5 (608B blob) |
| `AA04` | AuthenticationFailure | После AA03 | nr5 (статичный cert) вместо nr7 (подпись) | Использовать nr7 для AA03 |

### Identification Rejection Format

Формат отклонения `0x1D03`:
```
00 04 00 XX
```
где `XX` — ID отвергнутого параметра (big-endian).

### Все коды отклонений

| Rejection Payload | Параметр | Причина | Решение |
|-------------------|----------|---------|---------|
| `00 04 00 0a` | `0x000A` SupportedExternalAccessoryProtocol | Формат/содержимое протокола не совпадает с ожиданиями iPhone | **Пропустить 0x000A полностью** |
| `00 04 00 11` | `0x0011` BluetoothTransportComponent | Mismatch компонента BT транспорта | Исправить другие параметры |
| `00 04 00 06` | `0x0006` SupportedMessageIDs (outgoing) | Непустой список | **Установить пустым** (NULL, 0) |
| `00 04 00 07` | `0x0007` SupportedMessageIDs (incoming) | Непустой список | **Установить пустым** (NULL, 0) |
| `00 04 00 0b` | `0x000B` Capabilities | Значение `0x03` в 1-байтном формате | **Пропустить 0x000B полностью** |

### Bluetooth / Connection Errors

| Error | Context | Notes | Решение |
|-------|---------|-------|---------|
| `org.bluez.Error.Failed` | Reconnect от аксессуара | iPhone отклоняет accessory-initiated reconnect | Пользователь должен нажать "Connect" |
| `Errno 111` (Connection refused) | Raw L2CAP AVRCP connect | iPhone отклоняет outgoing L2CAP | Использовать incoming connection от iPhone |
| `ServicesResolved = false` | BlueZ 5.49 | Firmware bug | Проверять `Connected` вместо `ServicesResolved` |
| `No such device/address` | `i2cget` к 3-0010 | Ядро монопольно владеет I2C | Использовать ioctl через `/dev/apple_mfi` |

---

## 9. Link Layer

### Framing

Start of Frame (SOF): `FF 5A` (2-byte sequence)

### Packet Types

- **SYN** — Initial handshake
- **SYN+ACK** — Response to SYN
- **ACK** — Normal acknowledgment
- **EAK** (Explicit ACK) — Список seq номеров требующих ретрансмиссии
- **DATA** — Полезные данные

### RFCOMM

- **Channel:** 3 (iAP2 accessory server)
- **Mode:** Server (AutoConnect)
- **Accessory UUID:** `00000000-deca-fade-deca-deafdecacaff` (CAFF!)
- **Device UUID:** `00000000-deca-fade-deca-deafdecafe` (CAFE)

### SDP Record

BlueZ на Car Thing не создаёт SDP record при вызове `RegisterProfile` через `gdbus`/`dbus-send`. Stock `qt-superbird-app` использует libdbus C API для правильной регистрации.

Пример SDP XML:
```xml
<?xml version="1.0" encoding="UTF-8" ?>
<record>
  <attribute id="0x0001">
    <sequence>
      <uuid value="0x0003"/>
    </sequence>
  </attribute>
  <attribute id="0x0004">
    <sequence>
      <sequence>
        <uuid value="0x0003"/>
        <sequence>
          <uint8 value="0x03"/>
        </sequence>
      </sequence>
    </sequence>
  </attribute>
  <attribute id="0x0009">
    <sequence>
      <sequence>
        <uuid value="0x1108"/>
        <uuid value="0x110E"/>
      </sequence>
    </sequence>
  </attribute>
  <attribute id="0x0100">
    <text encoding="utf-8" value="iAP2 Accessory"/>
  </attribute>
</record>
```

---

## 10. Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `IAP2_CERT_X509_ONLY=1` | Force 469B X.509 cert mode (debug only — causes AA04) | 0 |
| `IAP2_CERT_RAW_BLOB=1` | Force 608B PKCS#7 mode | 1 (now default) |
| `IAP2_TEST_HID_MODE=N` | Select HID mode (1-6) | 1 |
| `IAP2_TEST_HID_USAGE=0xXXXX` | Auto-send HID usage after identification | — |
| `IAP2_HID_RESET_FIRST=1` | Send StopHID before StartHID | 0 |
| `IAP2_HID_FIRST=1` | Send StartHID before StartNowPlayingUpdates | — |
| `IAP2_HID_FIRST=0` | Skip StartHID, only send NowPlaying | — |
| `IAP2_ACTIVE_CONNECT=1` | Enable active connection fallback | 0 |
| `IAP2_REGISTER_CLIENT_PROFILE=1` | Register device profile (CAFE) | 0 |

---

## 11. Troubleshooting Guide

### MFi Authentication Fails (AA04)

**Симптом:** iPhone отправляет AA04 после AA01 или AA03.

**Чеклист:**
1. ✅ Используете ли вы 608B PKCS#7 (nr5), а не 469B X.509?
2. ✅ Для AA03 используете ли nr7 (подпись), а не nr5 (сертификат)?
3. ✅ Challenge (32B) записан в чип через `SET_CHALLENGE` (nr6) перед чтением подписи?
4. ✅ Подпись (64B) из nr7 — сырые r||s, НЕ ASN.1 wrapped?

**Диагностика:**
```bash
# Проверить MFi модуль
lsmod | grep apple_mfi
modinfo apple-mfi-auth-i2c.ko

# Проверить устройство
ls -la /dev/apple_mfi

# Проверить ioctl nr5 (сертификат)
# Первые байты должны начинаться с 30 82 02 5c

# Проверить ioctl nr7 (подпись)
# Должна меняться при разных challenge
```

### Identification Rejected (0x1D03)

**Симптом:** iPhone отправляет `00 04 00 XX`.

**По последнему байту XX:**

| XX | Проблема | Решение |
|----|----------|---------|
| `0a` | SupportedExternalAccessoryProtocol | **Пропустить 0x000A** |
| `06` | Non-empty SupportedMessageIDs outgoing | **Установить пустым** |
| `07` | Non-empty SupportedMessageIDs incoming | **Установить пустым** |
| `0b` | Capabilities | **Пропустить 0x000B** |
| `11` | BluetoothTransportComponent | Исправить другие параметры |

### HID Commands Not Working

**Симптом:** iPhone ACK'ит HID пакеты, но музыка не управляется.

**Это известная нерешённая проблема.** Текущие рекомендации:

1. ✅ Использовать AVRCP через BlueZ `MediaControl1` для управления музыкой — **это работает**
2. ❌ iAP2 HID не контролирует медиа на iOS через Car Thing
3. 💡 Альтернатива: **BLE AMS** (Apple Media Service) — официальный BLE сервис для медиа, не требует MFi чипа

### BlueZ Issues

**`ServicesResolved` никогда не становится true:**
- Это firmware bug BlueZ 5.49 на Car Thing
- Проверять `Connected` вместо `ServicesResolved`

**`bluetoothctl connect` сообщает ошибку, но подключение происходит:**
- Известная проблема — игнорировать ошибку

**iPhone не вызывает `Profile1.NewConnection`:**
- iPhone ожидает что аксессуар будет сервером, а не клиентом
- Решение: использовать `startup_active_connect_if_available()` — сканировать D-Bus при старте на предмет уже подключённых устройств

### ADB Issues

**`adb devices` показывает пустой список:**
```bash
adb kill-server && sleep 2 && adb start-server && adb devices -l
```

**`adb reboot` не работает:**
- Car Thing **НЕ** реагирует на `adb reboot`
- Необходимо **физически** вынуть и вставить USB кабель

---

## 12. Minimal Working Code Example

### Complete MFi Authentication + Identification

```c
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>

#define MFI_DEVICE "/dev/apple_mfi"

struct mfi_buf {
    uint32_t len;
    uint32_t pad;
    uint64_t ptr;
};

static int mfi_ioctl(int fd, unsigned long req, void *buf, size_t len) {
    struct mfi_buf mb;
    mb.len = len;
    mb.pad = 0;
    mb.ptr = (uint64_t)(uintptr_t)buf;
    return ioctl(fd, req, &mb);
}

int main() {
    int mfi_fd = open(MFI_DEVICE, O_RDWR);
    if (mfi_fd < 0) {
        perror("Cannot open /dev/apple_mfi");
        return 1;
    }

    // 1. Get MFi chip version
    uint8_t version = 0;
    mfi_ioctl(mfi_fd, _IOR(0x77, 1, struct mfi_buf), &version, sizeof(version));
    printf("MFi chip version: 0x%02x\n", version);
    // Expected: 0x07

    // 2. Get certificate length
    uint16_t cert_len = 0;
    mfi_ioctl(mfi_fd, _IOR(0x77, 4, struct mfi_buf), &cert_len, sizeof(cert_len));
    printf("MFi cert length: %d bytes\n", cert_len);
    // Expected: 608

    // 3. Read full PKCS#7 certificate (608 bytes)
    uint8_t pkcs7_cert[608] = {0};
    mfi_ioctl(mfi_fd, _IOR(0x77, 5, struct mfi_buf), pkcs7_cert, sizeof(pkcs7_cert));
    printf("PKCS#7 cert first bytes: %02x %02x %02x %02x\n",
           pkcs7_cert[0], pkcs7_cert[1], pkcs7_cert[2], pkcs7_cert[3]);
    // Expected: 30 82 02 5c (ASN.1 SEQUENCE)

    // --- Wait for AA00 from iPhone via RFCOMM ---
    // --- Send AA01 with pkcs7_cert (608 bytes) in param 0x0000 ---

    // --- Wait for AA02 with 32-byte challenge ---
    uint8_t challenge[32] = { /* from iPhone AA02 */ };

    // 4. Write challenge to MFi chip
    mfi_ioctl(mfi_fd, _IOW(0x77, 6, struct mfi_buf), challenge, sizeof(challenge));

    // 5. Read ECDSA signature (64 bytes, raw r||s)
    uint8_t signature[64] = {0};
    mfi_ioctl(mfi_fd, _IOR(0x77, 7, struct mfi_buf), signature, sizeof(signature));

    // --- Send AA03 with signature (64 bytes) to iPhone ---
    // --- Wait for AA05 (success) or AA04 (failure) ---

    // After AA05, send IdentificationInformation (TLV):
    // TLV params: 0x0000-0x0005 (strings), 0x0006-0x0007 (empty),
    //             0x0008 (power), 0x0009 (current)
    // OMIT: 0x000A (SupportedExternalAccessoryProtocol)
    // OMIT: 0x000B (Capabilities)

    close(mfi_fd);
    return 0;
}
```

### TLV Helper

```c
void tlv_append(FILE *fp, uint16_t type, const void *data, uint16_t len) {
    uint16_t be_type = __builtin_bswap16(type);
    uint16_t be_len = __builtin_bswap16(len);
    fwrite(&be_type, 2, 1, fp);
    fwrite(&be_len, 2, 1, fp);
    if (data && len > 0) {
        fwrite(data, 1, len, fp);
    }
}

void tlv_string(FILE *fp, uint16_t type, const char *str) {
    uint16_t len = strlen(str) + 1;  // +1 for NUL terminator
    tlv_append(fp, type, str, len);
}
```

### Building IdentificationInformation

```c
uint8_t tlv_buf[256];
FILE *fp = fmemopen(tlv_buf, sizeof(tlv_buf), "wb");

tlv_string(fp, 0x0000, "Spotify Car Thing");  // AccessoryName
tlv_string(fp, 0x0001, "Car Thing");           // ModelName
tlv_string(fp, 0x0002, "Spotify USA Inc.");   // Manufacturer
tlv_string(fp, 0x0003, "SUPERBIRD123");       // SerialNumber
tlv_string(fp, 0x0004, "1.0.0");               // FirmwareVersion
tlv_string(fp, 0x0005, "1.0");                 // HardwareVersion

tlv_append(fp, 0x0006, NULL, 0);  // SupportedMessageIDs outgoing — EMPTY
tlv_append(fp, 0x0007, NULL, 0);  // SupportedMessageIDs incoming — EMPTY

uint8_t power = 0x00;
tlv_append(fp, 0x0008, &power, 1);  // PowerCapability: self-powered

uint16_t current = __builtin_bswap16(0x0064);
tlv_append(fp, 0x0009, &current, 2);  // MaxCurrent: 100 mA

// NOT: 0x000A (SupportedExternalAccessoryProtocol) — OMIT
// NOT: 0x000B (Capabilities) — OMIT

size_t tlv_len = ftell(fp);
fclose(fp);

// Send 0x1D01 with tlv_buf (tlv_len bytes)
```

---

## Architecture Decision: Dual-Protocol

Для полноценного управления медиа на iPhone через Car Thing используется **два протокола**:

| Протокол | Назначение | Статус |
|----------|-----------|--------|
| **AVRCP** (PSM 0x17, BlueZ MediaControl1) | Управление музыкой (Play/Pause/Next/Prev/Volume) | ✅ **Работает** |
| **iAP2** (RFCOMM ch3) | NowPlaying метаданные (title, artist, album) | ❌ 0x4800 не приходит |

**Альтернатива для метаданных:** BLE AMS (Apple Media Service) — официальный BLE сервис, не требует MFi чипа.

---

## References

- **NOTES.md** — Append-only project log (3455 lines)
- **iap2_agent.c** — Full C implementation (~2000 lines)
- **avrcp_ctrl.py** — Working AVRCP media control
- **Apple MFi Specification** — (under NDA, not public)
- **iAP2 Protocol** — (reverse engineered, not public)

---

## License & Disclaimer

This document is based on **reverse engineering** of the Spotify Car Thing device. The iAP2 protocol and MFi authentication flow are proprietary Apple technologies. This documentation is provided for **educational and research purposes only**.

If you are developing a commercial Apple accessory, you **MUST** go through the official Apple MFi certification program: https://mfi.apple.com/

---

**Generated:** 2026-04-13  
**Based on:** Reverse engineering sessions (Checkpoints 001-014), NOTES.md, iap2_agent.c  
**For:** Developers working with Spotify Car Thing / MFi / iAP2 protocols
