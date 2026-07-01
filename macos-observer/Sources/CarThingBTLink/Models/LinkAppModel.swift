import AppKit
import Combine
import Foundation
import ProtocolCore
import ServerPlugins
import UniformTypeIdentifiers

struct AssistantMessage: Identifiable, Equatable {
    enum Role {
        case user
        case assistant
    }

    let id = UUID()
    let role: Role
    let text: String
    let timestamp: Date
}

final class LinkAppModel: ObservableObject {
    @Published var phase = "Ожидание"
    @Published var deviceName = "Car Thing"
    @Published var endpoint = ""
    @Published var rssi: Int?
    @Published var psm: Int?
    @Published var linkConnected = false
    @Published var micStreaming = false
    @Published var assistantRunning = false
    @Published var assistantEnabled: Bool
    @Published var assistantProvider: String
    @Published var assistantModel: String
    @Published var assistantAPIKey: String
    @Published var assistantEnvironmentFile: String
    @Published var assistantSystemPrompt: String
    @Published var assistantMessages: [AssistantMessage] = []
    @Published var assistantLiveText = ""
    @Published var assistantStatus = "Ожидание"
    @Published var pluginRecords: [DisplayPluginRecord] = []
    @Published var selectedPluginID: String?
    @Published var lastError = ""
    @Published var events: [String] = []

    weak var pluginHost: DisplayPluginHost?
    var onAssistantEnabledChanged: ((Bool) -> Void)?
    var onAssistantConfigurationChanged: (() -> Void)?

    private let assistantConfigurationStore: AssistantConfigurationStore

    init(
        assistantConfigurationStore: AssistantConfigurationStore =
            AssistantConfigurationStore()
    ) {
        self.assistantConfigurationStore = assistantConfigurationStore
        let configuration = assistantConfigurationStore.load()
        assistantEnabled = configuration.enabled
        assistantProvider = configuration.provider
        assistantModel = configuration.model
        assistantAPIKey = assistantConfigurationStore.apiKey(
            provider: configuration.provider
        )
        assistantEnvironmentFile = configuration.environmentFile
        assistantSystemPrompt = configuration.systemPrompt
    }

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

    func setAssistantEnabled(_ enabled: Bool) {
        assistantEnabled = enabled
        saveAssistantConfiguration(restart: false)
        onAssistantEnabledChanged?(enabled)
    }

    func selectAssistantProvider(_ provider: String) {
        guard provider == "mistral" || provider == "gemini" else { return }
        assistantProvider = provider
        assistantModel = provider == "gemini"
            ? "gemini-2.5-flash-lite"
            : "mistral-large-latest"
        assistantAPIKey = assistantConfigurationStore.apiKey(
            provider: provider
        )
    }

    func saveAssistantConfiguration(restart: Bool = true) {
        let configuration = currentAssistantConfiguration
        do {
            try assistantConfigurationStore.save(configuration)
            try assistantConfigurationStore.setAPIKey(
                assistantAPIKey,
                provider: assistantProvider
            )
            addEvent("Assistant configuration saved")
            if restart, assistantEnabled {
                onAssistantConfigurationChanged?()
            }
        } catch {
            lastError = error.localizedDescription
            addEvent("Assistant configuration failed: \(error.localizedDescription)")
        }
    }

    func chooseAssistantEnvironmentFile() {
        let panel = NSOpenPanel()
        panel.title = "Выберите файл окружения ассистента"
        panel.prompt = "Выбрать"
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            self?.assistantEnvironmentFile = url.path
        }
    }

    func clearAssistantConversation() {
        assistantMessages.removeAll()
        assistantLiveText = ""
        assistantStatus = assistantRunning ? "Готов" : "Ожидание"
    }

    func ingestAssistantText(_ value: String) {
        guard let event = AssistantTextProtocol.parse(value) else { return }
        switch event {
        case .partial(let text):
            assistantLiveText = text
        case .user(let text):
            assistantLiveText = ""
            appendAssistantMessage(role: .user, text: text)
        case .assistant(let text):
            appendAssistantMessage(role: .assistant, text: text)
        case .status(let text):
            assistantStatus = text.isEmpty
                ? (assistantRunning ? "Готов" : "Ожидание")
                : text
        }
    }

    func assistantWorkerEnvironment(
        base: [String: String]
    ) -> [String: String] {
        assistantConfigurationStore.workerEnvironment(
            configuration: currentAssistantConfiguration,
            base: base
        )
    }

    private var currentAssistantConfiguration: AssistantConfiguration {
        AssistantConfiguration(
            enabled: assistantEnabled,
            provider: assistantProvider,
            model: assistantModel.trimmingCharacters(
                in: .whitespacesAndNewlines
            ),
            environmentFile: assistantEnvironmentFile.trimmingCharacters(
                in: .whitespacesAndNewlines
            ),
            systemPrompt: assistantSystemPrompt.trimmingCharacters(
                in: .whitespacesAndNewlines
            )
        )
    }

    private func appendAssistantMessage(
        role: AssistantMessage.Role,
        text: String
    ) {
        guard !text.isEmpty else { return }
        if let last = assistantMessages.last,
           last.role == role,
           last.text == text {
            return
        }
        assistantMessages.append(
            AssistantMessage(role: role, text: text, timestamp: Date())
        )
        if assistantMessages.count > 100 {
            assistantMessages.removeFirst(assistantMessages.count - 100)
        }
    }
}
