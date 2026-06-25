import AVFoundation
import Foundation
import Network
import ProtocolCore
import TransportCore

final class CarThingBTAudioCap {
    private let transport = TransportCore()
    private let output = FileHandle.standardOutput
    private let engine = AVAudioEngine()
    private let mixer: AVAudioMixerNode
    private var playerNode: AVAudioPlayerNode?
    private var connected = false
    private var streaming = false
    private var frames = 0
    private var lastReport = Date()
    private var scanRetryTimer: Timer?
    private var signalSources: [DispatchSourceSignal] = []
    private let headless = ProcessInfo.processInfo.environment["CARTHING_BT_HEADLESS"] == "1"
    // TCP-режим: агент живёт под launchd (там CB/TCC работают), а потребитель (bt_whisper)
    // цепляется по локальному TCP — отдаём аудио, принимаем команды (text ...).
    private let tcpPort = ProcessInfo.processInfo.environment["CARTHING_BT_TCP_PORT"].flatMap { UInt16($0) }
    private var listener: NWListener?
    private var conns: [NWConnection] = []        // доступ только с main
    private var rxText = Data()
    private let netQueue = DispatchQueue(label: "carthing.bt.tcp")

    init() {
        mixer = engine.mainMixerNode
        transport.onEvent = { [weak self] event in
            self?.handle(event)
        }
    }

    func start() {
        setvbuf(stderr, nil, _IONBF, 0)   // без буферизации: видеть логи под launchd (stderr=файл)
        if tcpPort == nil {
            var sampleRate = Int32(16_000).littleEndian
            output.write(Data(bytes: &sampleRate, count: 4))   // в TCP-режиме SR шлём по коннекту
        }

        engine.connect(mixer, to: engine.outputNode, format: nil)
        do {
            try engine.start()
        } catch {
            fputs("carthing-bt-audiocap: playback engine error: \(error)\n", stderr)
        }

        // ВСЕГДА: без source main RunLoop.run() возвращается сразу → процесс выходит ещё
        // до того, как CBCentralManager(queue:.main) включится. Под launchd что-то держало
        // RunLoop, но в subprocess/foreground — нет. Явный keepalive-Timer надёжен везде.
        Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { _ in }
        if let p = tcpPort {
            installSignalHandlers()
            startTCP(p)               // аудио + команды через локальный TCP, stdin не нужен
        } else if headless {
            // Демон-«липучка»: stdin не читаем (под LaunchAgent stdin=/dev/null → мгновенный
            // EOF → exit(0); это и был флап). Реконнект — внутренний (scanRetry/l2capClosed).
            // Чистый дисконнект по SIGTERM, чтобы устройство не залипало.
            installSignalHandlers()
            fputs("carthing-bt-audiocap: headless link-keeper (stdin reader disabled)\n", stderr)
        } else {
            installCommandReader()
        }
        fputs("carthing-bt-audiocap: ready sample_rate=16000 source=bluetooth_ctsp\n", stderr)
    }

    private func installSignalHandlers() {
        for sig in [SIGTERM, SIGINT] {
            signal(sig, SIG_IGN)
            let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            src.setEventHandler { [weak self] in
                fputs("carthing-bt-audiocap: signal -> clean disconnect\n", stderr)
                self?.stopMic()
                self?.transport.disconnect()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { exit(0) }
            }
            src.resume()
            signalSources.append(src)
        }
    }

