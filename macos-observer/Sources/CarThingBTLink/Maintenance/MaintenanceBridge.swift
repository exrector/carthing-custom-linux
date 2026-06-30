import CryptoKit
import Foundation
import Network
import ProtocolCore

private final class MaintenanceLocalClient {
    let connection: NWConnection
    var buffer = Data()

    init(connection: NWConnection) {
        self.connection = connection
    }
}

private final class MaintenanceOperation {
    enum Kind {
        case request
        case push
    }

    let id: String
    let kind: Kind
    let client: MaintenanceLocalClient
    let operation: String
    var fileData = Data()
    var remotePath = ""
    var fileHash = ""
    var fileMode = 0o644
    var restart = false
    var offset = 0
    var sequence = 0
    var pendingChunkBytes = 0

    init(
        id: String,
        kind: Kind,
        client: MaintenanceLocalClient,
        operation: String
    ) {
        self.id = id
        self.kind = kind
        self.client = client
        self.operation = operation
    }
}

final class MaintenanceBridge {
    private static let maximumFileBytes = 8 * 1024 * 1024
    private static let chunkBytes = 24 * 1024

    var onEvent: ((String) -> Void)?

    private let sendFrame: (Data) -> Void
    private let linkAvailable: () -> Bool
    private let port: UInt16
    private var key: Data?
    private var listener: NWListener?
    private var clients: [ObjectIdentifier: MaintenanceLocalClient] = [:]
    private var active: MaintenanceOperation?
    private var sessionID: String?

    init(
        port: UInt16 = 49_502,
        sendFrame: @escaping (Data) -> Void,
        linkAvailable: @escaping () -> Bool
    ) {
        self.port = port
        self.sendFrame = sendFrame
        self.linkAvailable = linkAvailable
        key = Self.loadKey()
    }

    var isProvisioned: Bool { key != nil }

    func setSession(_ session: String?) {
        sessionID = session?.isEmpty == false ? session : nil
    }

    func start() {
        guard listener == nil,
              let endpointPort = NWEndpoint.Port(rawValue: port) else {
            return
        }
        do {
            let parameters = NWParameters.tcp
            parameters.allowLocalEndpointReuse = true
            parameters.requiredLocalEndpoint = .hostPort(
                host: "127.0.0.1",
                port: endpointPort
            )
            let listener = try NWListener(using: parameters)
            listener.newConnectionHandler = { [weak self] connection in
                DispatchQueue.main.async {
                    self?.accept(connection)
                }
            }
            listener.stateUpdateHandler = { [weak self] state in
                if case .failed(let error) = state {
                    DispatchQueue.main.async {
                        self?.onEvent?(
                            "Maintenance listener failed: \(error.localizedDescription)"
                        )
                    }
                }
            }
            self.listener = listener
            listener.start(queue: .main)
            onEvent?(
                key == nil
                    ? "Bluetooth maintenance requires provisioning"
                    : "Bluetooth maintenance ready on localhost:\(port)"
            )
        } catch {
            onEvent?("Maintenance listener failed: \(error.localizedDescription)")
        }
    }

    func stop() {
        listener?.cancel()
        listener = nil
        clients.values.forEach { $0.connection.cancel() }
        clients.removeAll()
        finishActive(
            response: [
                "ok": false,
                "message": "CarThingBTLink is stopping",
            ]
        )
    }

    func linkClosed() {
        finishActive(
            response: [
                "ok": false,
                "message": "Bluetooth CTSP link closed",
            ]
        )
    }

