// ─────────────────────────────────────────────────────────────────────────────
// ВРЕМЕННЫЙ ФАЙЛ ДЛЯ ТЕСТОВ КЛИЕНТ-СЕРВЕР (Claude, 2026-06-18).
// Движок CTSP поверх SessionLink. Используется и клиентом, и mock-сервером в
// loopback-пробах связки. См. macos-observer/MANIFEST.md.
// ─────────────────────────────────────────────────────────────────────────────
import Foundation

/// Сессия CTSP поверх любого `SessionLink`.
///
/// Берёт на себя: автоинкремент seq при отправке, потоковое декодирование
/// входящих байт в кадры, проброс callbacks и счётчиков. Не потокобезопасен —
/// потребляйте колбэки с очереди транспорта.
public final class CTSPSession {
    private let link: SessionLink
    private let decoder = CTSPFrameDecoder()
    private var seq: UInt32 = 0

    /// Декодированный входящий кадр.
    public var onFrame: ((CTSPFrame) -> Void)?
    /// Канал поднялся/упал.
    public var onConnected: ((Bool) -> Void)?
    /// Принято N сырых байт.
    public var onBytesIn: ((Int) -> Void)?
    /// Отправлено N сырых байт.
    public var onBytesOut: ((Int) -> Void)?
    /// Ошибка транспорта или декодирования.
    public var onError: ((String) -> Void)?

    public init(link: SessionLink) {
        self.link = link
        link.onBytes = { [weak self] data in self?.handleBytes(data) }
        link.onStateChange = { [weak self] up in self?.onConnected?(up) }
        link.onError = { [weak self] msg in self?.onError?(msg) }
    }

    public func start() { link.start() }
    public func stop() { link.stop() }

    /// Отправить кадр. По умолчанию проставляет следующий seq. Возвращает seq.
    @discardableResult
    public func send(_ frame: CTSPFrame, autoSeq: Bool = true) -> UInt32 {
        var f = frame
        if autoSeq {
            seq &+= 1
            f.seq = seq
        }
        let bytes = CTSPEncoder.encode(f)
        link.send(bytes)
        onBytesOut?(bytes.count)
        return f.seq
    }

    private func handleBytes(_ data: Data) {
        onBytesIn?(data.count)
        do {
            for frame in try decoder.feed(data) {
                onFrame?(frame)
            }
        } catch {
            onError?("CTSP decode: \(error)")
        }
    }
}
