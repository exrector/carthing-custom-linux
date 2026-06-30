import AppKit
import Combine
import Foundation
import ServerPlugins
import UniformTypeIdentifiers

final class LinkAppModel: ObservableObject {
    @Published var phase = "Ожидание"
    @Published var deviceName = "Car Thing"
    @Published var endpoint = ""
    @Published var rssi: Int?
    @Published var psm: Int?
    @Published var linkConnected = false
    @Published var micStreaming = false
    @Published var assistantRunning = false
    @Published var pluginRecords: [DisplayPluginRecord] = []
    @Published var selectedPluginID: String?
    @Published var lastError = ""
    @Published var events: [String] = []

    weak var pluginHost: DisplayPluginHost?

    var phaseLabel: String {
        switch phase {
        case "poweredOff": return "Bluetooth выключен"
        case "unauthorized": return "Нет доступа к Bluetooth"
        case "idle": return "Ожидание"
        case "scanning": return "Поиск устройства"
        case "connecting": return "Подключение"
        case "discoveringGATT": return "Чтение сервисов"
        case "bootstrapped": return "Настройка канала"
        case "l2capOpening": return "Открытие CTSP"
        case "l2capOpen": return "Подключён"
        case "disconnected": return "Отключён"
        case "failed": return "Ошибка"
        default: return phase
        }
    }

    func addEvent(_ message: String) {
        let stamp = Date().formatted(
            date: .omitted,
            time: .standard
        )
        events.append("\(stamp)  \(message)")
        if events.count > 200 {
            events.removeFirst(events.count - 200)
        }
    }

    func choosePluginArchive() {
        let panel = NSOpenPanel()
        panel.title = "Установить модуль Car Thing"
        panel.prompt = "Установить"
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.allowedContentTypes = [
            UTType(filenameExtension: "ctplugin") ?? .data,
            .zip,
        ]
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            do {
                let manifest = try self?.pluginHost?.install(
                    archiveURL: url
                )
                self?.selectedPluginID = manifest?.id
                self?.addEvent("Installed \(manifest?.name ?? url.lastPathComponent)")
            } catch {
                self?.lastError = error.localizedDescription
                self?.addEvent("Install failed: \(error.localizedDescription)")
            }
        }
    }

    func setPluginEnabled(_ enabled: Bool, id: String) {
        pluginHost?.setEnabled(enabled, id: id)
        addEvent("\(enabled ? "Enabled" : "Disabled") \(id)")
    }

    func uninstallPlugin(id: String) {
        do {
            try pluginHost?.uninstall(id: id)
            if selectedPluginID == id {
                selectedPluginID = nil
            }
            addEvent("Removed \(id)")
        } catch {
            lastError = error.localizedDescription
        }
    }

    func revealPluginsFolder() {
        guard let url = pluginHost?.pluginsRoot else { return }
        try? FileManager.default.createDirectory(
            at: url,
            withIntermediateDirectories: true
        )
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }
}
