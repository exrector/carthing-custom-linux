// ─────────────────────────────────────────────────────────────────────────────
// ⚠️ ВРЕМЕННЫЙ ТЕСТОВЫЙ ФАЙЛ — НЕ ДЛЯ ДЕПЛОЯ НА УСТРОЙСТВО (Claude, 2026-06-18).
// Эмулятор device-side Car Thing по протоколу CTSP для loopback-проб связки
// клиент-сервер на Mac. Реального устройства не касается. См. MANIFEST.md.
// ─────────────────────────────────────────────────────────────────────────────
import Foundation
import ProtocolCore
import SessionState

/// Мок Car Thing: отвечает по CTSP как настоящее устройство должно бы.
///
/// Поведение:
///  - при подключении клиента шлёт `capabilities` и `route_state`;
///  - на `hello` отвечает `hello` (эхо timestamp → клиент меряет RTT);
///  - на `command` с payload `start_mic` начинает on-demand стрим `audio_pcm16`
///    синтетическим тоном; `stop_mic` останавливает (ресурсная политика:
///    mic НЕ течёт сам по факту коннекта);
///  - периодически шлёт `telemetry`.
public final class MockCarThingServer {
    private let link: TCPServerLink
    private let session: CTSPSession
    private let queue = DispatchQueue(label: "ctsp.mock.server")
    private var micTimer: DispatchSourceTimer?
    private var phase: Double = 0

    /// Снимок маршрута, который мок отдаёт как route_state.
    public var routeSnapshot: SessionSnapshot

    /// Готовность listener'а: фактический порт.
    public var onListening: ((UInt16) -> Void)?
    /// Лог-строки мока (для CLI/диагностики).
    public var onLog: ((String) -> Void)?

    /// Параметры синтетического mic-потока.
    public struct MicConfig {
        public var sampleRate: Int = 16_000
        public var frameMillis: Int = 20      // 20 мс ≈ 320 сэмплов
        public var toneHz: Double = 440
        public var amplitude: Double = 0.3
        public init() {}
    }
    public var micConfig = MicConfig()

    public init(port: UInt16? = nil, route: SessionSnapshot? = nil) throws {
        link = try TCPServerLink(port: port)
        session = CTSPSession(link: link)

        // Дефолтный маршрут: Play Now, iPhone как вход, локальный выход, client включён.
        if let route {
            routeSnapshot = route
        } else {
            var s = SessionSnapshot()
            s.mode = .playNow
            s.activeAudioInput = .iPhone
            s.activeOutputSink = .local
            s.clientEnabled = true
            s.sessionPhase = .connected
            routeSnapshot = s
        }

        link.onListening = { [weak self] port in self?.onListening?(port) }
        session.onConnected = { [weak self] up in self?.handleConnected(up) }
        session.onFrame = { [weak self] frame in self?.handleFrame(frame) }
        session.onError = { [weak self] msg in self?.onLog?("server error: \(msg)") }
    }

    public func start() {
        session.start()
        onLog?("mock Car Thing server запущен")
    }

    public func stop() {
        stopMic()
        session.stop()
    }

    // MARK: - Поведение

    private func handleConnected(_ up: Bool) {
        guard up else {
            onLog?("клиент отключился")
            stopMic()
            return
        }
        onLog?("клиент подключился → шлём capabilities + route_state")
        let caps = #"{"roles":["audio_input","session_peer","remote_mic_receiver"],"protocol_version":1}"#
        session.send(CTSPFrame(type: .capabilities, payload: Data(caps.utf8)))
        sendRouteState()
    }

    private func handleFrame(_ frame: CTSPFrame) {
        switch frame.type {
        case .hello:
            // Эхо для измерения RTT клиентом.
            session.send(CTSPFrame(type: .hello, payload: frame.payload))
            onLog?("hello ← эхо (\(frame.payload.count) б)")
        case .command:
            let cmd = String(data: frame.payload, encoding: .utf8) ?? ""
            handleCommand(cmd)
        default:
            break
        }
    }

    private func handleCommand(_ cmd: String) {
        onLog?("команда: \(cmd)")
        switch cmd {
        case "start_mic":
            startMic()
        case "stop_mic":
            stopMic()
        case "route":
            sendRouteState()
        default:
            session.send(CTSPFrame(type: .error, payload: Data("unknown command: \(cmd)".utf8)))
        }
    }

    private func sendRouteState() {
        let encoder = JSONEncoder()
        guard let data = try? encoder.encode(routeSnapshot) else { return }
        session.send(CTSPFrame(type: .routeState, payload: data))
    }

    // MARK: - Синтетический mic

    private func startMic() {
        stopMic()
        routeSnapshot.micActive = true
        routeSnapshot.sessionPhase = .streamingMic
        sendRouteState()

        let samplesPerFrame = micConfig.sampleRate * micConfig.frameMillis / 1000
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: .milliseconds(micConfig.frameMillis))
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            let pcm = self.makeToneFrame(samples: samplesPerFrame)
            self.session.send(CTSPFrame(type: .audioPCM16, payload: pcm))
        }
        micTimer = timer
        timer.resume()
        onLog?("mic стрим стартовал (\(samplesPerFrame) сэмплов/кадр)")
    }

    private func stopMic() {
        guard micTimer != nil else { return }
        micTimer?.cancel()
        micTimer = nil
        routeSnapshot.micActive = false
        routeSnapshot.sessionPhase = .connected
        sendRouteState()
        onLog?("mic стрим остановлен")
    }

    /// Генерирует кадр PCM16LE с синусоидой (для проверки приёма/уровня).
    private func makeToneFrame(samples: Int) -> Data {
        var data = Data(capacity: samples * 2)
        let step = 2.0 * Double.pi * micConfig.toneHz / Double(micConfig.sampleRate)
        for _ in 0..<samples {
            let v = sin(phase) * micConfig.amplitude
            phase += step
            if phase > 2 * .pi { phase -= 2 * .pi }
            let s = Int16(max(-1.0, min(1.0, v)) * Double(Int16.max))
            data.append(UInt8(truncatingIfNeeded: Int(s)))
            data.append(UInt8(truncatingIfNeeded: Int(s) >> 8))
        }
        return data
    }
}
