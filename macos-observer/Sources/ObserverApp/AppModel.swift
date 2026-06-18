import Foundation
import Combine
import ProtocolCore
import SessionState
import DeviceRegistry
import AudioPipeline
import TransportCore

/// Лог-строка для панели наблюдения.
struct LogLine: Identifiable {
    let id = UUID()
    let time: Date
    let text: String
}

/// Центральная observable-модель observer-приложения.
///
/// Сводит события `TransportCore` в `SessionSnapshot` + `TransportMetrics`,
/// кормит `AudioPipeline`, держит лог. Всё на main — CoreBluetooth callbacks
/// тоже на main, поэтому без дополнительной синхронизации.
@MainActor
final class AppModel: ObservableObject {
    @Published var snapshot = SessionSnapshot()
    @Published var metrics = TransportMetrics()
    @Published var discovered: [DiscoveredPeripheral] = []
    @Published var endpoints: [Endpoint] = []
    @Published var log: [LogLine] = []
    @Published var connectedEndpointID: String?
    @Published var micLevel: Double = 0

    private let transport = TransportCore()
    private let registry = DeviceRegistry()
    private let audio = AudioPipeline()
    private let accumulator = MetricsAccumulator()

    private var discoveredByID: [String: DiscoveredPeripheral] = [:]
    private var metricsTimer: Timer?
    private var helloSentAt: Date?

    private let maxLogLines = 500

    /// Единая папка для ВСЕХ runtime-артефактов (diagnostic bundle, WAV).
    /// Держим внутри своей папки проекта, чтобы не мусорить в репо Codex и
    /// не плодить файлы по системе. Переопределяется env `CARTHING_OBSERVER_ARTIFACTS`.
    let artifactsDir: URL = AppModel.resolveArtifactsDir()