    private func handle(_ event: TransportEvent) {
        switch event {
        case .phaseChanged(let phase):
            fputs("carthing-bt-audiocap: phase=\(phase.rawValue)\n", stderr)
            if phase == .idle, !connected {
                transport.startScan()
            } else if phase == .scanning {
                scheduleScanRetry()
            }
        case .discovered(let peripheral):
            guard !connected else { return }
            connected = true
            stopScanRetry()
            fputs("carthing-bt-audiocap: discovered name=\"\(peripheral.name)\" rssi=\(peripheral.rssi)\n", stderr)
            transport.stopScan()
            transport.connect(peripheralID: peripheral.id)
        case .bootstrap(let version, let endpointID, let psm, _):
            fputs(
                "carthing-bt-audiocap: bootstrap version=\(version.map(String.init) ?? "?") endpoint=\(endpointID ?? "?") psm=\(psm.map(String.init) ?? "?")\n",
                stderr
            )
            transport.setClientEnabled(true)
        case .l2capOpened(let psm):
            fputs("carthing-bt-audiocap: l2cap_open psm=\(psm)\n", stderr)
            transport.send(CTSPFrame(type: .hello, payload: Data("\(Date().timeIntervalSince1970)".utf8)))
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                fputs("carthing-bt-audiocap: command=start_mic\n", stderr)
                self?.transport.send(CTSPFrame(type: .command, payload: Data("start_mic".utf8)))
            }
        case .l2capClosed:
            streaming = false
            connected = false
            stopScanRetry()
            fputs("carthing-bt-audiocap: l2cap_closed\n", stderr)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                self?.transport.startScan()
            }
        case .frame(let frame):
            handle(frame)
        case .error(let message):
            fputs("carthing-bt-audiocap: error=\(message)\n", stderr)
        case .log(let message):
            fputs("carthing-bt-audiocap: \(message)\n", stderr)
        case .bytesIn, .bytesOut:
            break
        }
    }

    private func scheduleScanRetry() {
        guard scanRetryTimer == nil else { return }
        scanRetryTimer = Timer.scheduledTimer(withTimeInterval: 8.0, repeats: true) { [weak self] _ in
            guard let self, !self.connected else { return }
            fputs("carthing-bt-audiocap: scan retry\n", stderr)
            self.transport.stopScan()
            self.transport.startScan()
        }
    }

    private func stopScanRetry() {
        scanRetryTimer?.invalidate()
        scanRetryTimer = nil
    }

    private func handle(_ frame: CTSPFrame) {
        switch frame.type {
        case .audioPCM16:
            writeFloat32PCM(from: frame.payload)
            frames += 1
            let now = Date()
            if now.timeIntervalSince(lastReport) >= 2.0 {
                lastReport = now
                fputs("carthing-bt-audiocap: audio_frames=\(frames)\n", stderr)
            }
        case .status:
            let text = String(data: frame.payload, encoding: .utf8) ?? "\(frame.payload.count) bytes"
            if !streaming, text.contains("\"streaming_mic\":[\"") {
                streaming = true
                fputs("carthing-bt-audiocap: streaming_mic=on\n", stderr)
            }
        case .error:
            let text = String(data: frame.payload, encoding: .utf8) ?? "\(frame.payload.count) bytes"
            fputs("carthing-bt-audiocap: device_error=\(text)\n", stderr)
        default:
            break
        }
    }

    private func writeFloat32PCM(from pcm16: Data) {
        let sampleCount = pcm16.count / 2
        guard sampleCount > 0 else { return }
        var floats = [Float]()
        floats.reserveCapacity(sampleCount)
        for index in 0..<sampleCount {
            let offset = index * 2
            let lo = UInt16(pcm16[offset])
            let hi = UInt16(pcm16[offset + 1]) << 8
            let sample = Int16(bitPattern: hi | lo)
            floats.append(max(-1.0, min(1.0, Float(sample) / 32768.0)))
        }
        emitAudio(Data(bytes: floats, count: floats.count * MemoryLayout<Float>.size))
    }

    // MARK: - Аудио-синк + локальный TCP-сервер (для bt_whisper)

    private func emitAudio(_ data: Data) {
        if tcpPort != nil {
            for c in conns { c.send(content: data, completion: .idempotent) }
        } else {
            output.write(data)
        }
    }

    private func startTCP(_ port: UInt16) {
        let params = NWParameters.tcp
        params.allowLocalEndpointReuse = true
        guard let l = try? NWListener(using: params, on: NWEndpoint.Port(rawValue: port)!) else {
            fputs("carthing-bt-audiocap: TCP listen failed port=\(port)\n", stderr)
            return
        }
        listener = l
        l.newConnectionHandler = { [weak self] conn in self?.acceptConn(conn) }
        l.start(queue: netQueue)
        fputs("carthing-bt-audiocap: TCP server on 127.0.0.1:\(port)\n", stderr)
    }

    private func acceptConn(_ conn: NWConnection) {
        conn.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                var sr = Int32(16_000).littleEndian
                conn.send(content: Data(bytes: &sr, count: 4), completion: .idempotent)
                DispatchQueue.main.async { self?.conns.append(conn) }
                self?.receiveText(conn)
                fputs("carthing-bt-audiocap: TCP client connected\n", stderr)
            case .failed, .cancelled:
                self?.removeConn(conn)
            default:
                break
            }
        }
        conn.start(queue: netQueue)
    }

    private func removeConn(_ conn: NWConnection) {
        DispatchQueue.main.async { [weak self] in
            self?.conns.removeAll { $0 === conn }
        }
    }

    private func receiveText(_ conn: NWConnection) {
        conn.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self] data, _, isComplete, error in
            if let data, !data.isEmpty {
                DispatchQueue.main.async { self?.ingestText(data) }
            }
            if isComplete || error != nil {
                self?.removeConn(conn)
                return
            }
            self?.receiveText(conn)
        }
    }

    private func ingestText(_ data: Data) {
        rxText.append(data)
        while let nl = rxText.firstIndex(of: 0x0A) {
            let line = Data(rxText[rxText.startIndex..<nl])
            rxText.removeSubrange(rxText.startIndex...nl)
            if let s = String(data: line, encoding: .utf8) {
                handleCommand(s.trimmingCharacters(in: .whitespacesAndNewlines))
            }
        }
    }

    private func installCommandReader() {
        let stdinHandle = FileHandle.standardInput
        NotificationCenter.default.addObserver(
            forName: .NSFileHandleDataAvailable,
            object: stdinHandle,
            queue: .main
        ) { [weak self] _ in
            let data = stdinHandle.availableData
            guard !data.isEmpty, let line = String(data: data, encoding: .utf8) else {
                self?.stopMic()
                exit(0)
            }
            self?.handleCommand(line.trimmingCharacters(in: .whitespacesAndNewlines))
            stdinHandle.waitForDataInBackgroundAndNotify()
        }
        stdinHandle.waitForDataInBackgroundAndNotify()
    }

    private func handleCommand(_ command: String) {
        if command.hasPrefix("play ") {
            play(String(command.dropFirst(5)))
        } else if command == "stop" {
            playerNode?.stop()
        } else if command.hasPrefix("text ") {
            // Текст распознавания вниз на экран устройства: T_COMMAND "text:<utf8>".
            let txt = String(command.dropFirst(5))
            transport.send(CTSPFrame(type: .command, payload: Data(("text:" + txt).utf8)))
        }
    }

    private func play(_ path: String) {
        let url = URL(fileURLWithPath: path)
        guard let file = try? AVAudioFile(forReading: url) else {
            fputs("carthing-bt-audiocap: cannot open \(path)\n", stderr)
            return
        }
        playerNode?.stop()
        if let playerNode {
            engine.detach(playerNode)
        }
        let node = AVAudioPlayerNode()
        engine.attach(node)
        engine.connect(node, to: mixer, format: file.processingFormat)
        node.scheduleFile(file, at: nil, completionCallbackType: .dataPlayedBack) { _ in
            fputs("carthing-bt-audiocap: done\n", stderr)
        }
        node.play()
        playerNode = node
    }

    private func stopMic() {
        if streaming {
            transport.send(CTSPFrame(type: .command, payload: Data("stop_mic".utf8)))
        }
    }
}

let cap = CarThingBTAudioCap()
cap.start()
// run() может вернуться сразу, если в RunLoop нет input-source (только Timer не всегда
// держит). Цикл run(until:) гарантирует, что процесс не выйдет ни в каком контексте.
while true {
    RunLoop.main.run(until: Date(timeIntervalSinceNow: 3600))
}
