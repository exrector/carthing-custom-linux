import Foundation
import Security

struct AssistantConfiguration: Codable, Equatable {
    var enabled: Bool
    var provider: String
    var model: String
    var environmentFile: String
    var systemPrompt: String

    static var defaults: AssistantConfiguration {
        let environment = ProcessInfo.processInfo.environment
        let script = environment["CARTHING_ASSISTANT_SCRIPT"] ?? ""
        let environmentFile = script.isEmpty
            ? FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Documents/ПРОЕКТЫ/voice-assistant/.env")
                .path
            : URL(fileURLWithPath: script)
                .deletingLastPathComponent()
                .appendingPathComponent(".env")
                .path
        return AssistantConfiguration(
            enabled: true,
            provider: "mistral",
            model: "mistral-large-latest",
            environmentFile: environmentFile,
            systemPrompt: """
            Ты — дружелюбный голосовой ассистент. Отвечай по-русски, кратко и \
            по делу: 1–2 коротких предложения, без списков и markdown. Текст \
            идёт на маленький экран.
            """
        )
    }
}

final class AssistantConfigurationStore {
    private let configurationURL: URL
    private let keychainService = "com.exrector.carthing.btlink.assistant"

    init(applicationSupport: URL? = nil) {
        let root = applicationSupport ?? FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("CarThingBTLink", isDirectory: true)
        configurationURL = root.appendingPathComponent("assistant.json")
    }

    func load() -> AssistantConfiguration {
        guard let data = try? Data(contentsOf: configurationURL),
              let value = try? JSONDecoder().decode(
                AssistantConfiguration.self,
                from: data
              ) else {
            return .defaults
        }
        return value
    }

    func save(_ configuration: AssistantConfiguration) throws {
        try FileManager.default.createDirectory(
            at: configurationURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let data = try JSONEncoder().encode(configuration)
        try data.write(to: configurationURL, options: [.atomic])
    }

    func apiKey(provider: String) -> String {
        let account = provider.lowercased()
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(
            query as CFDictionary,
            &item
        ) == errSecSuccess,
        let data = item as? Data,
        let value = String(data: data, encoding: .utf8) else {
            return ""
        }
        return value
    }

    func setAPIKey(_ value: String, provider: String) throws {
        let account = provider.lowercased()
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: account,
        ]
        let normalized = value.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        if normalized.isEmpty {
            SecItemDelete(base as CFDictionary)
            return
        }
        let update: [String: Any] = [
            kSecValueData as String: Data(normalized.utf8),
            kSecAttrAccessible as String:
                kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let status = SecItemUpdate(
            base as CFDictionary,
            update as CFDictionary
        )
        if status == errSecItemNotFound {
            var add = base
            update.forEach { add[$0.key] = $0.value }
            let addStatus = SecItemAdd(add as CFDictionary, nil)
            guard addStatus == errSecSuccess else {
                throw NSError(
                    domain: NSOSStatusErrorDomain,
                    code: Int(addStatus)
                )
            }
        } else if status != errSecSuccess {
            throw NSError(
                domain: NSOSStatusErrorDomain,
                code: Int(status)
            )
        }
    }

    func workerEnvironment(
        configuration: AssistantConfiguration,
        base: [String: String]
    ) -> [String: String] {
        var result = base
        valuesFromEnvironmentFile(configuration.environmentFile).forEach {
            result[$0.key] = $0.value
        }
        result["VA_LLM_PROVIDER"] = configuration.provider
        result["VA_BT_SYSTEM"] = configuration.systemPrompt
        if configuration.provider == "gemini" {
            result["VA_GEMINI_MODEL"] = configuration.model
            let key = apiKey(provider: "gemini")
            if !key.isEmpty {
                result["GEMINI_API_KEYS"] = key
            }
        } else {
            result["VA_MISTRAL_MODEL"] = configuration.model
            let key = apiKey(provider: "mistral")
            if !key.isEmpty {
                result["MISTRAL_API_KEY"] = key
            }
        }
        return result
    }

    private func valuesFromEnvironmentFile(
        _ path: String
    ) -> [String: String] {
        guard !path.isEmpty,
              let contents = try? String(
                contentsOfFile: path,
                encoding: .utf8
              ) else {
            return [:]
        }
        var result: [String: String] = [:]
        for rawLine in contents.split(
            whereSeparator: \.isNewline
        ) {
            let line = rawLine.trimmingCharacters(
                in: .whitespacesAndNewlines
            )
            guard !line.isEmpty,
                  !line.hasPrefix("#"),
                  let separator = line.firstIndex(of: "=") else {
                continue
            }
            let key = line[..<separator].trimmingCharacters(
                in: .whitespaces
            )
            var value = line[line.index(after: separator)...]
                .trimmingCharacters(in: .whitespaces)
            if value.count >= 2,
               (value.hasPrefix("\"") && value.hasSuffix("\"")
                || value.hasPrefix("'") && value.hasSuffix("'")) {
                value.removeFirst()
                value.removeLast()
            }
            if !key.isEmpty {
                result[String(key)] = value
            }
        }
        return result
    }
}
