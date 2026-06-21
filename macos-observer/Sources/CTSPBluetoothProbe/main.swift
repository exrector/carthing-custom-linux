import Foundation
import AudioPipeline
import ProtocolCore
import TransportCore

final class BluetoothMicProbe {
    private let transport = TransportCore()
    private let audio = AudioPipeline()
    private let duration: TimeInterval
    private let artifactsDir: URL
    private var connected = false
    private var started = false
    private var audioFrames = 0
    private var audioBytes = 0
    private var lastReport = Date()
    private var wavURL: URL?

    init(duration: TimeInterval, artifactsDir: URL) {
        self.duration = duration
        self.artifactsDir = artifactsDir
        transport.onEvent = { [weak self] event in
            self?.handle(event)
        }
    }

    func start() {
        try? FileManager.default.createDirectory(at: artifactsDir, withIntermediateDirectories: true)
        print("bt-probe: starting scan duration=\(Int(duration))s")
    }

    private func finish(_ code: Int32) {
        if started {
            transport.send(CTSPFrame(type: .command, payload: Data("stop_mic".utf8)))
        }
        if let saved = audio.stopRecording() {
            print("bt-probe: wav=\(saved.path)")
        } else if let wavURL {
            print("bt-probe: wav_pending=\(wavURL.path)")
        }
        print("bt-probe: done frames=\(audioFrames) bytes=\(audioBytes) rms=\(String(format: "%.6f", audio.lastRMS))")
        transport.disconnect()
        exit(code)
    }

    private func handle(_ event: TransportEvent) {
        switch event {
        case .phaseChanged(let phase):
            print("bt-probe: phase=\(phase.rawValue)")
            if phase == .idle, !connected {
                transport.startScan()
            }
        case .discovered(let peripheral):
            print("bt-probe: discovered name=\"\(peripheral.name)\" id=\(peripheral.id) rssi=\(peripheral.rssi)")
            guard !connected else { return }
            connected = true
            transport.stopScan()
            transport.connect(peripheralID: peripheral.id)
        case .bootstrap(let version, let endpointID, let psm, let capabilities):
            let caps = capabilities.flatMap { String(data: $0, encoding: .utf8) } ?? ""
            print("bt-probe: bootstrap version=\(version.map(String.init) ?? "?") endpoint=\(endpointID ?? "?") psm=\(psm.map(String.init) ?? "?") caps=\(caps)")
            transport.setClientEnabled(true)
        case .l2capOpened(let psm):
            print("bt-probe: l2cap_open psm=\(psm)")
            let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
            let url = artifactsDir.appendingPathComponent("carthing-ble-mic-\(stamp).wav")
            wavURL = try? audio.startRecording(to: url)
            transport.send(CTSPFrame(type: .hello, payload: Data("\(Date().timeIntervalSince1970)".utf8)))
            started = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                print("bt-probe: command=start_mic")
                self?.transport.send(CTSPFrame(type: .command, payload: Data("start_mic".utf8)))
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + duration) { [weak self] in
                self?.finish((self?.audioFrames ?? 0) > 0 ? 0 : 2)
            }
        case .l2capClosed:
            print("bt-probe: l2cap_closed")
            if started {
                finish(3)
            }
        case .frame(let frame):
            handle(frame)
        case .error(let message):
            print("bt-probe: error=\(message)")
            if started {
                finish(4)
            }
        case .log(let message):
            print("bt-probe: log=\(message)")
        case .bytesIn, .bytesOut:
            break
        }
    }

    private func handle(_ frame: CTSPFrame) {
        switch frame.type {
        case .audioPCM16:
            audioFrames += 1
            audioBytes += frame.payload.count
            audio.ingest(frame.payload)
            let now = Date()
            if now.timeIntervalSince(lastReport) >= 1.0 {
                lastReport = now
                print("bt-probe: audio frames=\(audioFrames) bytes=\(audioBytes) rms=\(String(format: "%.6f", audio.lastRMS))")
            }
        case .hello, .status, .capabilities, .routeState:
            let text = String(data: frame.payload, encoding: .utf8) ?? "\(frame.payload.count) bytes"
            print("bt-probe: frame=\(frame.type.description) payload=\(text)")
        case .error:
            let text = String(data: frame.payload, encoding: .utf8) ?? "\(frame.payload.count) bytes"
            print("bt-probe: device_error=\(text)")
        default:
            break
        }
    }
}

let duration = TimeInterval(Int(ProcessInfo.processInfo.environment["CTSP_BT_PROBE_SECONDS"] ?? "10") ?? 10)
let dir = URL(fileURLWithPath: ProcessInfo.processInfo.environment["CTSP_BT_PROBE_ARTIFACTS"] ?? "/tmp/carthing-ble-probe", isDirectory: true)
let probe = BluetoothMicProbe(duration: duration, artifactsDir: dir)
probe.start()
RunLoop.main.run()
