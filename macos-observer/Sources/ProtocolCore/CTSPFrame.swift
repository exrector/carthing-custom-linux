import Foundation

/// Один кадр CTSP.
///
/// Бинарный заголовок (16 байт, поля multi-byte в big-endian / network order):
/// ```text
/// magic:   4 bytes  "CTSP"
/// version: 1 byte
/// type:    1 byte
/// flags:   2 bytes
/// seq:     4 bytes
/// len:     4 bytes
/// payload: len bytes
/// ```
public struct CTSPFrame: Equatable, Sendable {
    /// Версия протокола. Текущая базовая версия — 1.
    public var version: UInt8
    /// Тип кадра.
    public var type: CTSPFrameType
    /// Битовые флаги кадра (зарезервированы; младшие биты — ниже).
    public var flags: UInt16
    /// Порядковый номер (монотонно растёт у отправителя).
    public var seq: UInt32
    /// Полезная нагрузка.
    public var payload: Data

    public init(
        version: UInt8 = CTSP.protocolVersion,
        type: CTSPFrameType,
        flags: UInt16 = 0,
        seq: UInt32 = 0,
        payload: Data = Data()
    ) {
        self.version = version
        self.type = type
        self.flags = flags
        self.seq = seq
        self.payload = payload
    }
}

public extension CTSPFrame {
    /// Зарезервированные флаги кадра.
    enum Flag {
        /// Полезная нагрузка — продолжение фрагментированного логического сообщения.
        public static let fragment: UInt16 = 1 << 0
        /// Кадр требует подтверждения (для будущего reliability-слоя).
        public static let needsAck: UInt16 = 1 << 1
        /// Первые 20 байт audio payload: capture_end_ns, send_ns, dsp_us.
        public static let audioTiming: UInt16 = 1 << 8
        /// IMA-ADPCM содержит mono 16 kHz вместо совместимого режима 8 kHz.
        public static let audioRate16K: UInt16 = 1 << 9
    }
}
