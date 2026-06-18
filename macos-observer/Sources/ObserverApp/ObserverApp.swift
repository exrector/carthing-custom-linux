import SwiftUI
import AppKit

@main
struct ObserverApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("Car Thing Observer") {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 720, minHeight: 560)
        }
        .windowResizability(.contentMinSize)
    }
}

/// Открыть путь в Finder (для diagnostic bundle).
func revealInFinder(_ url: URL) {
    NSWorkspace.shared.activateFileViewerSelecting([url])
}
