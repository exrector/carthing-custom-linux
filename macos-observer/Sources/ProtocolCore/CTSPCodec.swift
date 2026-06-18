import Foundation

/// Константы протокола CTSP.
public enum CTSP {
    /// Магия заголовка: ASCII "CTSP".
    public static let magic: [UInt8] = Array("CTSP".utf8)
    /// Размер фиксированного заголовка в байтах.
    public static let headerSize = 16
    /// Текущая базовая версия протокола.
    public static let protocolVersion: UInt8 = 1
    /// Защитный лимит на размер payload (защита от рассинхрона/мусора в потоке).
    /// 1 MiB с запасом покрывает любой mic/route/capabilities кадр.
    public static let maxPayloadLength: UInt32 = 1 << 20
}

/// Ошибки кодирования/декодирования CTSP.
public enum CTSPError: Error, Equatable, CustomStringConvertible {
    case badMagic([UInt8])
    case unknownFrameType(UInt8)
    case payloadTooLarge(UInt32)

    public var description: String {
        switch self {
        case .badMagic(let bytes):
            let hex = bytes.map { String(format: "%02x", $0) }.joined(separator: " ")
            return "bad CTSP magic: [\(hex)]"
        case .unknownFrameType(let raw):
            return String(format: "unknown CTSP frame type: 0x%02x", raw)
        case .payloadTooLarge(let len):
            return "CTSP payload too large: \(len) bytes (limit \(CTSP.maxPayloadLength))"
        }
    }
}

/// Без-состояния энкодер кадров CTSP в `Data`.
public enum CTSPEncoder {
    /// Сериализует кадр в байты (заголовок + payload), big-endian для multi-byte полей.
    public static func encode(_ frame: CTSPFrame) -> Data {
        var out = Data(capacity: CTSP.headerSize + frame.payload.count)
        out.append(contentsOf: CTSP.magic)
        out.append(frame.version)
        out.append(frame.type.rawValue)
        out.appendBigEndian(frame.flags)
        out.appendBigEndian(frame.seq)
        out.appendBigEndian(UInt32(frame.payload.count))
        out.append(frame.payload)
        return out
    }
}

/// Потоковый декодер: накапливает входящие байты и извлекает целые кадры
/// по мере их полного поступления. Безопасен к фрагментированным L2CAP-чтениям.
///
/// Реализован как `final class` с внутренним буфером, потому что L2CAP CoC
/// отдаёт данные произвольными чанками, и состояние между чтениями обязано
/// сохраняться. Не потокобезопасен — используйте с одного очереди/run loop.
public final class CTSPFrameDecoder {
    private var buffer = Data()

    public init() {}

    /// Сбросить накопленный буфер (например, при переоткрытии канала).
    public func reset() {
        buffer.removeAll(keepingCapacity: true)
    }

    /// Количество ещё не разобранных байт в буфере.
    public var pendingBytes: Int { buffer.count }

    /// Скормить очередную порцию байт и получить все целиком собранные кадры.
    ///
    /// Бросает `CTSPError` при повреждении потока (несовпадение magic, неизвестный
    /// тип, превышение лимита payload). После ошибки буфер очищается, чтобы
    /// не зациклиться на испорченных данных — вызывающий слой решает, разрывать ли канал.
    @discardableResult
    public func feed(_ data: Data) throws -> [CTSPFrame] {
        buffer.append(data)
        var frames: [CTSPFrame] = []

        while true {
            guard buffer.count >= CTSP.headerSize else { break }

            // Заголовок читаем по абсолютным смещениям от начала буфера.
            let base = buffer.startIndex

            let magic = Array(buffer[base ..< base + 4])
            guard magic == CTSP.magic else {
                let bad = magic
                buffer.removeAll(keepingCapacity: true)
                throw CTSPError.badMagic(bad)
            }

            let version = buffer[base + 4]
            let rawType = buffer[base + 5]
            let flags = buffer.readBigEndianUInt16(at: base + 6)
            let seq = buffer.readBigEndianUInt32(at: base + 8)
            let len = buffer.readBigEndianUInt32(at: base + 12)

            guard len <= CTSP.maxPayloadLength else {
                buffer.removeAll(keepingCapacity: true)
                throw CTSPError.payloadTooLarge(len)
            }

            let total = CTSP.headerSize + Int(len)
            // Ждём, пока придёт весь payload.
            guard buffer.count >= total else { break }

            let payloadStart = base + CTSP.headerSize
            let payload = Data(buffer[payloadStart ..< payloadStart + Int(len)])

            guard let type = CTSPFrameType(rawValue: rawType) else {
                // Неизвестный тип — снимаем кадр из буфера, чтобы продолжить, и сигналим.
                buffer.removeFirst(total)
                throw CTSPError.unknownFrameType(rawType)
            }

            frames.append(
                CTSPFrame(version: version, type: type, flags: flags, seq: seq, payload: payload)
            )
            buffer.removeFirst(total)
        }

        return frames
    }
}

// MARK: - Big-endian helpers

private extension Data {
    mutating func appendBigEndian(_ value: UInt16) {
        append(UInt8((value >> 8) & 0xFF))
        append(UInt8(value & 0xFF))
    }

    mutating func appendBigEndian(_ value: UInt32) {
        append(UInt8((value >> 24) & 0xFF))
        append(UInt8((value >> 16) & 0xFF))
        append(UInt8((value >> 8) & 0xFF))
        append(UInt8(value & 0xFF))
    }

    func readBigEndianUInt16(at index: Index) -> UInt16 {
        (UInt16(self[index]) << 8) | UInt16(self[index + 1])
    }

    func readBigEndianUInt32(at index: Index) -> UInt32 {
        (UInt32(self[index]) << 24)
            | (UInt32(self[index + 1]) << 16)
            | (UInt32(self[index + 2]) << 8)
            | UInt32(self[index + 3])
    }
}
