import Foundation
import ServerPlugins
import XCTest

final class DisplayPluginTests: XCTestCase {
    func testManifestDefaultsAndArchiveInstallDisabled() throws {
        XCTAssertTrue(Thread.isMainThread)
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let package = root.appendingPathComponent("package")
        let support = root.appendingPathComponent("support")
        let archive = root.appendingPathComponent("Example.ctplugin")
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(
            at: package,
            withIntermediateDirectories: true
        )
        let manifest = """
        {
          "id": "dev.carthing.tests.example",
          "name": "Example",
          "version": "1.0.0",
          "executable": "plugin",
          "default_enabled": true
        }
        """
        try Data(manifest.utf8).write(
            to: package.appendingPathComponent("manifest.json")
        )
        try Data("#!/bin/sh\nexit 0\n".utf8).write(
            to: package.appendingPathComponent("plugin")
        )
        try zip(package: package, to: archive)

        let host = DisplayPluginHost(applicationSupport: support)
        let installed = try host.install(archiveURL: archive)
        XCTAssertEqual(installed.id, "dev.carthing.tests.example")
        XCTAssertEqual(host.records.count, 1)
        XCTAssertFalse(host.records[0].enabled)
        XCTAssertEqual(host.records[0].status, .disabled)
    }

    func testArchiveRejectsExecutableOutsidePackage() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let package = root.appendingPathComponent("package")
        let archive = root.appendingPathComponent("Unsafe.ctplugin")
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(
            at: package,
            withIntermediateDirectories: true
        )
        let manifest = """
        {
          "schema": 1,
          "id": "dev.carthing.tests.unsafe",
          "name": "Unsafe",
          "version": "1.0.0",
          "executable": "../outside"
        }
        """
        try Data(manifest.utf8).write(
            to: package.appendingPathComponent("manifest.json")
        )
        try zip(package: package, to: archive)

        XCTAssertThrowsError(
            try DisplayPluginArchiveInstaller().inspect(archiveURL: archive)
        )
    }

    func testHostForwardsOnlyPublishedActions() throws {
        XCTAssertTrue(Thread.isMainThread)
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let package = root
            .appendingPathComponent("Plugins")
            .appendingPathComponent("dev.carthing.tests.actions")
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(
            at: package,
            withIntermediateDirectories: true
        )
        let manifest = """
        {
          "schema": 1,
          "id": "dev.carthing.tests.actions",
          "name": "Actions",
          "version": "1.0.0",
          "executable": "plugin"
        }
        """
        let script = """
        #!/bin/sh
        count=0
        while IFS= read -r line; do
          count=$((count + 1))
          if [ "$count" -eq 1 ]; then
            echo '{"type":"snapshot","snapshot":{"schema":1,"plugin_id":"dev.carthing.tests.actions","revision":1,"cards":[{"id":"main","title":"Actions","actions":[{"id":"run","label":"Run","style":"primary","enabled":true}]}]}}'
          else
            echo '{"type":"snapshot","snapshot":{"schema":1,"plugin_id":"dev.carthing.tests.actions","revision":2,"cards":[{"id":"main","title":"Actions","status":"DONE","actions":[{"id":"run","label":"Run","style":"primary","enabled":true}]}]}}'
          fi
        done
        """
        try Data(manifest.utf8).write(
            to: package.appendingPathComponent("manifest.json")
        )
        let executable = package.appendingPathComponent("plugin")
        try Data(script.utf8).write(to: executable)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: executable.path
        )
        try Data("[\"dev.carthing.tests.actions\"]".utf8).write(
            to: root.appendingPathComponent("plugins.json")
        )

        let started = expectation(description: "initial snapshot")
        let acted = expectation(description: "action snapshot")
        let host = DisplayPluginHost(applicationSupport: root)
        var catalogUpdates = 0
        host.onCatalogChanged = { _ in catalogUpdates += 1 }
        host.onSnapshot = { snapshot in
            if snapshot.revision == 1 {
                started.fulfill()
            } else if snapshot.revision == 2 {
                acted.fulfill()
            }
        }
        host.start()
        XCTAssertEqual(host.records.count, 1)
        XCTAssertTrue(host.records.first?.enabled == true)
        wait(for: [started], timeout: 2)
        XCTAssertEqual(
            host.records.first?.status,
            .running,
            host.records.first?.message ?? "missing record"
        )
        let catalogUpdatesBeforeAction = catalogUpdates
        XCTAssertFalse(
            host.handle(
                action: DisplayPluginActionRequest(
                    schema: 99,
                    pluginID: "dev.carthing.tests.actions",
                    cardID: "main",
                    actionID: "run"
                )
            )
        )
        XCTAssertFalse(
            host.handle(
                action: DisplayPluginActionRequest(
                    pluginID: "dev.carthing.tests.actions",
                    cardID: "main",
                    actionID: "not-published"
                )
            )
        )
        XCTAssertTrue(
            host.handle(
                action: DisplayPluginActionRequest(
                    pluginID: "dev.carthing.tests.actions",
                    cardID: "main",
                    actionID: "run"
                )
            )
        )
        wait(for: [acted], timeout: 2)
        XCTAssertEqual(
            host.snapshots["dev.carthing.tests.actions"]?.revision,
            2
        )
        XCTAssertEqual(catalogUpdates, catalogUpdatesBeforeAction)
        host.setEnabled(false, id: "dev.carthing.tests.actions")
        RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        XCTAssertEqual(host.records.first?.status, .disabled)
        host.stop()
    }

    private func zip(package: URL, to archive: URL) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        process.arguments = [
            "-c", "-k", "--norsrc", package.path + "/.", archive.path,
        ]
        try process.run()
        process.waitUntilExit()
        XCTAssertEqual(process.terminationStatus, 0)
    }
}
