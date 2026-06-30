import AppKit
import Foundation

public final class AppleMusicPlugin: ServerPlugin {
    public let id = "mac_music"

    private let publish: (NowPlayingPayload) -> Void
    private let queue = DispatchQueue(label: "carthing.plugin.mac-music")
    private var timer: Timer?
    private var pollInFlight = false

    public init(publish: @escaping (NowPlayingPayload) -> Void) {
        self.publish = publish
    }

    public func start() {
        guard timer == nil else { return }
        poll()
        timer = Timer.scheduledTimer(
            withTimeInterval: 1.0,
            repeats: true
        ) { [weak self] _ in
            self?.poll()
        }
    }

    public func stop() {
        timer?.invalidate()
        timer = nil
    }

    public func handle(
        mediaCommand: String,
        activeSource: String?
    ) -> Bool {
        guard activeSource == "mac_local",
              let script = Self.controlScript(for: mediaCommand) else {
            return false
        }
        queue.async {
            var error: NSDictionary?
            if NSAppleScript(source: script)?
                .executeAndReturnError(&error) == nil {
                fputs(
                    "carthing-btlink: mac_music control failed: \(String(describing: error))\n",
                    stderr
                )
            }
        }
        return true
    }

    private func poll() {
        guard !pollInFlight else { return }
        pollInFlight = true
        queue.async { [weak self] in
            let payload = Self.read()
            DispatchQueue.main.async {
                guard let self else { return }
                self.pollInFlight = false
                self.publish(payload)
            }
        }
    }

    private static func read() -> NowPlayingPayload {
        guard !NSRunningApplication.runningApplications(
            withBundleIdentifier: "com.apple.Music"
        ).isEmpty else {
            return NowPlayingPayload(active: false, source: "mac_local")
        }
        let source = """
        tell application id "com.apple.Music"
            if player state is stopped then return {"stopped", "", "", "", 0, 0, 0, ""}
            set currentTrack to current track
            return {player state as text, name of currentTrack, artist of currentTrack, album of currentTrack, duration of currentTrack, player position, sound volume, persistent ID of currentTrack}
        end tell
        """
        var error: NSDictionary?
        guard let result = NSAppleScript(source: source)?
            .executeAndReturnError(&error),
              result.numberOfItems >= 8 else {
            if let error {
                fputs(
                    "carthing-btlink: mac_music poll failed: \(error)\n",
                    stderr
                )
            }
            return NowPlayingPayload(active: false, source: "mac_local")
        }

        let state = result.atIndex(1)?.stringValue ?? "stopped"
        let title = result.atIndex(2)?.stringValue ?? ""
        return NowPlayingPayload(
            active: state != "stopped" && !title.isEmpty,
            source: "mac_local",
            route: "Музыка · Mac",
            identifier: result.atIndex(8)?.stringValue ?? "",
            title: title,
            artist: result.atIndex(3)?.stringValue ?? "",
            album: result.atIndex(4)?.stringValue ?? "",
            elapsed: result.atIndex(6)?.doubleValue ?? 0,
            duration: result.atIndex(5)?.doubleValue ?? 0,
            volume: max(
                0,
                min(1, (result.atIndex(7)?.doubleValue ?? 0) / 100)
            ),
            playing: state == "playing",
            loading: false
        )
    }

    static func controlScript(for command: String) -> String? {
        let action: String
        switch command {
        case "toggle": action = "playpause"
        case "play": action = "play"
        case "pause": action = "pause"
        case "next": action = "next track"
        case "prev", "previous": action = "previous track"
        case "skip_fwd":
            action = "set player position to (player position + 15)"
        case "skip_back":
            action = "set player position to (player position - 15)"
        case "vol_up":
            action = "set sound volume to (sound volume + 5)"
        case "vol_down":
            action = "set sound volume to (sound volume - 5)"
        default:
            return nil
        }
        return "tell application id \"com.apple.Music\" to \(action)"
    }
}
