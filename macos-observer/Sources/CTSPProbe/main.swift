// ─────────────────────────────────────────────────────────────────────────────
// ⚠️ ВРЕМЕННЫЙ ТЕСТОВЫЙ CLI — НЕ ДЛЯ ДЕПЛОЯ НА УСТРОЙСТВО (Claude, 2026-06-18).
// Проба связки клиент-сервер CTSP. Два режима:
//   swift run CTSPProbe                  — loopback на Mac (встроенный mock-сервер)
//   swift run CTSPProbe <host> <port>    — клиент к удалённому серверу (напр. устройство по usb0)
// См. macos-observer/MANIFEST.md.
// ─────────────────────────────────────────────────────────────────────────────
import Foundation
import ProtocolCore
import LinkKit
import SessionState
import AudioPipeline

let runSeconds = 4.0
let args = CommandLine.arguments

/// Прогон клиентского сценария против host:port. Завершает процесс по таймауту.
func runClient(host: String, port: UInt16, stopServer: (() -> Void)? = nil) {
    let audio = AudioPipeline()
    let accumulator = MetricsAccumulator()
    var helloSentAt: Date?
    var routeFromServer: SessionSnapshot?

    let link = TCPClientLink(host: host, port: port)
    let client = CTSPSession(link: link)

    client.onConnected = { up in
        print("  [client] \(up ? "подключён к \(host):\(port)" : "отключён")")
        if up {
            helloSentAt = Date()
            client.send(CTSPFrame(type: .hello, payload: Data("\(Date().timeIntervalSince1970)".utf8)))
        }
    }
    client.onBytesIn = { n in accumulator.recordIncoming(bytes: n, frames: []) }
    client.onBytesOut = { n in accumulator.recordOutgoing(bytes: n) }
    client.onError = { print("  [client] error: \($0)") }
    client.onFrame = { frame in
        accumulator.recordIncoming(bytes: 0, frames: [frame])
        switch frame.type {
        case .hello:
            if let t = helloSentAt {
                let rtt = Date().timeIntervalSince(t) * 1000
                accumulator.setLatency(rtt)
                print(String(format: "  [client] RTT hello = %.2f ms", rtt))
            }
        case .capabilities:
            print("  [client] capabilities: \(String(data: frame.payload, encoding: .utf8) ?? "?")")
        case .routeState:
            routeFromServer = try? JSONDecoder().decode(SessionSnapshot.self, from: frame.payload)
            if let r = routeFromServer {
                print("  [client] route_state: mode=\(r.mode) input=\(r.activeAudioInput) session=\(r.sessionPhase) mic=\(r.micActive)")
            }
        case .audioPCM16:
            audio.ingest(frame.payload)
        case .error:
            print("  [client] server error: \(String(data: frame.payload, encoding: .utf8) ?? "?")")
        default:
            break
        }
    }
    client.start()

    DispatchQueue.global().asyncAfter(deadline: .now() + 1.0) {
        print("  [client] → command start_mic")
        client.send(CTSPFrame(type: .command, payload: Data("start_mic".utf8)))
    }

    let metricsTimer = DispatchSource.makeTimerSource(queue: .global())
    metricsTimer.schedule(deadline: .now() + 1, repeating: 1)
    metricsTimer.setEventHandler {
        accumulator.tick()
        let m = accumulator.metrics
        print(String(format: "  [metrics] in=%.0f B/s out=%.0f B/s frames=%.1f/s lastType=%@ seq=%@ rms=%.3f",
                     m.bytesPerSecIn, m.bytesPerSecOut, m.framesPerSec,
                     m.lastFrameType ?? "—", m.lastSeq.map(String.init) ?? "—", audio.lastRMS))
    }
    metricsTimer.resume()

    DispatchQueue.global().asyncAfter(deadline: .now() + runSeconds) {
        client.send(CTSPFrame(type: .command, payload: Data("stop_mic".utf8)))
        metricsTimer.cancel()
        let m = accumulator.metrics
        print("=== ИТОГ ===")
        print("  всего кадров in/out: \(m.totalFramesIn)/\(m.totalFramesOut)")
        print("  всего байт in/out:   \(m.totalBytesIn)/\(m.totalBytesOut)")
        print(String(format: "  latency est: %@", m.latencyEstimateMs.map { String(format: "%.2f ms", $0) } ?? "—"))
        print(String(format: "  audio буфер: %.2f c, всего PCM: %d б", audio.bufferedSeconds, audio.totalBytes))
        print("  route получен: \(routeFromServer != nil ? "да" : "нет")")
        client.stop()
        stopServer?()
        exit(0)
    }
}

if args.count >= 3, let port = UInt16(args[2]) {
    // Режим: клиент к удалённому серверу (устройство по usb0 и т.п.).
    print("=== CTSP probe — клиент к \(args[1]):\(port) ===")
    runClient(host: args[1], port: port)
} else {
    // Режим: loopback на Mac со встроенным mock-сервером.
    print("=== CTSP loopback probe (Mac-only, без устройства) ===")
    let server = try MockCarThingServer()
    server.onLog = { print("  [server] \($0)") }
    let portReady = DispatchSemaphore(value: 0)
    var assignedPort: UInt16 = 0
    server.onListening = { port in assignedPort = port; portReady.signal() }
    server.start()
    guard portReady.wait(timeout: .now() + 3) == .success else {
        print("listener не поднялся"); exit(1)
    }
    print("  [server] слушает 127.0.0.1:\(assignedPort)")
    runClient(host: "127.0.0.1", port: assignedPort, stopServer: { server.stop() })
}

RunLoop.main.run()
