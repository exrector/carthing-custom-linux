import Foundation
import ProtocolCore

/// Живые метрики транспорта/протокола для observer UI и diagnostic bundle.
public struct TransportMetrics: Codable, Sendable, Equatable {
    public var bytesPerSecIn: Double = 0
    public var bytesPerSecOut: Double = 0
    public var framesPerSec: Double = 0
    public var totalBytesIn: UInt64 = 0
    public var totalBytesOut: UInt64 = 0
    public var totalFramesIn: UInt64 = 0
    public var totalFramesOut: UInt64 = 0

    /// Оценка задержки (мс), напр. RTT hello→первый ответ. nil = не измерялась.
    public var latencyEstimateMs: Double?

    public var lastFrameType: String?
    public var lastSeq: UInt32?

    public init() {}
}

/// Аккумулятор счётчиков с расчётом скоростей по скользящему окну в 1 секунду.
///
/// Не потокобезопасен — обновляйте с одной очереди (main), как и UI.
public final class MetricsAccumulator {
    private var windowStart: Date
    private var bytesInWindow = 0
    private var bytesOutWindow = 0
    private var framesInWindow = 0

    public private(set) var metrics = TransportMetrics()

    public init(now: Date = Date()) {
        windowStart = now
    }

    public func recordIncoming(bytes: Int, frames: [CTSPFrame]) {
        bytesInWindow += bytes
        framesInWindow += frames.count
        metrics.totalBytesIn += UInt64(bytes)
        metrics.totalFramesIn += UInt64(frames.count)
        if let last = frames.last {
            metrics.lastFrameType = last.type.description
            metrics.lastSeq = last.seq
        }
    }

    public func recordOutgoing(bytes: Int) {
        bytesOutWindow += bytes
        metrics.totalBytesOut += UInt64(bytes)
        metrics.totalFramesOut += 1
    }

    public func setLatency(_ ms: Double) {
        metrics.latencyEstimateMs = ms
    }

    /// Пересчитать скорости. Вызывать раз в ~секунду из таймера.
    public func tick(now: Date = Date()) {
        let elapsed = now.timeIntervalSince(windowStart)
        guard elapsed > 0 else { return }
        metrics.bytesPerSecIn = Double(bytesInWindow) / elapsed
        metrics.bytesPerSecOut = Double(bytesOutWindow) / elapsed
        metrics.framesPerSec = Double(framesInWindow) / elapsed
        bytesInWindow = 0
        bytesOutWindow = 0
        framesInWindow = 0
        windowStart = now
    }

    public func reset() {
        metrics = TransportMetrics()
        bytesInWindow = 0
        bytesOutWindow = 0
        framesInWindow = 0
        windowStart = Date()
    }
}
