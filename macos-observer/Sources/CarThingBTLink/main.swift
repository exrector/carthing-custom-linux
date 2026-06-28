import AVFoundation
import AppKit
import Foundation
import Network
import ProtocolCore
import TransportCore

private final class TCPAudioClient {
    let connection: NWConnection
    var sendInFlight = false

    init(_ connection: NWConnection) {
        self.connection = connection
    }
}

private struct AudioLatencySample {
    let sequence: UInt32
    let dspMs: Double
    let devicePipelineMs: Double
    let bluetoothMs: Double
    let captureToMacMs: Double
    let ctspRTTMs: Double?
}

private func readUInt64BE(_ data: Data, at offset: Int) -> UInt64? {
    guard offset >= 0, data.count >= offset + 8 else { return nil }
    var value: UInt64 = 0
    for byte in data[offset..<(offset + 8)] {
        value = (value << 8) | UInt64(byte)
    }
    return value
}

private func readUInt32BE(_ data: Data, at offset: Int) -> UInt32? {
    guard offset >= 0, data.count >= offset + 4 else { return nil }
    var value: UInt32 = 0
    for byte in data[offset..<(offset + 4)] {
        value = (value << 8) | UInt32(byte)
    }
    return value
}

private func bigEndianData(_ value: UInt64) -> Data {
    var bigEndian = value.bigEndian
    return Data(bytes: &bigEndian, count: MemoryLayout<UInt64>.size)
}

final class CarThingBTLink {
    private let transport = TransportCore()
    private let output = FileHandle.standardOutput
    private var engine: AVAudioEngine?
    private var mixer: AVAudioMixerNode?
    private var playerNode: AVAudioPlayerNode?
    private var connected = false
    private var streaming = false
    private var frames = 0
    private var lastReport = Date()
    private var scanRetryTimer: Timer?
    private var latencyProbeTimer: Timer?
    private var reconnectWorkItem: DispatchWorkItem?
    private var signalSources: [DispatchSourceSignal] = []
    private var shuttingDown = false
    private let headless =
        ProcessInfo.processInfo.environment["CARTHING_BT_HEADLESS"] == "1"
        || Bundle.main.bundleIdentifier == "com.exrector.carthing.btlink"
    // TCP-режим: агент живёт под launchd (там CB/TCC работают), а потребитель (bt_whisper)
    // цепляется по локальному TCP — отдаём аудио, принимаем команды (text ...).
    private let tcpPort = ProcessInfo.processInfo.environment["CARTHING_BT_TCP_PORT"].flatMap { UInt16($0) }
    private let eventPort = ProcessInfo.processInfo.environment["CARTHING_BT_EVENT_PORT"].flatMap { UInt16($0) }
    private var listener: NWListener?
    private var eventListener: NWListener?
    private var clients: [TCPAudioClient] = []    // доступ только с main
    private var eventClients: [NWConnection] = [] // доступ только с main
    private var rxText = Data()
    private var latencyProbeSequence: UInt32 = 0
    private var clockOffsetDeviceMinusMacNs: Double?
    private var latestCTSPRTTMs: Double?
    private var latestAudioLatency: AudioLatencySample?
    private var latestAudioReceivedNs: UInt64?
    private var linkLostNs: UInt64?
    private var linkOpenedNs: UInt64?
    private var firstAudioReceived = false
    private var lastPartialSentAt = Date.distantPast
    private var lastPartialText = ""
    private let netQueue = DispatchQueue(label: "carthing.bt.tcp")
    private lazy var speechPipeline = AppleSpeechPipeline { [weak self] text, isFinal in
        DispatchQueue.main.async {
            self?.broadcastSpeech(text: text, isFinal: isFinal)
        }
    }

