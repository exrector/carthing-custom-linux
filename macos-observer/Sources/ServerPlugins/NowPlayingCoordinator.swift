import Foundation

public struct NowPlayingPayload: Codable, Equatable {
    public var active: Bool
    public var source: String
    public var route: String?
    public var identifier: String?
    public var title: String?
    public var artist: String?
    public var album: String?
    public var elapsed: Double?
    public var duration: Double?
    public var volume: Double?
    public var playing: Bool?
    public var loading: Bool?

    public init(
        active: Bool,
        source: String,
        route: String? = nil,
        identifier: String? = nil,
        title: String? = nil,
        artist: String? = nil,
        album: String? = nil,
        elapsed: Double? = nil,
        duration: Double? = nil,
        volume: Double? = nil,
        playing: Bool? = nil,
        loading: Bool? = nil
    ) {
        self.active = active
        self.source = source
        self.route = route
        self.identifier = identifier
        self.title = title
        self.artist = artist
        self.album = album
        self.elapsed = elapsed
        self.duration = duration
        self.volume = volume
        self.playing = playing
        self.loading = loading
    }
}

public final class NowPlayingCoordinator {
    private struct Snapshot {
        let payload: NowPlayingPayload
        let updatedAt: TimeInterval
    }

    private let publish: (Data) -> Void
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private var snapshots: [String: Snapshot] = [:]
    private var lastPublished: Data?

    public private(set) var activeSource: String?

    public init(publish: @escaping (Data) -> Void) {
        self.publish = publish
        encoder.outputFormatting = [.sortedKeys]
    }

    @discardableResult
    public func update(
        json: Data,
        now: TimeInterval = ProcessInfo.processInfo.systemUptime
    ) -> Bool {
        guard let payload = try? decoder.decode(
            NowPlayingPayload.self,
            from: json
        ) else {
            return false
        }
        update(payload, now: now)
        return true
    }

    public func update(
        _ payload: NowPlayingPayload,
        now: TimeInterval = ProcessInfo.processInfo.systemUptime
    ) {
        snapshots[payload.source] = Snapshot(payload: payload, updatedAt: now)
        publishSelected(now: now)
    }

    public func resend(
        now: TimeInterval = ProcessInfo.processInfo.systemUptime
    ) {
        publishSelected(now: now, force: true)
    }

    private func publishSelected(now: TimeInterval, force: Bool = false) {
        let selected = select(now: now)
        activeSource = selected.active ? selected.source : nil
        guard let data = try? encoder.encode(selected) else { return }
        guard force || data != lastPublished else { return }
        lastPublished = data
        publish(data)
    }

    private func select(now: TimeInterval) -> NowPlayingPayload {
        for (source, ttl) in [("airplay", 12.0), ("mac_local", 4.0)] {
            guard let snapshot = snapshots[source],
                  now - snapshot.updatedAt <= ttl,
                  snapshot.payload.active else {
                continue
            }
            return snapshot.payload
        }
        return NowPlayingPayload(active: false, source: "none")
    }
}