    func handleDevicePayload(_ data: Data) {
        guard let key, let sessionID, let active else { return }
        do {
            let decoded = try MaintenanceProtocol.decode(
                data,
                key: key,
                expectedSession: sessionID
            )
            guard decoded.envelope.id == active.id,
                  decoded.envelope.op == "result",
                  let body = try JSONSerialization.jsonObject(
                    with: decoded.payload
                  ) as? [String: Any] else {
                return
            }
            guard body["ok"] as? Bool == true else {
                finishActive(response: body)
                return
            }
            if active.kind == .request {
                finishActive(response: body)
                return
            }
            let stage = body["stage"] as? String ?? ""
            switch stage {
            case "put_begin":
                sendNextChunk()
            case "put_chunk":
                active.offset += active.pendingChunkBytes
                active.pendingChunkBytes = 0
                active.sequence += 1
                sendNextChunk()
            case "put_commit":
                finishActive(response: body)
            default:
                finishActive(
                    response: [
                        "ok": false,
                        "message": "Unexpected maintenance response: \(stage)",
                    ]
                )
            }
        } catch {
            finishActive(
                response: [
                    "ok": false,
                    "message": "Invalid maintenance response",
                ]
            )
        }
    }

    func handleDeviceError(_ message: String) {
        guard active != nil else { return }
        finishActive(
            response: [
                "ok": false,
                "message": message,
            ]
        )
    }

    private func accept(_ connection: NWConnection) {
        let client = MaintenanceLocalClient(connection: connection)
        clients[ObjectIdentifier(connection)] = client
        connection.stateUpdateHandler = { [weak self, weak client] state in
            guard let self, let client else { return }
            if case .failed = state {
                DispatchQueue.main.async { self.remove(client) }
            } else if case .cancelled = state {
                DispatchQueue.main.async { self.remove(client) }
            }
        }
        connection.start(queue: .main)
        receive(client)
    }

    private func receive(_ client: MaintenanceLocalClient) {
        client.connection.receive(
            minimumIncompleteLength: 1,
            maximumLength: 16 * 1024
        ) { [weak self, weak client] data, _, complete, error in
            guard let self, let client else { return }
            DispatchQueue.main.async {
                if let data, !data.isEmpty {
                    client.buffer.append(data)
                    self.consumeLines(client)
                }
                if complete || error != nil {
                    self.remove(client)
                } else {
                    self.receive(client)
                }
            }
        }
    }

    private func consumeLines(_ client: MaintenanceLocalClient) {
        while let newline = client.buffer.firstIndex(of: 0x0A) {
            let line = Data(client.buffer[..<newline])
            client.buffer.removeSubrange(...newline)
            guard !line.isEmpty else { continue }
            handleLocalCommand(line, client: client)
        }
        if client.buffer.count > 16 * 1024 {
            respond(
                client,
                value: ["ok": false, "message": "Local command is too large"]
            )
        }
    }

    private func handleLocalCommand(
        _ data: Data,
        client: MaintenanceLocalClient
    ) {
        guard active == nil else {
            respond(
                client,
                value: ["ok": false, "message": "Another transfer is active"]
            )
            return
        }
        guard linkAvailable() else {
            respond(
                client,
                value: ["ok": false, "message": "Car Thing is not connected"]
            )
            return
        }
        guard key != nil, sessionID != nil else {
            respond(
                client,
                value: [
                    "ok": false,
                    "message": "Bluetooth maintenance is not ready",
                ]
            )
            return
        }
        guard let command = try? JSONSerialization.jsonObject(
            with: data
        ) as? [String: Any],
        let operation = command["op"] as? String else {
            respond(
                client,
                value: ["ok": false, "message": "Invalid local command"]
            )
            return
        }
        switch operation {
        case "status":
            beginRequest(operation: "status", body: [:], client: client)
        case "logs":
            beginRequest(
                operation: "logs",
                body: ["lines": command["lines"] as? Int ?? 80],
                client: client
            )
        case "restart":
            beginRequest(operation: "restart", body: [:], client: client)
        case "push":
            beginPush(command, client: client)
        default:
            respond(
                client,
                value: [
                    "ok": false,
                    "message": "Unsupported operation: \(operation)",
                ]
            )
        }
    }

    private func beginRequest(
        operation: String,
        body: [String: Any],
        client: MaintenanceLocalClient
    ) {
        let request = MaintenanceOperation(
            id: UUID().uuidString.lowercased(),
            kind: .request,
            client: client,
            operation: operation
        )
        active = request
        send(operation: operation, body: body, request: request)
    }

