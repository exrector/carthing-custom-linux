import Foundation

/// Приёмник remote-mic кадров: PCM16LE, 16 kHz, mono.
///
/// Держит кольцевой буфер последних N секунд (для уровня/диагностики) и при
/// явном запросе пишет debug WAV на диск. STT — позже, отдельным слоем.
///
/// Контракт ресурсной политики: pipeline НЕ запускает захват сам. Кадры
/// поступают только когда session активно стримит mic (явное действие).
public final class AudioPipeline {
    public struct Format: Sendable {
        public let sampleRate: Int
        public let channels: Int
        public let bitsPerSample: Int
        public init(sampleRate: Int = 16_000, channels: Int = 1, bitsPerSample: Int = 16) {
            self.sampleRate = sampleRate
            self.channels = channels
            self.bitsPerSample = bitsPerSample
        }
        var bytesPerSecond: Int { sampleRate * channels * (bitsPerSample / 8) }
    }

    public let format: Format
    private let ringCapacityBytes: Int
    private var ring = Data()

    /// Последний вычисленный RMS-уровень (0...1) — для индикатора «mic active».
    public private(set) var lastRMS: Double = 0
    /// Всего принято PCM-байт за текущую сессию записи.
    public private(set) var totalBytes: UInt64 = 0

    private var wavHandle: FileHandle?
    private var wavURL: URL?
    private var wavDataBytes: UInt32 = 0

    /// - Parameter ringSeconds: сколько секунд аудио держать в кольцевом буфере.
    public init(format: Format = Format(), ringSeconds: Int = 10) {
        self.format = format
        self.ringCapacityBytes = format.bytesPerSecond * ringSeconds
    }

    /// Скормить очередной PCM16LE кадр (payload из CTSP `audio_pcm16`).
    public func ingest(_ pcm: Data) {
        guard !pcm.isEmpty else { return }
        totalBytes += UInt64(pcm.count)

        // Кольцевой буфер.
        ring.append(pcm)
        if ring.count > ringCapacityBytes {
            ring.removeFirst(ring.count - ringCapacityBytes)
        }

        lastRMS = Self.rms(of: pcm)

        // Дозапись в WAV, если активна.
        if let handle = wavHandle {
            handle.write(pcm)
            wavDataBytes += UInt32(pcm.count)
        }
    }

    /// Текущий объём кольцевого буфера в секундах.
    public var bufferedSeconds: Double {
        Double(ring.count) / Double(max(1, format.bytesPerSecond))
    }

    // MARK: - Debug WAV

    /// Начать писать debug WAV. Возвращает URL файла.
    @discardableResult
    public func startRecording(to url: URL? = nil) throws -> URL {
        stopRecording()
        let target = url ?? Self.defaultWAVURL()
        FileManager.default.createFile(atPath: target.path, contents: nil)
        let handle = try FileHandle(forWritingTo: target)
        // Пишем placeholder-заголовок, перепишем размеры в stopRecording().
        handle.write(Self.wavHeader(dataBytes: 0, format: format))
        wavHandle = handle
        wavURL = target
        wavDataBytes = 0
        return target
    }

    /// Остановить запись и финализировать WAV-заголовок. Возвращает URL, если писали.
    @discardableResult
    public func stopRecording() -> URL? {
        guard let handle = wavHandle, let url = wavURL else { return nil }
        // Переписываем корректный заголовок с реальными размерами.
        let header = Self.wavHeader(dataBytes: wavDataBytes, format: format)
        try? handle.seek(toOffset: 0)
        handle.write(header)
        try? handle.close()
        wavHandle = nil
        wavURL = nil
        return url
    }

    public var isRecording: Bool { wavHandle != nil }

    // MARK: - Helpers

    private static func rms(of pcm: Data) -> Double {
        let count = pcm.count / 2
        guard count > 0 else { return 0 }
        var sumSquares = 0.0
        pcm.withUnsafeBytes { raw in
            let samples = raw.bindMemory(to: Int16.self)
            for i in 0..<count {
                let s = Double(Int16(littleEndian: samples[i]))
                sumSquares += s * s
            }
        }
        let mean = sumSquares / Double(count)
        return mean.squareRoot() / Double(Int16.max)
    }

    private static func defaultWAVURL() -> URL {
        let dir = FileManager.default.temporaryDirectory
        let stamp = ISO8601DateFormatter().string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
        return dir.appendingPathComponent("carthing-mic-\(stamp).wav")
    }

    /// Канонический 44-байтный WAV/PCM-заголовок.
    static func wavHeader(dataBytes: UInt32, format: Format) -> Data {
        var d = Data()
        let byteRate = UInt32(format.sampleRate * format.channels * (format.bitsPerSample / 8))
        let blockAlign = UInt16(format.channels * (format.bitsPerSample / 8))

        func le16(_ v: UInt16) { d.append(UInt8(v & 0xFF)); d.append(UInt8((v >> 8) & 0xFF)) }
        func le32(_ v: UInt32) {
            d.append(UInt8(v & 0xFF)); d.append(UInt8((v >> 8) & 0xFF))
            d.append(UInt8((v >> 16) & 0xFF)); d.append(UInt8((v >> 24) & 0xFF))
        }

        d.append(contentsOf: Array("RIFF".utf8))
        le32(36 + dataBytes)                       // ChunkSize
        d.append(contentsOf: Array("WAVE".utf8))
        d.append(contentsOf: Array("fmt ".utf8))
        le32(16)                                   // Subchunk1Size (PCM)
        le16(1)                                    // AudioFormat = PCM
        le16(UInt16(format.channels))
        le32(UInt32(format.sampleRate))
        le32(byteRate)
        le16(blockAlign)
        le16(UInt16(format.bitsPerSample))
        d.append(contentsOf: Array("data".utf8))
        le32(dataBytes)                            // Subchunk2Size
        return d
    }
}
