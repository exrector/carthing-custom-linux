import Foundation

public protocol ServerPlugin: AnyObject {
    var id: String { get }
    func start()
    func stop()
    func handle(mediaCommand: String, activeSource: String?) -> Bool
}

public final class ServerPluginManager {
    private let plugins: [ServerPlugin]

    public init(
        plugins: [ServerPlugin],
        enabledIDs: Set<String>? = nil
    ) {
        let configured = enabledIDs ?? Self.enabledIDs()
        self.plugins = plugins.filter { configured.contains($0.id) }
    }

    public func start() {
        plugins.forEach { $0.start() }
    }

    public func stop() {
        plugins.forEach { $0.stop() }
    }

    public func handle(
        mediaCommand: String,
        activeSource: String?
    ) -> Bool {
        plugins.contains {
            $0.handle(
                mediaCommand: mediaCommand,
                activeSource: activeSource
            )
        }
    }

    public static func enabledIDs(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Set<String> {
        let raw = environment["CARTHING_SERVER_PLUGINS"] ?? "mac_music"
        return Set(
            raw.split(separator: ",")
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
        )
    }
}
