import Foundation
import CoreBluetooth

/// Контракт BLE GATT для bootstrap/discovery Car Thing.
///
/// ⚠️ Источник истины. Device-side (Bumble на QN19) ДОЛЖЕН опубликовать ровно
/// эти UUID. GATT используется ТОЛЬКО для: discovery, capabilities, protocol
/// version, endpoint identity, публикации динамического L2CAP PSM и client
/// toggle/status. Аудио и bulk-данные идут по L2CAP CoC, не по GATT.
///
/// UUID-база `C7C5xxxx-...` (C7C5 ≈ "CarThing CarThing Session") выбрана как
/// приватный 128-битный диапазон, чтобы не конфликтовать с SIG-профилями.
public enum CarThingGATT {
    /// Основной сервис session-транспорта.
    public static let serviceUUID =
        CBUUID(string: "C7C50000-0000-4000-8000-00C7C7C7C7C7")

    /// protocol_version — UInt8, read. Версия CTSP, которую держит устройство.
    public static let protocolVersionUUID =
        CBUUID(string: "C7C50001-0000-4000-8000-00C7C7C7C7C7")

    /// capabilities — JSON/бинарь, read. Роли, транспорты, audio форматы.
    public static let capabilitiesUUID =
        CBUUID(string: "C7C50002-0000-4000-8000-00C7C7C7C7C7")

    /// endpoint_id — UTF-8/бинарь, read. Стабильный id endpoint (напр. из USID).
    public static let endpointIDUUID =
        CBUUID(string: "C7C50003-0000-4000-8000-00C7C7C7C7C7")

    /// current_psm — UInt16 LE, read + notify. Текущий динамический L2CAP CoC PSM.
    public static let currentPSMUUID =
        CBUUID(string: "C7C50004-0000-4000-8000-00C7C7C7C7C7")

    /// client_toggle — UInt8, write. 1 = client on, 0 = client off (session plane).
    public static let clientToggleUUID =
        CBUUID(string: "C7C50005-0000-4000-8000-00C7C7C7C7C7")

    /// status — бинарь, notify. Краткий статус session/route (полный — по CoC).
    public static let statusUUID =
        CBUUID(string: "C7C50006-0000-4000-8000-00C7C7C7C7C7")

    /// Характеристики, которые читаем при bootstrap.
    public static let bootstrapReadUUIDs: [CBUUID] = [
        protocolVersionUUID, capabilitiesUUID, endpointIDUUID, currentPSMUUID,
    ]

    /// Все характеристики сервиса (для discoverCharacteristics).
    public static let allCharacteristicUUIDs: [CBUUID] = [
        protocolVersionUUID, capabilitiesUUID, endpointIDUUID,
        currentPSMUUID, clientToggleUUID, statusUUID,
    ]
}
