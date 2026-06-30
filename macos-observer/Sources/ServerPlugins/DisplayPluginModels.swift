import Foundation

public let displayPluginProtocolVersion = 1

public struct DisplayPluginManifest: Codable, Equatable, Identifiable {
    public let schema: Int
    public let id: String
    public let name: String
    public let version: String
    public let executable: String
    public let summary: String
    public let icon: String?
    public let permissions: [String]
    public let defaultEnabled: Bool

    public init(
        schema: Int = displayPluginProtocolVersion,
        id: String,
        name: String,
        version: String,
        executable: String,
        summary: String = "",
        icon: String? = nil,
        permissions: [String] = [],
        defaultEnabled: Bool = false
    ) {
        self.schema = schema
        self.id = id
        self.name = name
        self.version = version
        self.executable = executable
        self.summary = summary
        self.icon = icon
        self.permissions = permissions
        self.defaultEnabled = defaultEnabled
    }

    enum CodingKeys: String, CodingKey {
        case schema, id, name, version, executable, summary, icon, permissions
        case defaultEnabled = "default_enabled"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schema = try values.decodeIfPresent(Int.self, forKey: .schema)
            ?? displayPluginProtocolVersion
        id = try values.decode(String.self, forKey: .id)
        name = try values.decode(String.self, forKey: .name)
        version = try values.decode(String.self, forKey: .version)
        executable = try values.decode(String.self, forKey: .executable)
        summary = try values.decodeIfPresent(String.self, forKey: .summary) ?? ""
        icon = try values.decodeIfPresent(String.self, forKey: .icon)
        permissions = try values.decodeIfPresent(
            [String].self,
            forKey: .permissions
        ) ?? []
        defaultEnabled = try values.decodeIfPresent(
            Bool.self,
            forKey: .defaultEnabled
        ) ?? false
    }
}

public enum DisplayPluginStatus: String, Codable {
    case disabled
    case starting
    case running
    case failed
    case stopped
}

public struct DisplayPluginRow: Codable, Equatable, Identifiable {
    public let id: String
    public let label: String
    public let value: String

    public init(id: String, label: String, value: String) {
        self.id = id
        self.label = label
        self.value = value
    }
}

public enum DisplayPluginActionStyle: String, Codable {
    case normal
    case primary
    case destructive
}

public struct DisplayPluginAction: Codable, Equatable, Identifiable {
    public let id: String
    public let label: String
    public let style: DisplayPluginActionStyle
    public let enabled: Bool

    public init(
        id: String,
        label: String,
        style: DisplayPluginActionStyle = .normal,
        enabled: Bool = true
    ) {
        self.id = id
        self.label = label
        self.style = style
        self.enabled = enabled
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(
            keyedBy: CodingKeys.self
        )
        id = try values.decode(String.self, forKey: .id)
        label = try values.decode(String.self, forKey: .label)
        style = try values.decodeIfPresent(
            DisplayPluginActionStyle.self,
            forKey: .style
        ) ?? .normal
        enabled = try values.decodeIfPresent(
            Bool.self,
            forKey: .enabled
        ) ?? true
    }

    enum CodingKeys: String, CodingKey {
        case id, label, style, enabled
    }
}

public struct DisplayPluginCard: Codable, Equatable, Identifiable {
    public let id: String
    public let title: String
    public let subtitle: String
    public let status: String
    public let accent: String?
    public let rows: [DisplayPluginRow]
    public let actions: [DisplayPluginAction]

    public init(
        id: String,
        title: String,
        subtitle: String = "",
        status: String = "",
        accent: String? = nil,
        rows: [DisplayPluginRow] = [],
        actions: [DisplayPluginAction] = []
    ) {
        self.id = id
        self.title = title
        self.subtitle = subtitle
        self.status = status
        self.accent = accent
        self.rows = rows
        self.actions = actions
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(
            keyedBy: CodingKeys.self
        )
        id = try values.decode(String.self, forKey: .id)
        title = try values.decode(String.self, forKey: .title)
        subtitle = try values.decodeIfPresent(
            String.self,
            forKey: .subtitle
        ) ?? ""
        status = try values.decodeIfPresent(
            String.self,
            forKey: .status
        ) ?? ""
        accent = try values.decodeIfPresent(String.self, forKey: .accent)
        rows = try values.decodeIfPresent(
            [DisplayPluginRow].self,
            forKey: .rows
        ) ?? []
        actions = try values.decodeIfPresent(
            [DisplayPluginAction].self,
            forKey: .actions
        ) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case id, title, subtitle, status, accent, rows, actions
    }
}

public struct DisplayPluginSnapshot: Codable, Equatable {
    public let schema: Int
    public let pluginID: String
    public let revision: Int
    public let cards: [DisplayPluginCard]

    public init(
        schema: Int = displayPluginProtocolVersion,
        pluginID: String,
        revision: Int,
        cards: [DisplayPluginCard]
    ) {
        self.schema = schema
        self.pluginID = pluginID
        self.revision = revision
        self.cards = cards
    }

    enum CodingKeys: String, CodingKey {
        case schema, revision, cards
        case pluginID = "plugin_id"
    }
}

public struct DisplayPluginRecord: Codable, Equatable, Identifiable {
    public let manifest: DisplayPluginManifest
    public var enabled: Bool
    public var status: DisplayPluginStatus
    public var message: String
    public var cardCount: Int

    public var id: String { manifest.id }

    public init(
        manifest: DisplayPluginManifest,
        enabled: Bool,
        status: DisplayPluginStatus,
        message: String = "",
        cardCount: Int = 0
    ) {
        self.manifest = manifest
        self.enabled = enabled
        self.status = status
        self.message = message
        self.cardCount = cardCount
    }

    enum CodingKeys: String, CodingKey {
        case manifest, enabled, status, message
        case cardCount = "card_count"
    }
}

public struct DisplayPluginCatalog: Codable, Equatable {
    public let schema: Int
    public let plugins: [DisplayPluginRecord]

    public init(
        schema: Int = displayPluginProtocolVersion,
        plugins: [DisplayPluginRecord]
    ) {
        self.schema = schema
        self.plugins = plugins
    }
}

public struct DisplayPluginActionRequest: Codable, Equatable {
    public let schema: Int
    public let pluginID: String
    public let cardID: String
    public let actionID: String

    public init(
        schema: Int = displayPluginProtocolVersion,
        pluginID: String,
        cardID: String,
        actionID: String
    ) {
        self.schema = schema
        self.pluginID = pluginID
        self.cardID = cardID
        self.actionID = actionID
    }

    enum CodingKeys: String, CodingKey {
        case schema
        case pluginID = "plugin_id"
        case cardID = "card_id"
        case actionID = "action_id"
    }
}

struct DisplayPluginOutputMessage: Codable {
    let type: String
    let snapshot: DisplayPluginSnapshot?
    let message: String?
}

struct DisplayPluginInputMessage: Codable {
    let type: String
    let protocolVersion: Int?
    let action: DisplayPluginActionRequest?

    enum CodingKeys: String, CodingKey {
        case type, action
        case protocolVersion = "protocol"
    }
}
