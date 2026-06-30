import Foundation

final class ExternalDisplayPluginRuntime {
    private static let maximumJSONLBufferBytes = 256 * 1024
    let manifest: DisplayPluginManifest
    let packageRoot: URL

    var onSnapshot: ((DisplayPluginSnapshot) -> Void)?
    var onStatus: ((DisplayPluginStatus, String) -> Void)?

    private let queue: DispatchQueue
    private var process: Process?
    private var input: FileHandle?
    private var outputBuffer = Data()
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(manifest: DisplayPluginManifest, packageRoot: URL) {
        self.manifest = manifest
        self.packageRoot = packageRoot
        self.queue = DispatchQueue(
            label: "carthing.display-plugin.\(manifest.id)"
        )
        encoder.outputFormatting = [.sortedKeys]
    }

    func start(dataRoot: URL) {
        guard process == nil else { return }
        onStatus?(.starting, "")
        queue.async { [weak self] in
            self?.launch(dataRoot: dataRoot)
        }
    }

    func stop() {
        queue.async { [weak self] in
            guard let self else { return }
            self.send(
                DisplayPluginInputMessage(
                    type: "stop",
                    protocolVersion: nil,
                    action: nil
                )
            )
            self.process?.terminate()
            self.process = nil
            self.input = nil
            DispatchQueue.main.async {
                self.onStatus?(.stopped, "")
            }
        }
    }

    func send(action: DisplayPluginActionRequest) {
        queue.async { [weak self] in
            self?.send(
                DisplayPluginInputMessage(
                    type: "action",
                    protocolVersion: nil,
                    action: action
                )
            )
        }
    }

    private func launch(dataRoot: URL) {
        let executable = packageRoot.appendingPathComponent(
            manifest.executable
        )
        let pluginData = dataRoot.appendingPathComponent(
            manifest.id,
            isDirectory: true
        )
        do {
            try FileManager.default.createDirectory(
                at: pluginData,
                withIntermediateDirectories: true
            )
            let process = Process()
            let stdinPipe = Pipe()
            let stdoutPipe = Pipe()
            let stderrPipe = Pipe()
            process.executableURL = executable
            process.arguments = ["--carthing-plugin-stdio"]
            process.currentDirectoryURL = packageRoot
            process.standardInput = stdinPipe
            process.standardOutput = stdoutPipe
            process.standardError = stderrPipe
            var environment: [String: String] = [
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
                "CARTHING_PLUGIN_ID": manifest.id,
                "CARTHING_PLUGIN_DATA_DIR": pluginData.path,
                "CARTHING_PLUGIN_PROTOCOL": String(
                    displayPluginProtocolVersion
                ),
            ]
            if let tmp = ProcessInfo.processInfo.environment["TMPDIR"] {
                environment["TMPDIR"] = tmp
            }
            process.environment = environment
            stdoutPipe.fileHandleForReading.readabilityHandler = {
                [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else { return }
                self?.queue.async { self?.ingest(data) }
            }
            stderrPipe.fileHandleForReading.readabilityHandler = {
                [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty,
                      let text = String(data: data, encoding: .utf8) else {
                    return
                }
                DispatchQueue.main.async {
                    self?.onStatus?(
                        .running,
                        String(text.trimmingCharacters(
                            in: .whitespacesAndNewlines
                        ).suffix(300))
                    )
                }
            }
            process.terminationHandler = { [weak self] finished in
                self?.queue.async {
                    guard let self else { return }
                    self.process = nil
                    self.input = nil
                    let code = finished.terminationStatus
                    DispatchQueue.main.async {
                        self.onStatus?(
                            code == 0 ? .stopped : .failed,
                            code == 0 ? "" : "exit \(code)"
                        )
                    }
                }
            }
            try process.run()
            self.process = process
            input = stdinPipe.fileHandleForWriting
            send(
                DisplayPluginInputMessage(
                    type: "start",
                    protocolVersion: displayPluginProtocolVersion,
                    action: nil
                )
            )
            DispatchQueue.main.async { [weak self] in
                self?.onStatus?(.running, "")
            }
        } catch {
            DispatchQueue.main.async { [weak self] in
                self?.onStatus?(.failed, error.localizedDescription)
            }
        }
    }

    private func ingest(_ data: Data) {
        outputBuffer.append(data)
        while let newline = outputBuffer.firstIndex(of: 0x0A) {
            let line = Data(outputBuffer[..<newline])
            outputBuffer.removeSubrange(...newline)
            guard !line.isEmpty else { continue }
            guard line.count <= Self.maximumJSONLBufferBytes else {
                failOversizedOutput()
                return
            }
            do {
                let message = try decoder.decode(
                    DisplayPluginOutputMessage.self,
                    from: line
                )
                if message.type == "snapshot",
                   let snapshot = message.snapshot,
                   snapshot.pluginID == manifest.id {
                    DispatchQueue.main.async { [weak self] in
                        self?.onSnapshot?(snapshot)
                    }
                } else if message.type == "status" {
                    DispatchQueue.main.async { [weak self] in
                        self?.onStatus?(.running, message.message ?? "")
                    }
                }
            } catch {
                DispatchQueue.main.async { [weak self] in
                    self?.onStatus?(
                        .failed,
                        "invalid JSONL: \(error.localizedDescription)"
                    )
                }
            }
        }
        if outputBuffer.count > Self.maximumJSONLBufferBytes {
            failOversizedOutput()
        }
    }

    private func failOversizedOutput() {
        outputBuffer.removeAll(keepingCapacity: false)
        DispatchQueue.main.async { [weak self] in
            self?.onStatus?(.failed, "JSONL output exceeded 256 KiB")
        }
        process?.terminate()
    }

    private func send(_ message: DisplayPluginInputMessage) {
        guard let input,
              let data = try? encoder.encode(message) else {
            return
        }
        var line = data
        line.append(0x0A)
        do {
            try input.write(contentsOf: line)
        } catch {
            DispatchQueue.main.async { [weak self] in
                self?.onStatus?(.failed, error.localizedDescription)
            }
        }
    }
}