    init() {
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

        if tcpPort == nil, !startPlaybackEngine() {
            fputs("carthing-btlink: playback engine unavailable\n", stderr)
        }

        // ВСЕГДА: без source main RunLoop.run() возвращается сразу → процесс выходит ещё
        // до того, как CBCentralManager(queue:.main) включится. Под launchd что-то держало
        // RunLoop, но в subprocess/foreground — нет. Явный keepalive-Timer надёжен везде.
        Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { _ in }
        if let p = tcpPort {
            installSignalHandlers()
            startTCP(p)               // аудио + команды через локальный TCP, stdin не нужен
            if let eventPort {
                startEventTCP(eventPort)
                speechPipeline.start()
            }
        } else if headless {
            // Демон-«липучка»: stdin не читаем (под LaunchAgent stdin=/dev/null → мгновенный
            // EOF → exit(0); это и был флап). Реконнект — внутренний (scanRetry/l2capClosed).
            // Чистый дисконнект по SIGTERM, чтобы устройство не залипало.
            installSignalHandlers()
            fputs("carthing-btlink: headless link-keeper (stdin reader disabled)\n", stderr)
        } else {
            installCommandReader()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            guard let self, !self.connected, !self.shuttingDown else { return }
            self.transport.startScan()
        }
        fputs("carthing-btlink: ready sample_rate=16000 source=bluetooth_ctsp\n", stderr)
    }

    private func installSignalHandlers() {
        for sig in [SIGTERM, SIGINT] {
            signal(sig, SIG_IGN)
            let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            src.setEventHandler { [weak self] in
                self?.shuttingDown = true
                self?.stopScanRetry()
                self?.stopLatencyProbes()
                self?.cancelReconnect()
                self?.transport.stopScan()
                fputs("carthing-btlink: signal -> clean disconnect\n", stderr)
                self?.stopMic()
                self?.transport.send(
                    CTSPFrame(type: .command, payload: Data("disconnect".utf8))
                )
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                    self?.transport.disconnect()
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { exit(0) }
            }
            src.resume()
            signalSources.append(src)
        }
    }

