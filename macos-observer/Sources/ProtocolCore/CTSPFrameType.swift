import Foundation

/// Тип кадра CTSP (CarThing Session Protocol).
///
/// Значения соответствуют контракту из
/// `docs/INPUT-SESSION-OUTPUT-ARCHITECTURE-2026-06-18.md`. Это источник истины
/// для байтовых значений: устройство (QN19) должно использовать те же коды.
public enum CTSPFrameType: UInt8, CaseIterable, Sendable, CustomStringConvertible {
    /// Рукопожатие после открытия L2CAP CoC. Payload: версия/идентификация/timestamp.
    case hello = 0x01
    /// Описание возможностей endpoint (роли, поддерживаемые транспорты, audio форматы).
    case capabilities = 0x02
    /// Краткий статус session/route plane.
    case status = 0x03
    /// Полное состояние RouteGraph (mode/input/output/session/client_enabled).
    case routeState = 0x04
    /// Команда (toggle client, выбор input/output, запрос mic и т.п.).
    case command = 0x05
    /// Кадр аудио: PCM16LE 16 kHz mono. Только on-demand.
    case audioPCM16 = 0x06
    /// Телеметрия/метрики (счётчики, RTT-эхо, состояние очередей).
    case telemetry = 0x07
    /// Ошибка протокольного уровня.
    case error = 0x08

    public var description: String {
        switch self {
        case .hello: return "hello"
        case .capabilities: return "capabilities"
        case .status: return "status"
        case .routeState: return "route_state"
        case .command: return "command"
        case .audioPCM16: return "audio_pcm16"
        case .telemetry: return "telemetry"
        case .error: return "error"
        }
    }
}
