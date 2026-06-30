import XCTest
@testable import ServerPlugins

final class NowPlayingCoordinatorTests: XCTestCase {
    func testAirPlayWinsAndLocalResumesWhenAirPlayExpires() {
        var published: [NowPlayingPayload] = []
        let coordinator = NowPlayingCoordinator { data in
            published.append(
                try! JSONDecoder().decode(NowPlayingPayload.self, from: data)
            )
        }
        coordinator.update(
            NowPlayingPayload(
                active: true,
                source: "mac_local",
                title: "Local",
                playing: true
            ),
            now: 100
        )
        coordinator.update(
            NowPlayingPayload(
                active: true,
                source: "airplay",
                title: "HomePod",
                playing: true
            ),
            now: 101
        )
        coordinator.update(
            NowPlayingPayload(
                active: true,
                source: "mac_local",
                title: "Local again",
                playing: true
            ),
            now: 114
        )
        XCTAssertEqual(published.map(\.title), [
            "Local",
            "HomePod",
            "Local again",
        ])
        XCTAssertEqual(coordinator.activeSource, "mac_local")
    }

    func testInactiveSourcesClearRemoteMedia() {
        var published: [NowPlayingPayload] = []
        let coordinator = NowPlayingCoordinator { data in
            published.append(
                try! JSONDecoder().decode(NowPlayingPayload.self, from: data)
            )
        }
        coordinator.update(
            NowPlayingPayload(
                active: true,
                source: "mac_local",
                title: "Local"
            ),
            now: 10
        )
        coordinator.update(
            NowPlayingPayload(active: false, source: "mac_local"),
            now: 11
        )
        XCTAssertEqual(published.last?.active, false)
        XCTAssertNil(coordinator.activeSource)
    }

    func testPluginListDefaultsToMacMusicAndCanBeOverridden() {
        XCTAssertEqual(
            ServerPluginManager.enabledIDs(environment: [:]),
            ["mac_music"]
        )
        XCTAssertEqual(
            ServerPluginManager.enabledIDs(
                environment: ["CARTHING_SERVER_PLUGINS": "mac_music, demo"]
            ),
            ["mac_music", "demo"]
        )
    }

    func testAppleMusicPluginMapsEveryDeviceMediaCommand() {
        for command in [
            "toggle",
            "play",
            "pause",
            "next",
            "prev",
            "previous",
            "skip_fwd",
            "skip_back",
            "vol_up",
            "vol_down",
        ] {
            XCTAssertNotNil(
                AppleMusicPlugin.controlScript(for: command),
                command
            )
        }
        XCTAssertNil(AppleMusicPlugin.controlScript(for: "eject"))
    }
}