    private func handle(_ event: TransportEvent) {
        switch event {
        case .phaseChanged(let phase):
            fputs("carthing-btlink: phase=\(phase.rawValue)\n", stderr)
            if phase == .idle, !connected, !shuttingDown {
                transport.startScan()
            } else if phase == .scanning {
                scheduleScanRetry()
            } else if phase == .failed, !shuttingDown {
                connected = false
                stopScanRetry()
                transport.disconnect()
                scheduleReconnect()
            }
        case .discovered(let peripheral):
            guard !connected, !shuttingDown else { return }
            connected = true
            stopScanRetry()
            cancelReconnect()
            fputs("carthing-btlink: discovered name=\"\(peripheral.name)\" rssi=\(peripheral.rssi)\n", stderr)
            transport.stopScan()
            transport.connect(peripheralID: peripheral.id)
        case .bootstrap(let version, let endpointID, let psm, _):
            fputs(
                "carthing-btlink: bootstrap version=\(version.map(String.init) ?? "?") endpoint=\(endpointID ?? "?") psm=\(psm.map(String.init) ?? "?")\n",
                stderr
            )
            transport.setClientEnabled(true)
        case .l2capOpened(let psm):
            fputs("carthing-btlink: l2cap_open psm=\(psm)\n", stderr)
            let now = DispatchTime.now().uptimeNanoseconds
            linkOpenedNs = now
            firstAudioReceived = false
            clockOffsetDeviceMinusMacNs = nil
            latestCTSPRTTMs = nil
            latestAudioLatency = nil
            latestAudioReceivedNs = nil
            lastPartialText = ""
            lastPartialSentAt = .distantPast
            if let lost = linkLostNs {
                fputs(
                    "carthing-btlink: reconnect_l2cap_ms=\(Self.ms(now, since: lost))\n",
                    stderr
                )
            }
            startLatencyProbes()
            transport.send(CTSPFrame(type: .hello, payload: Data("\(Date().timeIntervalSince1970)".utf8)))
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                fputs("carthing-btlink: command=start_mic\n", stderr)
                self?.transport.send(CTSPFrame(type: .command, payload: Data("start_mic".utf8)))
            }
        case .l2capClosed:
            streaming = false
            connected = false
            linkLostNs = DispatchTime.now().uptimeNanoseconds
            linkOpenedNs = nil
            stopLatencyProbes()
            stopScanRetry()
            fputs("carthing-btlink: l2cap_closed\n", stderr)
            if !shuttingDown {
                transport.disconnect()
            }
            scheduleReconnect()
        case .frame(let frame):
            handle(frame)
        case .error(let message):
            fputs("carthing-btlink: error=\(message)\n", stderr)
        case .log(let message):
            fputs("carthing-btlink: \(message)\n", stderr)
        case .bytesIn, .bytesOut:
            break
        }
    }

    private func scheduleScanRetry() {
        guard scanRetryTimer == nil else { return }
        scanRetryTimer = Timer.scheduledTimer(withTimeInterval: 8.0, repeats: true) { [weak self] _ in
            guard let self, !self.connected, !self.shuttingDown else { return }
            fputs("carthing-btlink: scan retry\n", stderr)
            self.transport.stopScan()
            self.transport.startScan()
        }
    }

    private func stopScanRetry() {
        scanRetryTimer?.invalidate()
        scanRetryTimer = nil
    }

    private func scheduleReconnect() {
        guard !shuttingDown, reconnectWorkItem == nil else { return }
        let workItem = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.reconnectWorkItem = nil
            guard !self.connected, !self.shuttingDown else { return }
            self.transport.startScan()
        }
        reconnectWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0, execute: workItem)
    }

    private func cancelReconnect() {
        reconnectWorkItem?.cancel()
        reconnectWorkItem = nil
    }

    private func handle(_ frame: CTSPFrame) {
        switch frame.type {
        case .audioPCM16:
            writeFloat32PCM(from: frame.payload)
            reportAudioFrame()
        case .audioIMAADPCM:
            writeFloat32ADPCM(from: frame)
            reportAudioFrame()
        case .latencyProbe:
            handleLatencyProbe(frame)
        case .status:
            let text = String(data: frame.payload, encoding: .utf8) ?? "\(frame.payload.count) bytes"
            if !streaming, text.contains("\"streaming_mic\":[\"") {
                streaming = true
                fputs("carthing-btlink: streaming_mic=on\n", stderr)
            }
        case .error:
            let text = String(data: frame.payload, encoding: .utf8) ?? "\(frame.payload.count) bytes"
            fputs("carthing-btlink: device_error=\(text)\n", stderr)
        default:
            break
        }
    }

    private func reportAudioFrame() {
        frames += 1
        let now = Date()
        if !firstAudioReceived {
            firstAudioReceived = true
            if let opened = linkOpenedNs {
                let elapsed = Self.ms(DispatchTime.now().uptimeNanoseconds, since: opened)
                fputs("carthing-btlink: first_audio_after_l2cap_ms=\(elapsed)\n", stderr)
            }
        }
        if now.timeIntervalSince(lastReport) >= 2.0 {
            lastReport = now
            if let latency = latestAudioLatency {
                fputs(
                    String(
                        format: "carthing-btlink: audio_frames=%d seq=%u dsp_ms=%.1f device_ms=%.1f bluetooth_ms=%.1f capture_to_mac_ms=%.1f ctsp_rtt_ms=%.1f\n",
                        frames,
                        latency.sequence,
                        latency.dspMs,
                        latency.devicePipelineMs,
                        latency.bluetoothMs,
                        latency.captureToMacMs,
                        latency.ctspRTTMs ?? -1
                    ),
                    stderr
                )
            } else {
                fputs("carthing-btlink: audio_frames=\(frames)\n", stderr)
            }
        }
    }

    private func writeFloat32PCM(from pcm16: Data) {
        let sampleCount = pcm16.count / 2
        guard sampleCount > 0 else { return }
        var samples = [Int16]()
        samples.reserveCapacity(sampleCount)
        var floats = [Float]()
        floats.reserveCapacity(sampleCount)
        for index in 0..<sampleCount {
            let offset = index * 2
            let lo = UInt16(pcm16[offset])
            let hi = UInt16(pcm16[offset + 1]) << 8
            let sample = Int16(bitPattern: hi | lo)
            samples.append(sample)
            floats.append(max(-1.0, min(1.0, Float(sample) / 32768.0)))
        }
        speechPipeline.append(samples: samples, sampleRate: 16_000)
        emitAudio(Data(bytes: floats, count: floats.count * MemoryLayout<Float>.size))
    }

    private static let imaIndexTable = [
        -1, -1, -1, -1, 2, 4, 6, 8,
        -1, -1, -1, -1, 2, 4, 6, 8,
    ]
    private static let imaStepTable = [
        7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
        34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
        143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
        494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
        1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
        4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
        11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
        27086, 29794, 32767,
    ]

    private func writeFloat32ADPCM(from frame: CTSPFrame) {
        let receivedNs = DispatchTime.now().uptimeNanoseconds
        latestAudioReceivedNs = receivedNs
        var data = frame.payload
        if frame.flags & CTSPFrame.Flag.audioTiming != 0,
           let captureEndNs = readUInt64BE(data, at: 0),
           let deviceSendNs = readUInt64BE(data, at: 8),
           let dspUs = readUInt32BE(data, at: 16),
           data.count >= 20,
           deviceSendNs >= captureEndNs,
           let offset = clockOffsetDeviceMinusMacNs {
            let captureMacNs = Double(captureEndNs) - offset
            let sendMacNs = Double(deviceSendNs) - offset
            let receiveMacNs = Double(receivedNs)
            latestAudioLatency = AudioLatencySample(
                sequence: frame.seq,
                dspMs: Double(dspUs) / 1000,
                devicePipelineMs: max(0, Double(deviceSendNs - captureEndNs) / 1_000_000),
                bluetoothMs: max(0, (receiveMacNs - sendMacNs) / 1_000_000),
                captureToMacMs: max(0, (receiveMacNs - captureMacNs) / 1_000_000),
                ctspRTTMs: latestCTSPRTTMs
            )
            data = Data(data.dropFirst(20))
        }
        guard data.count >= 4 else { return }
        var predictor = Int(Int16(bitPattern: UInt16(data[0]) | (UInt16(data[1]) << 8)))
        var index = max(0, min(88, Int(data[2])))
        var samples: [Int16] = []
        samples.reserveCapacity((data.count - 4) * 2)
        var floats: [Float] = []
        floats.reserveCapacity((data.count - 4) * 4)
        for byte in data.dropFirst(4) {
            for code in [Int(byte & 0x0F), Int(byte >> 4)] {
                let step = Self.imaStepTable[index]
                var delta = step >> 3
                if code & 4 != 0 { delta += step }
                if code & 2 != 0 { delta += step >> 1 }
                if code & 1 != 0 { delta += step >> 2 }
                predictor += code & 8 != 0 ? -delta : delta
                predictor = max(-32768, min(32767, predictor))
                index = max(0, min(88, index + Self.imaIndexTable[code]))
                samples.append(Int16(predictor))
                let value = max(-1.0, min(1.0, Float(predictor) / 32768.0))
                floats.append(value)
                floats.append(value)
            }
        }
        speechPipeline.append(samples: samples, sampleRate: 8_000)
        emitAudio(Data(bytes: floats, count: floats.count * MemoryLayout<Float>.size))
    }

    // MARK: - Аудио-синк + локальный TCP-сервер (для bt_whisper)

    private func emitAudio(_ data: Data) {
        if tcpPort != nil {
            for client in clients where !client.sendInFlight {
                client.sendInFlight = true
                client.connection.send(content: data, completion: .contentProcessed { [weak self, weak client] error in
                    DispatchQueue.main.async {
                        guard let client else { return }
                        client.sendInFlight = false
                        if error != nil {
                            self?.removeConn(client.connection)
                        }
                    }
                })
            }
        } else {
            output.write(data)
        }
    }

    private func startTCP(_ port: UInt16) {
        let params = NWParameters.tcp
        params.allowLocalEndpointReuse = true
        params.requiredLocalEndpoint = .hostPort(
            host: "127.0.0.1",
            port: NWEndpoint.Port(rawValue: port)!
        )
        guard let l = try? NWListener(using: params) else {
            fputs("carthing-btlink: TCP listen failed port=\(port)\n", stderr)
            return
        }
        listener = l
        l.newConnectionHandler = { [weak self] conn in self?.acceptConn(conn) }
        l.start(queue: netQueue)
        fputs("carthing-btlink: TCP server on 127.0.0.1:\(port)\n", stderr)
    }

    private func startEventTCP(_ port: UInt16) {
        let params = NWParameters.tcp
        params.allowLocalEndpointReuse = true
        params.requiredLocalEndpoint = .hostPort(
            host: "127.0.0.1",
            port: NWEndpoint.Port(rawValue: port)!
        )
        guard let listener = try? NWListener(using: params) else {
            fputs("carthing-btlink: event TCP listen failed port=\(port)\n", stderr)
            return
        }
        eventListener = listener
        listener.newConnectionHandler = { [weak self] connection in
            self?.acceptEventConn(connection)
        }
        listener.start(queue: netQueue)
        fputs("carthing-btlink: speech events on 127.0.0.1:\(port)\n", stderr)
    }

    private func acceptConn(_ conn: NWConnection) {
        var client: TCPAudioClient?
        conn.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                guard client == nil else { return }
                let newClient = TCPAudioClient(conn)
                client = newClient
                var sr = Int32(16_000).littleEndian
                conn.send(content: Data(bytes: &sr, count: 4), completion: .idempotent)
                DispatchQueue.main.async { self?.clients.append(newClient) }
                self?.receiveText(conn)
                fputs("carthing-btlink: TCP client connected\n", stderr)
            case .failed, .cancelled:
                self?.removeConn(conn)
            default:
                break
            }
        }
        conn.start(queue: netQueue)
    }

    private func acceptEventConn(_ conn: NWConnection) {
        conn.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                DispatchQueue.main.async {
                    self?.eventClients.append(conn)
                    self?.receiveText(conn)
                }
                fputs("carthing-btlink: speech event client connected\n", stderr)
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
            self?.clients.removeAll { $0.connection === conn }
            self?.eventClients.removeAll { $0 === conn }
        }
    }

    private func broadcastSpeech(text: String, isFinal: Bool) {
        let nowNs = DispatchTime.now().uptimeNanoseconds
        let audioTailToTextMs = latestAudioReceivedNs.map { Self.ms(nowNs, since: $0) }
        var object: [String: Any] = [
            "type": isFinal ? "final" : "partial",
            "text": text,
            "timestamp": Date().timeIntervalSince1970,
        ]
        if let latency = latestAudioLatency {
            object["audio_sequence"] = latency.sequence
            object["dsp_ms"] = latency.dspMs
            object["device_pipeline_ms"] = latency.devicePipelineMs
            object["bluetooth_ms"] = latency.bluetoothMs
            object["capture_to_mac_ms"] = latency.captureToMacMs
            object["ctsp_rtt_ms"] = latency.ctspRTTMs
            if let tail = audioTailToTextMs {
                object["audio_tail_to_text_ms"] = tail
                object["capture_to_text_edge_ms"] = latency.captureToMacMs + tail
            }
        }
        let kind = isFinal ? "final" : "partial"
        fputs(
            "carthing-btlink: speech_\(kind) metrics=\(metricsSummary(object)) text=\(text.prefix(80))\n",
            stderr
        )
        let shouldSendToDevice = isFinal
            || (text != lastPartialText && Date().timeIntervalSince(lastPartialSentAt) >= 0.15)
        if shouldSendToDevice {
            lastPartialText = text
            lastPartialSentAt = Date()
            let role = isFinal ? "U" : "P"
            transport.send(
                CTSPFrame(
                    type: .command,
                    payload: Data("text:\(role)|\(text)".utf8)
                )
            )
        }
        guard var data = try? JSONSerialization.data(withJSONObject: object) else {
            return
        }
        data.append(0x0A)
        for connection in eventClients {
            connection.send(content: data, completion: .contentProcessed { [weak self] error in
                if error != nil {
                    self?.removeConn(connection)
                }
            })
        }
    }

    private func metricsSummary(_ object: [String: Any]) -> String {
        let keys = [
            "dsp_ms",
            "device_pipeline_ms",
            "bluetooth_ms",
            "capture_to_mac_ms",
            "audio_tail_to_text_ms",
            "capture_to_text_edge_ms",
            "ctsp_rtt_ms",
        ]
        return keys.compactMap { key in
            guard let value = object[key] as? Double else { return nil }
            return String(format: "%@=%.1f", key, value)
        }.joined(separator: " ")
    }

    private func startLatencyProbes() {
        stopLatencyProbes()
        sendLatencyProbe()
        latencyProbeTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) {
            [weak self] _ in
            self?.sendLatencyProbe()
        }
    }

    private func stopLatencyProbes() {
        latencyProbeTimer?.invalidate()
        latencyProbeTimer = nil
    }

    private func sendLatencyProbe() {
        latencyProbeSequence &+= 1
        let sentNs = DispatchTime.now().uptimeNanoseconds
        transport.send(
            CTSPFrame(
                type: .latencyProbe,
                seq: latencyProbeSequence,
                payload: bigEndianData(sentNs)
            )
        )
    }

    private func handleLatencyProbe(_ frame: CTSPFrame) {
        let receivedNs = DispatchTime.now().uptimeNanoseconds
        guard let macSendNs = readUInt64BE(frame.payload, at: 0),
              let deviceReceiveNs = readUInt64BE(frame.payload, at: 8),
              let deviceSendNs = readUInt64BE(frame.payload, at: 16),
              receivedNs >= macSendNs,
              deviceSendNs >= deviceReceiveNs else {
            return
        }
        let processingNs = Double(deviceSendNs - deviceReceiveNs)
        let rttNs = max(0, Double(receivedNs - macSendNs) - processingNs)
        let measuredOffset = (
            (Double(deviceReceiveNs) - Double(macSendNs))
            + (Double(deviceSendNs) - Double(receivedNs))
        ) / 2
        if let current = clockOffsetDeviceMinusMacNs {
            clockOffsetDeviceMinusMacNs = current * 0.8 + measuredOffset * 0.2
        } else {
            clockOffsetDeviceMinusMacNs = measuredOffset
        }
        latestCTSPRTTMs = rttNs / 1_000_000
        fputs(
            String(
                format: "carthing-btlink: ctsp_probe seq=%u rtt_ms=%.1f\n",
                frame.seq,
                latestCTSPRTTMs ?? -1
            ),
            stderr
        )
    }

    private static func ms(_ end: UInt64, since start: UInt64) -> Double {
        guard end >= start else { return 0 }
        return Double(end - start) / 1_000_000
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
        guard tcpPort == nil else {
            fputs("carthing-btlink: play ignored in capture-only TCP mode\n", stderr)
            return
        }
        guard startPlaybackEngine(), let engine, let mixer else {
            fputs("carthing-btlink: playback engine unavailable\n", stderr)
            return
        }
        let url = URL(fileURLWithPath: path)
        guard let file = try? AVAudioFile(forReading: url) else {
            fputs("carthing-btlink: cannot open \(path)\n", stderr)
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
            fputs("carthing-btlink: done\n", stderr)
        }
        node.play()
        playerNode = node
    }

    private func startPlaybackEngine() -> Bool {
        if let engine {
            if engine.isRunning {
                return true
            }
            do {
                try engine.start()
                return true
            } catch {
                fputs("carthing-btlink: playback engine error: \(error)\n", stderr)
                return false
            }
        }

        let newEngine = AVAudioEngine()
        let newMixer = newEngine.mainMixerNode
        newEngine.connect(newMixer, to: newEngine.outputNode, format: nil)
        do {
            try newEngine.start()
            engine = newEngine
            mixer = newMixer
            return true
        } catch {
            fputs("carthing-btlink: playback engine error: \(error)\n", stderr)
            return false
        }
    }

    private func stopMic() {
        if streaming {
            transport.send(CTSPFrame(type: .command, payload: Data("stop_mic".utf8)))
        }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let cap = CarThingBTLink()
cap.start()
app.run()