    private static func resolveArtifactsDir() -> URL {
        let fm = FileManager.default
        let dir: URL
        if let override = ProcessInfo.processInfo.environment["CARTHING_OBSERVER_ARTIFACTS"] {
            dir = URL(fileURLWithPath: override, isDirectory: true)
        } else {
            // Дефолт — Application Support/CarThingObserver/artifacts (своя песочница).
            let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
                ?? fm.temporaryDirectory
            dir = base
                .appendingPathComponent("CarThingObserver", isDirectory: true)
                .appendingPathComponent("artifacts", isDirectory: true)
        }
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    init() {
        transport.onEvent = { [weak self] event in
            self?.handle(event)
        }
        endpoints = registry.allSorted
        startMetricsTimer()
        appendLog("observer запущен")
    }

    // MARK: - User actions

    func startScan() {
        discovered.removeAll()
        discoveredByID.removeAll()
        transport.startScan()
    }

    func stopScan() { transport.stopScan() }

    func connect(_ id: String) {
        // Создаём/обновляем endpoint в реестре при попытке подключения.
        if let d = discoveredByID[id] {
            let ep = registry.resolveByBluetooth(identifier: id, displayName: d.name)
            registry.update(id: ep.id) { $0.lastSeen = Date() }
            endpoints = registry.allSorted
        }
        transport.connect(peripheralID: id)
    }

    func disconnect() {
        transport.disconnect()
        connectedEndpointID = nil
    }

    /// Client ON/OFF — только session/client plane (не трогает audio route).
    func setClientEnabled(_ enabled: Bool) {
        transport.setClientEnabled(enabled)
        snapshot.clientEnabled = enabled
        if enabled {
            snapshot.sessionPhase = snapshot.transportPhase == .l2capOpen ? .connected : .idle
        } else {
            snapshot.sessionPhase = .off
            snapshot.micActive = false
            micLevel = 0
        }
        if let id = connectedEndpointID {
            registry.update(id: id) { $0.policy.sessionEnabled = enabled }
        }
    }

    /// Отправить hello и засечь RTT (единичное рукопожатие, не polling).
    func sendHello() {
        helloSentAt = Date()
        let payload = Data("\(Date().timeIntervalSince1970)".utf8)
        transport.send(CTSPFrame(type: .hello, payload: payload))
    }

    /// Тогглить запись debug WAV.
    func toggleRecording() {
        if audio.isRecording {
            if let url = audio.stopRecording() {
                appendLog("WAV сохранён: \(url.lastPathComponent)")
            }
        } else {
            let stamp = ISO8601DateFormatter().string(from: Date())
                .replacingOccurrences(of: ":", with: "-")
            let url = artifactsDir.appendingPathComponent("carthing-mic-\(stamp).wav")
            if let saved = try? audio.startRecording(to: url) {
                appendLog("WAV запись → \(saved.lastPathComponent)")
            }
        }
    }

    var isRecording: Bool { audio.isRecording }

    // MARK: - Event handling

    private func handle(_ event: TransportEvent) {
        switch event {
        case .phaseChanged(let phase):
            snapshot.transportPhase = phase
        case .discovered(let p):
            discoveredByID[p.id] = p
            discovered = discoveredByID.values.sorted { $0.rssi > $1.rssi }
        case .bootstrap(let version, let endpointID, let psm, _):
            appendLog("bootstrap: v=\(version.map(String.init) ?? "?") id=\(endpointID ?? "?") psm=\(psm.map(String.init) ?? "?")")
            if let id = connectedEndpointID ?? endpointID, let psm {
                registry.update(id: id) { $0.lastKnownPSM = psm }
            }
        case .l2capOpened(let psm):
            snapshot.sessionPhase = snapshot.clientEnabled ? .connected : .idle
            appendLog("L2CAP CoC psm=\(psm) открыт")
            sendHello()
        case .l2capClosed:
            snapshot.sessionPhase = snapshot.clientEnabled ? .idle : .off
        case .bytesIn(let n):
            accumulator.recordIncoming(bytes: n, frames: [])
        case .bytesOut(let n):
            accumulator.recordOutgoing(bytes: n)
        case .frame(let frame):
            handleFrame(frame)
        case .error(let msg):
            snapshot.lastError = msg
            appendLog("ОШИБКА: \(msg)")
        case .log(let msg):
            appendLog(msg)
        }
        metrics = accumulator.metrics
    }

    private func handleFrame(_ frame: CTSPFrame) {
        accumulator.recordIncoming(bytes: 0, frames: [frame])

        switch frame.type {
        case .hello:
            if let sentAt = helloSentAt {
                let rtt = Date().timeIntervalSince(sentAt) * 1000
                accumulator.setLatency(rtt)
                helloSentAt = nil
            }
        case .audioPCM16:
            snapshot.micActive = true
            snapshot.sessionPhase = .streamingMic
            audio.ingest(frame.payload)
            micLevel = audio.lastRMS
        case .routeState:
            applyRouteState(frame.payload)
        case .status:
            appendLog("status: \(frame.payload.count) байт")
        case .error:
            let text = String(data: frame.payload, encoding: .utf8) ?? "?"
            snapshot.lastError = text
            appendLog("device error: \(text)")
        default:
            break
        }
        metrics = accumulator.metrics
    }

    /// Применить route_state, если устройство шлёт JSON-снимок RouteGraph.
    private func applyRouteState(_ payload: Data) {
        guard let decoded = try? JSONDecoder().decode(SessionSnapshot.self, from: payload)
        else { return }
        // Транспортную фазу не перетираем — она наша, локальная.
        var s = decoded
        s.transportPhase = snapshot.transportPhase
        snapshot = s
    }

    // MARK: - Diagnostics

    /// Собрать diagnostic bundle (папку) и вернуть URL. Без облака, всё локально.
    func saveDiagnosticBundle() -> URL? {
        let stamp = ISO8601DateFormatter().string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
        let dir = artifactsDir.appendingPathComponent("carthing-diag-\(stamp)", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

            let snapData = try encoder.encode(snapshot)
            try snapData.write(to: dir.appendingPathComponent("session.json"))

            let metricsData = try encoder.encode(metrics)
            try metricsData.write(to: dir.appendingPathComponent("metrics.json"))

            let logText = log.map { "\(iso($0.time))  \($0.text)" }.joined(separator: "\n")
            try logText.data(using: .utf8)?.write(to: dir.appendingPathComponent("log.txt"))

            // Финализировать активную запись и подложить WAV.
            if let wav = audio.stopRecording() {
                let dest = dir.appendingPathComponent(wav.lastPathComponent)
                try? FileManager.default.copyItem(at: wav, to: dest)
            }
            appendLog("diagnostic bundle → \(dir.path)")
            return dir
        } catch {
            appendLog("ОШИБКА bundle: \(error.localizedDescription)")
            return nil
        }
    }

    // MARK: - Helpers

    private func startMetricsTimer() {
        metricsTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.accumulator.tick()
                self.metrics = self.accumulator.metrics
                // mic считается активным, только если кадры реально шли.
                if self.metrics.framesPerSec == 0, self.snapshot.micActive {
                    self.snapshot.micActive = false
                    self.micLevel = 0
                    if self.snapshot.sessionPhase == .streamingMic {
                        self.snapshot.sessionPhase = self.snapshot.clientEnabled ? .connected : .idle
                    }
                }
            }
        }
    }

    private func appendLog(_ text: String) {
        log.append(LogLine(time: Date(), text: text))
        if log.count > maxLogLines { log.removeFirst(log.count - maxLogLines) }
    }

    private func iso(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss.SSS"
        return f.string(from: date)
    }
}
