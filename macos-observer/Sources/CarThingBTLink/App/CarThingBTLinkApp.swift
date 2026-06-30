import AppKit
import ServerPlugins
import SwiftUI

final class CarThingAppDelegate: NSObject, NSApplicationDelegate {
    let model = LinkAppModel()
    let displayPluginHost = DisplayPluginHost()
    private var service: CarThingBTLink?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        model.pluginHost = displayPluginHost
        service = CarThingBTLink(
            appModel: model,
            displayPluginHost: displayPluginHost
        )
        service?.start()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationWillTerminate(_ notification: Notification) {
        service?.shutdown()
    }

    func applicationShouldTerminateAfterLastWindowClosed(
        _ sender: NSApplication
    ) -> Bool {
        false
    }
}

@main
struct CarThingBTLinkApp: App {
    @NSApplicationDelegateAdaptor(CarThingAppDelegate.self)
    private var appDelegate

    var body: some Scene {
        WindowGroup("Car Thing", id: "main") {
            RootView(model: appDelegate.model)
                .frame(minWidth: 780, minHeight: 520)
        }
        .defaultSize(width: 920, height: 620)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}