    private func beginPush(
        _ command: [String: Any],
        client: MaintenanceLocalClient
    ) {
        guard let local = command["local"] as? String,
              let remote = command["remote"] as? String else {
            respond(
                client,
                value: ["ok": false, "message": "push requires local and remote"]
            )
            return
        }
        let localURL = URL(fileURLWithPath: local)
        guard let data = try? Data(contentsOf: localURL),
              data.count <= Self.maximumFileBytes else {
            respond(
                client,
                value: ["ok": false, "message": "Cannot read local file or file is too large"]
            )
            return
        }
        let attributes = try? FileManager.default.attributesOfItem(
            atPath: localURL.path
        )
        let mode = (attributes?[.posixPermissions] as? NSNumber)?.intValue
            ?? 0o644
        let digest = SHA256.hash(data: data)
            .map { String(format: "%02x", $0) }
            .joined()
        let request = MaintenanceOperation(
            id: UUID().uuidString.lowercased(),
            kind: .push,
            client: client,
            operation: "push"
        )
        request.fileData = data
        request.remotePath = remote
        request.fileHash = digest
        request.fileMode = mode
        request.restart = command["restart"] as? Bool ?? false
        active = request
        send(
            operation: "put_begin",
            body: [
                "path": remote,
                "size": data.count,
                "sha256": digest,
                "mode": mode,
                "restart": request.restart,
            ],
            request: request
        )
    }

    private func sendNextChunk() {
        guard let active, active.kind == .push else { return }
        if active.offset >= active.fileData.count {
            send(operation: "put_commit", body: [:], request: active)
            return
        }
        let end = min(
            active.fileData.count,
            active.offset + Self.chunkBytes
        )
        let chunk = active.fileData[active.offset..<end]
        active.pendingChunkBytes = chunk.count
        send(
            operation: "put_chunk",
            body: [
                "seq": active.sequence,
                "data": Data(chunk).base64EncodedString(),
            ],
            request: active
        )
    }

    private func send(
        operation: String,
        body: [String: Any],
        request: MaintenanceOperation
    ) {
        guard let key,
              let sessionID,
              let payload = try? JSONSerialization.data(
                withJSONObject: body,
                options: [.sortedKeys]
              ),
              let envelope = try? MaintenanceProtocol.encode(
                id: request.id,
                op: operation,
                payload: payload,
                key: key,
                session: sessionID
              ) else {
            finishActive(
                response: ["ok": false, "message": "Cannot encode request"]
            )
            return
        }
        sendFrame(envelope)
    }

    private func finishActive(response: [String: Any]) {
        guard let active else { return }
        self.active = nil
        respond(active.client, value: response)
        onEvent?(
            (response["ok"] as? Bool == true)
                ? "Maintenance \(active.operation) completed"
                : "Maintenance \(active.operation) failed"
        )
    }

    private func respond(
        _ client: MaintenanceLocalClient,
        value: [String: Any]
    ) {
        guard var data = try? JSONSerialization.data(
            withJSONObject: value,
            options: [.sortedKeys]
        ) else {
            client.connection.cancel()
            return
        }
        data.append(0x0A)
        client.connection.send(
            content: data,
            completion: .contentProcessed { [weak self, weak client] _ in
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                    if let self, let client {
                        self.remove(client)
                    }
                }
            }
        )
    }

    private func remove(_ client: MaintenanceLocalClient) {
        clients[ObjectIdentifier(client.connection)] = nil
        client.connection.cancel()
        if active?.client === client {
            active = nil
        }
    }

    private static func loadKey() -> Data? {
        let url = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("CarThingBTLink")
            .appendingPathComponent("maintenance.key")
        guard let text = try? String(contentsOf: url, encoding: .utf8) else {
            return nil
        }
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.count == 64 else { return nil }
        var result = Data()
        result.reserveCapacity(32)
        var index = value.startIndex
        for _ in 0..<32 {
            let next = value.index(index, offsetBy: 2)
            guard let byte = UInt8(value[index..<next], radix: 16) else {
                return nil
            }
            result.append(byte)
            index = next
        }
        return result
    }
}
