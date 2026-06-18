import Foundation

/// Роль endpoint в модели Input/Session/Output (роли независимы).
public enum EndpointRole: String, Codable, Sendable, CaseIterable {
    case audioInput
    case audioOutput
    case sessionPeer
    case remoteMicReceiver
    case usbPeer
}

/// Транспорты, которые умеет endpoint.
public enum EndpointTransport: String, Codable, Sendable, CaseIterable {
    case bleGattBootstrap
    case bleL2capCocSession
    case classicA2dpAvrcpAudio
    case usbNcmUacWhenAvailable
}

/// Идентичность Car Thing endpoint (стабильна между сессиями).
public struct EndpointIdentity: Codable, Sendable, Equatable {
    /// Заводской USID (источник истины имени, напр. "8559RP88Q917").
    public var carthingUSID: String?
    /// Идентификатор Mac-хоста (для multi-role endpoint этого Mac).
    public var macHostID: String?
    /// CoreBluetooth identifier (UUID), резолвится локально на этом Mac.
    public var bluetoothIdentifier: String?
    public var optionalUSBIdentity: String?

    public init(
        carthingUSID: String? = nil,
        macHostID: String? = nil,
        bluetoothIdentifier: String? = nil,
        optionalUSBIdentity: String? = nil
    ) {
        self.carthingUSID = carthingUSID
        self.macHostID = macHostID
        self.bluetoothIdentifier = bluetoothIdentifier
        self.optionalUSBIdentity = optionalUSBIdentity
    }
}

/// Политика endpoint — разделяет session и audio plane (инвариант архитектуры).
public struct EndpointPolicy: Codable, Sendable, Equatable {
    /// session/client plane включён.
    public var sessionEnabled: Bool = false
    /// выбран ли как аудиовход (НЕ зависит от sessionEnabled).
    public var audioSelected: Bool = false
    public var remoteMicAllowed: Bool = false
    public var backgroundAllowed: Bool = false

    public init() {}
}

/// Multi-role endpoint. Pairing с macOS сразу создаёт endpoint, а не «подключённый Mac».
public struct Endpoint: Codable, Sendable, Equatable, Identifiable {
    public var id: String              // стабильный endpoint id
    public var kind: String            // "macos" | "carthing" | ...
    public var displayName: String
    public var identity: EndpointIdentity
    public var roles: Set<EndpointRole>
    public var transports: Set<EndpointTransport>
    public var policy: EndpointPolicy

    /// Последний известный динамический L2CAP PSM (прочитан из GATT).
    public var lastKnownPSM: UInt16?
    public var lastSeen: Date?

    public init(
        id: String,
        kind: String,
        displayName: String,
        identity: EndpointIdentity = EndpointIdentity(),
        roles: Set<EndpointRole> = [],
        transports: Set<EndpointTransport> = [],
        policy: EndpointPolicy = EndpointPolicy(),
        lastKnownPSM: UInt16? = nil,
        lastSeen: Date? = nil
    ) {
        self.id = id
        self.kind = kind
        self.displayName = displayName
        self.identity = identity
        self.roles = roles
        self.transports = transports
        self.policy = policy
        self.lastKnownPSM = lastKnownPSM
        self.lastSeen = lastSeen
    }
}
