import SwiftUI
import SessionState
import TransportCore

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        HSplitView {
            VStack(alignment: .leading, spacing: 12) {
                connectionSection
                Divider()
                routeSection
                Divider()
                metricsSection
                Spacer()
                controlsSection
            }
            .padding()
            .frame(minWidth: 340)

            logPanel
                .frame(minWidth: 320)
        }
    }

    // MARK: - Connection / discovery

    private var connectionSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("ТРАНСПОРТ").font(.caption).foregroundStyle(.secondary)
            statusRow("Car Thing",
                      value: model.snapshot.transportPhase == .idle && model.discovered.isEmpty
                        ? "не обнаружен" : "обнаружен",
                      ok: !model.discovered.isEmpty)
            statusRow("Pairing/endpoint",
                      value: model.connectedEndpointID == nil ? "не сопряжён" : "сопряжён",
                      ok: model.connectedEndpointID != nil)
            statusRow("BLE GATT bootstrap",
                      value: phaseLabel(model.snapshot.transportPhase),
                      ok: model.snapshot.transportPhase == .bootstrapped
                        || model.snapshot.transportPhase == .l2capOpen)
            statusRow("L2CAP CoC",
                      value: model.snapshot.transportPhase == .l2capOpen ? "открыт" : "закрыт",
                      ok: model.snapshot.transportPhase == .l2capOpen)

            if !model.discovered.isEmpty {
                ForEach(model.discovered) { p in
                    HStack {
                        Text(p.name).font(.callout)
                        Text("\(p.rssi) dBm").font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Button("Подключить") { model.connect(p.id) }
                            .controlSize(.small)
                    }
                }
            }
        }
    }

    // MARK: - Route / session

    private var routeSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("МАРШРУТ / СЕССИЯ").font(.caption).foregroundStyle(.secondary)
            statusRow("MODE", value: modeLabel(model.snapshot.mode), ok: true)
            statusRow("INPUT", value: inputLabel(model.snapshot.activeAudioInput), ok: true)
            statusRow("SESSION", value: sessionLabel(model.snapshot.sessionPhase),
                      ok: model.snapshot.sessionPhase == .connected
                        || model.snapshot.sessionPhase == .streamingMic)
            statusRow("OUTPUT", value: outputLabel(model.snapshot.activeOutputSink), ok: true)

            HStack {
                Circle()
                    .fill(model.snapshot.micActive ? Color.green : Color.secondary.opacity(0.4))
                    .frame(width: 10, height: 10)
                Text(model.snapshot.micActive ? "mic stream active" : "mic idle")
                    .font(.callout)
                if model.snapshot.micActive {
                    ProgressView(value: min(model.micLevel * 4, 1.0))
                        .frame(width: 120)
                }
            }
            if let err = model.snapshot.lastError {
                Text("last error: \(err)").font(.caption).foregroundStyle(.red)
            }
        }
    }

    // MARK: - Metrics

    private var metricsSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("МЕТРИКИ").font(.caption).foregroundStyle(.secondary)
            statusRow("bytes/sec ↓↑",
                      value: "\(Int(model.metrics.bytesPerSecIn)) / \(Int(model.metrics.bytesPerSecOut))",
                      ok: true)
            statusRow("frames/sec", value: String(format: "%.1f", model.metrics.framesPerSec), ok: true)
            statusRow("latency est.",
                      value: model.metrics.latencyEstimateMs.map { String(format: "%.1f ms", $0) } ?? "—",
                      ok: true)
            statusRow("last frame",
                      value: "\(model.metrics.lastFrameType ?? "—") seq=\(model.metrics.lastSeq.map(String.init) ?? "—")",
                      ok: true)
            statusRow("total frames ↓↑",
                      value: "\(model.metrics.totalFramesIn) / \(model.metrics.totalFramesOut)",
                      ok: true)
        }
    }

    // MARK: - Controls

    private var controlsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Button("Scan") { model.startScan() }
                Button("Stop scan") { model.stopScan() }
                Button("Disconnect") { model.disconnect() }
                    .disabled(model.snapshot.transportPhase != .l2capOpen
                              && model.snapshot.transportPhase != .bootstrapped)
            }
            HStack {
                Toggle("Client ON", isOn: Binding(
                    get: { model.snapshot.clientEnabled },
                    set: { model.setClientEnabled($0) }
                ))
                .toggleStyle(.switch)
                Spacer()
                Button(model.isRecording ? "Stop WAV" : "Rec WAV") { model.toggleRecording() }
            }
            Button("Save diagnostic bundle") {
                if let url = model.saveDiagnosticBundle() { revealInFinder(url) }
            }
        }
    }

    // MARK: - Log panel

    private var logPanel: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("ЛОГ").font(.caption).foregroundStyle(.secondary).padding(.horizontal)
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(model.log) { line in
                            Text(line.text)
                                .font(.system(.caption, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(line.id)
                        }
                    }
                    .padding(.horizontal)
                }
                .onChange(of: model.log.count) { _ in
                    if let last = model.log.last { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
        .padding(.vertical)
    }

    // MARK: - Row helper + labels

    private func statusRow(_ title: String, value: String, ok: Bool) -> some View {
        HStack {
            Circle().fill(ok ? Color.green : Color.secondary.opacity(0.4))
                .frame(width: 8, height: 8)
            Text(title).font(.callout)
            Spacer()
            Text(value).font(.callout).foregroundStyle(.secondary)
        }
    }

    private func phaseLabel(_ p: TransportPhase) -> String {
        switch p {
        case .poweredOff: return "BT выключен"
        case .unauthorized: return "нет доступа"
        case .idle: return "ожидание"
        case .scanning: return "scan"
        case .connecting: return "connect"
        case .discoveringGATT: return "discovery"
        case .bootstrapped: return "готов"
        case .l2capOpening: return "L2CAP…"
        case .l2capOpen: return "готов"
        case .disconnected: return "отключён"
        case .failed: return "сбой"
        }
    }

    private func modeLabel(_ m: DeviceMode) -> String {
        switch m {
        case .playNow: return "Play Now"
        case .switcher: return "Коммутатор"
        case .reserveUSB: return "Резерв/USB"
        case .unknown: return "—"
        }
    }

    private func inputLabel(_ i: AudioInput) -> String {
        switch i {
        case .iPhone: return "iPhone"
        case .mac: return "Mac"
        case .usb: return "USB"
        case .localTest: return "local/test"
        case .none: return "none"
        }
    }

    private func sessionLabel(_ s: SessionPhase) -> String {
        switch s {
        case .off: return "Mac off"
        case .idle: return "idle"
        case .connected: return "connected"
        case .streamingMic: return "streaming mic"
        case .error: return "error"
        }
    }

    private func outputLabel(_ o: OutputSink) -> String {
        switch o {
        case .local: return "local"
        case .bluetooth: return "Fosi/BT"
        case .usb: return "USB"
        case .none: return "none"
        }
    }
}
