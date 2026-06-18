import Foundation

/// Режим устройства Car Thing (зеркало device-side модели; см.
/// INPUT-SESSION-OUTPUT-ARCHITECTURE-2026-06-18.md). macOS — НЕ режим, а endpoint.
public enum DeviceMode: String, Codable, Sendable {
    case playNow      // Play Now — дефолт, обычно iPhone как главный аудиовход.
    case switcher     // Коммутатор — явный выбор входов/выходов.
    case reserveUSB   // Резерв / USB.
    case unknown
}

/// Активный аудиовход маршрута.
public enum AudioInput: String, Codable, Sendable {
    case iPhone
    case mac
    case usb
    case localTest
    case none
}

/// Активный аудиовыход маршрута.
public enum OutputSink: String, Codable, Sendable {
    case local       // локальный T9015 / line-out
    case bluetooth   // BT speaker (например, Fosi)
    case usb
    case none
}

/// Фаза session/client plane (отдельно от audio route plane — это инвариант).
public enum SessionPhase: String, Codable, Sendable {
    case off          // client выключен — никакой session-активности
    case idle         // client включён, но поток не идёт
    case connected    // L2CAP CoC session открыт, обмен кадрами
    case streamingMic // активно идёт remote mic PCM
    case error
}

/// Фаза транспортного соединения (BLE).
public enum TransportPhase: String, Codable, Sendable {
    case poweredOff       // CBManager выключен/недоступен
    case unauthorized     // нет разрешения Bluetooth
    case idle             // готов, не сканирует
    case scanning
    case connecting
    case discoveringGATT  // подключён, читаем сервисы/характеристики
    case bootstrapped     // GATT bootstrap прочитан (есть PSM)
    case l2capOpening
    case l2capOpen        // CoC канал открыт
    case disconnected
    case failed
}

/// Снимок состояния RouteGraph + session + транспорта для GUI и diagnostics.
public struct SessionSnapshot: Codable, Sendable, Equatable {
    public var mode: DeviceMode = .unknown
    public var activeAudioInput: AudioInput = .none
    public var activeOutputSink: OutputSink = .none
    public var sessionPhase: SessionPhase = .off
    public var transportPhase: TransportPhase = .idle

    /// client_enabled — управляет ТОЛЬКО session/client plane, не audio route.
    public var clientEnabled: Bool = false
    /// Активен ли поток remote-mic прямо сейчас.
    public var micActive: Bool = false

    public var lastError: String?

    public init() {}
}
