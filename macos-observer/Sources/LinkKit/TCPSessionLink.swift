// ─────────────────────────────────────────────────────────────────────────────
// ВРЕМЕННЫЙ ФАЙЛ ДЛЯ ТЕСТОВ КЛИЕНТ-СЕРВЕР (Claude, 2026-06-18).
// TCP-loopback реализации SessionLink для проб связки CTSP на Mac без устройства.
// Network.framework, никаких внешних зависимостей. См. macos-observer/MANIFEST.md.
// ─────────────────────────────────────────────────────────────────────────────
import Foundation
import Network
import ProtocolCore

/// Клиентская сторона: исходящее TCP-соединение как `SessionLink`.
public final class TCPClientLink: SessionLink {
    public var onBytes: ((Data) -> Void)?
    public var onStateChange: ((Bool) -> Void)?
    public var onError: ((String) -> Void)?

    private let connection: NWConnection
    private let queue = DispatchQueue(label: "ctsp.tcp.client")

    public init(host: String, port: UInt16) {
        connection = NWConnection(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port)!,
            using: .tcp
        )
    }

    public func start() {
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                self?.onStateChange?(true)
                self?.receive()
            case .failed(let err):
                self?.onError?("tcp client failed: \(err)")
                self?.onStateChange?(false)
            case .cancelled:
                self?.onStateChange?(false)
            default:
                break
            }
        }
        connection.start(queue: queue)
    }

    public func send(_ data: Data) {
        connection.send(content: data, completion: .contentProcessed { [weak self] err in
            if let err { self?.onError?("tcp client send: \(err)") }
        })
    }

    public func stop() {
        connection.cancel()
    }

    private func receive() {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) {
            [weak self] data, _, isComplete, err in
            if let data, !data.isEmpty { self?.onBytes?(data) }
            if let err { self?.onError?("tcp client recv: \(err)"); return }
            if isComplete { self?.onStateChange?(false); return }
            self?.receive()
        }
    }
}

/// Серверная сторона: слушает порт, принимает ОДНО соединение и представляет
/// его как `SessionLink`. Достаточно для loopback-проб 1:1.
public final class TCPServerLink: SessionLink {
    public var onBytes: ((Data) -> Void)?
    public var onStateChange: ((Bool) -> Void)?
    public var onError: ((String) -> Void)?

    /// Вызывается, когда listener готов; отдаёт фактический (возможно эфемерный) порт.
    public var onListening: ((UInt16) -> Void)?

    private let listener: NWListener
    private var connection: NWConnection?
    private let queue = DispatchQueue(label: "ctsp.tcp.server")

    /// - Parameter port: 0/nil → эфемерный порт (узнать через `onListening`).
    public init(port: UInt16? = nil) throws {
        if let port, port != 0 {
            listener = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: port)!)
        } else {
            listener = try NWListener(using: .tcp)
        }
    }

    public func start() {
        listener.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                if let p = self?.listener.port?.rawValue { self?.onListening?(p) }
            case .failed(let err):
                self?.onError?("tcp listener failed: \(err)")
            default:
                break
            }
        }
        listener.newConnectionHandler = { [weak self] conn in
            guard let self else { return }
            // Берём только первое соединение; остальные отклоняем.
            if self.connection != nil { conn.cancel(); return }
            self.connection = conn
            conn.stateUpdateHandler = { [weak self] state in
                switch state {
                case .ready:
                    self?.onStateChange?(true)
                    self?.receive()
                case .failed(let err):
                    self?.onError?("tcp server conn failed: \(err)")
                    self?.onStateChange?(false)
                case .cancelled:
                    self?.onStateChange?(false)
                default:
                    break
                }
            }
            conn.start(queue: self.queue)
        }
        listener.start(queue: queue)
    }

    public func send(_ data: Data) {
        connection?.send(content: data, completion: .contentProcessed { [weak self] err in
            if let err { self?.onError?("tcp server send: \(err)") }
        })
    }

    public func stop() {
        connection?.cancel()
        listener.cancel()
    }

    private func receive() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 65536) {
            [weak self] data, _, isComplete, err in
            if let data, !data.isEmpty { self?.onBytes?(data) }
            if let err { self?.onError?("tcp server recv: \(err)"); return }
            if isComplete { self?.onStateChange?(false); return }
            self?.receive()
        }
    }
}
