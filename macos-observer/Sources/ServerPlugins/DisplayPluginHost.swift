import Foundation

public final class DisplayPluginHost {
    public var onCatalogChanged: ((DisplayPluginCatalog) -> Void)?
    public var onSnapshot: ((DisplayPluginSnapshot) -> Void)?

    public private(set) var records: [DisplayPluginRecord] = []
    public private(set) var snapshots: [String: DisplayPluginSnapshot] = [:]

    public let pluginsRoot: URL
    public let dataRoot: URL

    private let stateURL: URL
    private let installer = DisplayPluginArchiveInstaller()
    private var runtimes: [String: ExternalDisplayPluginRuntime] = [:]
    private var lastSnapshotPublish: [String: TimeInterval] = [:]
    private var pendingSnapshotPublish: [String: DispatchWorkItem] = [:]
    private var enabledIDs: Set<String> = []
    private var started = false

    public init(applicationSupport: URL? = nil) {
        let base = applicationSupport ?? FileManager.default
            .urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            )[0]
            .appendingPathComponent("CarThingBTLink", isDirectory: true)
        pluginsRoot = base.appendingPathComponent("Plugins", isDirectory: true)
        dataRoot = base.appendingPathComponent("PluginData", isDirectory: true)
        stateURL = base.appendingPathComponent("plugins.json")
        loadState()
    }

    public func start() {
        precondition(Thread.isMainThread)
        started = true
        reload()
    }

    public func stop() {
        precondition(Thread.isMainThread)
        started = false
        runtimes.values.forEach { $0.stop() }
        runtimes.removeAll()
        pendingSnapshotPublish.values.forEach { $0.cancel() }
        pendingSnapshotPublish.removeAll()
    }

    @discardableResult
    public func install(archiveURL: URL) throws -> DisplayPluginManifest {
        precondition(Thread.isMainThread)
        let candidate = try installer.inspect(archiveURL: archiveURL)
        runtimes[candidate.id]?.stop()
        runtimes[candidate.id] = nil
        snapshots[candidate.id] = nil
        let manifest: DisplayPluginManifest
        do {
            manifest = try installer.install(
                archiveURL: archiveURL,
                pluginsRoot: pluginsRoot
            )
        } catch {
            reload()
            throw error
        }
        enabledIDs.remove(manifest.id)
        saveState()
        reload()
        return manifest
    }

    public func uninstall(id: String) throws {
        precondition(Thread.isMainThread)
        runtimes[id]?.stop()
        runtimes[id] = nil
        snapshots[id] = nil
        pendingSnapshotPublish[id]?.cancel()
        pendingSnapshotPublish[id] = nil
        lastSnapshotPublish[id] = nil
        enabledIDs.remove(id)
        let target = pluginsRoot.appendingPathComponent(id)
        if FileManager.default.fileExists(atPath: target.path) {
            try FileManager.default.removeItem(at: target)
        }
        saveState()
        reload()
    }

    public func setEnabled(_ enabled: Bool, id: String) {
        precondition(Thread.isMainThread)
        guard records.contains(where: { $0.id == id }) else { return }
        if enabled {
            enabledIDs.insert(id)
        } else {
            enabledIDs.remove(id)
            runtimes[id]?.stop()
            runtimes[id] = nil
            snapshots[id] = nil
            pendingSnapshotPublish[id]?.cancel()
            pendingSnapshotPublish[id] = nil
            lastSnapshotPublish[id] = nil
        }
        saveState()
        reload()
    }

    public func handle(action: DisplayPluginActionRequest) -> Bool {
        precondition(Thread.isMainThread)
        guard action.schema == displayPluginProtocolVersion,
              enabledIDs.contains(action.pluginID),
              let runtime = runtimes[action.pluginID],
              let snapshot = snapshots[action.pluginID],
              snapshot.cards.contains(where: { card in
                  card.id == action.cardID
                      && card.actions.contains(where: {
                          $0.id == action.actionID && $0.enabled
                      })
              }) else {
            return false
        }
        runtime.send(action: action)
        return true
    }

    public func catalog() -> DisplayPluginCatalog {
        DisplayPluginCatalog(plugins: records)
    }

    public func reload() {
        precondition(Thread.isMainThread)
        let manifests = loadManifests()
        let installedIDs = Set(manifests.map(\.id))
        enabledIDs.formIntersection(installedIDs)
        var nextRecords: [DisplayPluginRecord] = []
        var manifestsToStart: [DisplayPluginManifest] = []

        for manifest in manifests {
            let enabled = enabledIDs.contains(manifest.id)
            let existing = records.first { $0.id == manifest.id }
            var record = DisplayPluginRecord(
                manifest: manifest,
                enabled: enabled,
                status: enabled ? (existing?.status ?? .starting) : .disabled,
                message: existing?.message ?? "",
                cardCount: snapshots[manifest.id]?.cards.count ?? 0
            )
            if !enabled {
                record.status = .disabled
                record.message = ""
            }
            nextRecords.append(record)
            if enabled, started, runtimes[manifest.id] == nil {
                manifestsToStart.append(manifest)
            }
        }

        let removedRuntimeIDs = runtimes.keys.filter {
            !installedIDs.contains($0)
        }
        for id in removedRuntimeIDs {
            runtimes[id]?.stop()
            runtimes[id] = nil
        }
        records = nextRecords.sorted {
            $0.manifest.name.localizedCaseInsensitiveCompare(
                $1.manifest.name
            ) == .orderedAscending
        }
        publishCatalog()
        for manifest in manifestsToStart {
            startRuntime(manifest)
        }
    }

    private func startRuntime(_ manifest: DisplayPluginManifest) {
        let packageRoot = pluginsRoot.appendingPathComponent(manifest.id)
        let runtime = ExternalDisplayPluginRuntime(
            manifest: manifest,
            packageRoot: packageRoot
        )
        runtime.onSnapshot = { [weak self] snapshot in
            guard let self else { return }
            guard self.runtimes[manifest.id] === runtime,
                  self.enabledIDs.contains(manifest.id) else {
                return
            }
            let sanitized = self.sanitize(
                snapshot,
                expectedPluginID: manifest.id
            )
            self.snapshots[manifest.id] = sanitized
            self.updateRecord(
                id: manifest.id,
                status: .running,
                message: "",
                cardCount: sanitized.cards.count
            )
            self.publishSnapshotThrottled(id: manifest.id)
        }
        runtime.onStatus = { [weak self] status, message in
            guard let self,
                  self.runtimes[manifest.id] === runtime,
                  self.enabledIDs.contains(manifest.id) else {
                return
            }
            self.updateRecord(
                id: manifest.id,
                status: status,
                message: message,
                cardCount: self.snapshots[manifest.id]?.cards.count ?? 0
            )
        }
        runtimes[manifest.id] = runtime
        runtime.start(dataRoot: dataRoot)
    }

    private func updateRecord(
        id: String,
        status: DisplayPluginStatus,
        message: String,
        cardCount: Int
    ) {
        guard let index = records.firstIndex(where: { $0.id == id }) else {
            reload()
            return
        }
        let normalizedMessage = String(message.prefix(300))
        guard records[index].status != status
                || records[index].message != normalizedMessage
                || records[index].cardCount != cardCount else {
            return
        }
        records[index].status = status
        records[index].message = normalizedMessage
        records[index].cardCount = cardCount
        publishCatalog()
    }

    private func publishCatalog() {
        onCatalogChanged?(catalog())
    }

    private func publishSnapshotThrottled(id: String) {
        let now = ProcessInfo.processInfo.systemUptime
        let elapsed = now - (lastSnapshotPublish[id] ?? 0)
        if elapsed >= 0.5 {
            pendingSnapshotPublish[id]?.cancel()
            pendingSnapshotPublish[id] = nil
            lastSnapshotPublish[id] = now
            if let snapshot = snapshots[id] {
                onSnapshot?(snapshot)
            }
            return
        }
        guard pendingSnapshotPublish[id] == nil else { return }
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.pendingSnapshotPublish[id] = nil
            self.lastSnapshotPublish[id] =
                ProcessInfo.processInfo.systemUptime
            if let snapshot = self.snapshots[id] {
                self.onSnapshot?(snapshot)
            }
        }
        pendingSnapshotPublish[id] = work
        DispatchQueue.main.asyncAfter(
            deadline: .now() + max(0.01, 0.5 - elapsed),
            execute: work
        )
    }

    private func loadManifests() -> [DisplayPluginManifest] {
        try? FileManager.default.createDirectory(
            at: pluginsRoot,
            withIntermediateDirectories: true
        )
        let directories = (try? FileManager.default.contentsOfDirectory(
            at: pluginsRoot,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )) ?? []
        return directories.compactMap {
            try? installer.loadManifest(at: $0)
        }
    }

    private func sanitize(
        _ snapshot: DisplayPluginSnapshot,
        expectedPluginID: String
    ) -> DisplayPluginSnapshot {
        let cards = snapshot.cards.prefix(8).map { card in
            DisplayPluginCard(
                id: String(card.id.prefix(80)),
                title: String(card.title.prefix(120)),
                subtitle: String(card.subtitle.prefix(240)),
                status: String(card.status.prefix(80)),
                accent: card.accent.map { String($0.prefix(16)) },
                rows: card.rows.prefix(8).map {
                    DisplayPluginRow(
                        id: String($0.id.prefix(80)),
                        label: String($0.label.prefix(80)),
                        value: String($0.value.prefix(120))
                    )
                },
                actions: card.actions.prefix(4).map {
                    DisplayPluginAction(
                        id: String($0.id.prefix(80)),
                        label: String($0.label.prefix(48)),
                        style: $0.style,
                        enabled: $0.enabled
                    )
                }
            )
        }
        return DisplayPluginSnapshot(
            pluginID: expectedPluginID,
            revision: max(0, snapshot.revision),
            cards: cards
        )
    }

    private func loadState() {
        guard let data = try? Data(contentsOf: stateURL),
              let values = try? JSONDecoder().decode(
                [String].self,
                from: data
              ) else {
            return
        }
        enabledIDs = Set(values)
    }

    private func saveState() {
        try? FileManager.default.createDirectory(
            at: stateURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        guard let data = try? JSONEncoder().encode(enabledIDs.sorted()) else {
            return
        }
        let temporary = stateURL.appendingPathExtension("tmp")
        try? data.write(to: temporary, options: .atomic)
        _ = try? FileManager.default.replaceItemAt(
            stateURL,
            withItemAt: temporary
        )
        if !FileManager.default.fileExists(atPath: stateURL.path) {
            try? FileManager.default.moveItem(at: temporary, to: stateURL)
        }
    }
}
