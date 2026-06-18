import Foundation

/// Реестр известных Car Thing endpoint с persistence в JSON.
///
/// Хранит pairing/session metadata между запусками. Файл лежит в
/// `~/Library/Application Support/CarThingObserver/endpoints.json`.
/// Не потокобезопасен — используйте с main-очереди UI.
public final class DeviceRegistry {
    private(set) public var endpoints: [String: Endpoint] = [:]
    private let storeURL: URL

    /// - Parameter storeURL: путь к файлу. По умолчанию — Application Support.
    public init(storeURL: URL? = nil) {
        if let storeURL {
            self.storeURL = storeURL
        } else {
            let base = FileManager.default
                .urls(for: .applicationSupportDirectory, in: .userDomainMask)
                .first ?? FileManager.default.temporaryDirectory
            let dir = base.appendingPathComponent("CarThingObserver", isDirectory: true)
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            self.storeURL = dir.appendingPathComponent("endpoints.json")
        }
        load()
    }

    /// Все endpoint, отсортированные по «недавно виден».
    public var allSorted: [Endpoint] {
        endpoints.values.sorted {
            ($0.lastSeen ?? .distantPast) > ($1.lastSeen ?? .distantPast)
        }
    }

    public func endpoint(id: String) -> Endpoint? { endpoints[id] }

    /// Вставить/обновить endpoint и сохранить на диск.
    @discardableResult
    public func upsert(_ endpoint: Endpoint) -> Endpoint {
        endpoints[endpoint.id] = endpoint
        save()
        return endpoint
    }

    /// Обновить endpoint по id трансформером. Возвращает обновлённый endpoint.
    @discardableResult
    public func update(id: String, _ mutate: (inout Endpoint) -> Void) -> Endpoint? {
        guard var ep = endpoints[id] else { return nil }
        mutate(&ep)
        endpoints[id] = ep
        save()
        return ep
    }

    /// Найти или создать endpoint по CoreBluetooth identifier.
    public func resolveByBluetooth(identifier: String, displayName: String) -> Endpoint {
        if let existing = endpoints.values.first(where: {
            $0.identity.bluetoothIdentifier == identifier
        }) {
            return existing
        }
        var identity = EndpointIdentity()
        identity.bluetoothIdentifier = identifier
        let ep = Endpoint(
            id: identifier,
            kind: "carthing",
            displayName: displayName,
            identity: identity,
            transports: [.bleGattBootstrap, .bleL2capCocSession]
        )
        return upsert(ep)
    }

    public func remove(id: String) {
        endpoints.removeValue(forKey: id)
        save()
    }

    // MARK: - Persistence

    private func load() {
        guard let data = try? Data(contentsOf: storeURL) else { return }
        if let decoded = try? JSONDecoder().decode([String: Endpoint].self, from: data) {
            endpoints = decoded
        }
    }

    private func save() {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? encoder.encode(endpoints) else { return }
        try? data.write(to: storeURL, options: .atomic)
    }
}
