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
    /// Краткий статус Bluetooth microphone session.
    case status = 0x03
    /// Команда управления микрофоном или экранным текстом.
    case command = 0x05
    /// Кадр аудио: PCM16LE 16 kHz mono. Только on-demand.
    case audioPCM16 = 0x06
    /// Ошибка протокольного уровня.
    case error = 0x08
    /// Блочный IMA-ADPCM, mono 8 kHz; каждый блок содержит predictor/index.
    case audioIMAADPCM = 0x09
    /// NTP-подобная синхронизация monotonic clock и измерение CTSP RTT.
    case latencyProbe = 0x0A
    /// Один raw Opus packet, mono 16 kHz, VOIP, 10, 20 или 40 ms.
    case audioOpus = 0x0B
    /// Аутентифицированное обслуживание устройства: файлы, логи, restart.
    case maintenance = 0x0C

    public var description: String {
        switch self {
        case .hello: return "hello"
        case .capabilities: return "capabilities"
        case .status: return "status"
        case .command: return "command"
        case .audioPCM16: return "audio_pcm16"
        case .error: return "error"
        case .audioIMAADPCM: return "audio_ima_adpcm"
        case .latencyProbe: return "latency_probe"
        case .audioOpus: return "audio_opus"
        case .maintenance: return "maintenance"
        }
    }
}
