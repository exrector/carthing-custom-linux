import CryptoKit
import Foundation

public struct MaintenanceEnvelope: Codable, Equatable, Sendable {
    public let version: Int
    public let session: String
    public let id: String
    public let op: String
    public let payload: String
    public let auth: String

    public init(
        version: Int = 1,
        session: String,
        id: String,
        op: String,
        payload: String,
        auth: String
    ) {
        self.version = version
        self.session = session
        self.id = id
        self.op = op
        self.payload = payload
        self.auth = auth
    }
}

public enum MaintenanceProtocolError: Error {
    case invalidVersion
    case invalidPayload
    case invalidAuthentication
}

public enum MaintenanceProtocol {
    public static let version = 1
    public static let maximumPayloadBytes = 48 * 1024

    public static func encode(
        id: String,
        op: String,
        payload: Data,
        key: Data,
        session: String
    ) throws -> Data {
        guard payload.count <= maximumPayloadBytes else {
            throw MaintenanceProtocolError.invalidPayload
        }
        let payload64 = payload.base64EncodedString()
        let envelope = MaintenanceEnvelope(
            session: session,
            id: id,
            op: op,
            payload: payload64,
            auth: authentication(
                id: id,
                op: op,
                payload: payload64,
                key: key,
                session: session
            )
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(envelope)
    }

    public static func decode(
        _ data: Data,
        key: Data,
        expectedSession: String
    ) throws -> (envelope: MaintenanceEnvelope, payload: Data) {
        let envelope = try JSONDecoder().decode(
            MaintenanceEnvelope.self,
            from: data
        )
        guard envelope.version == version else {
            throw MaintenanceProtocolError.invalidVersion
        }
        guard envelope.session == expectedSession else {
            throw MaintenanceProtocolError.invalidAuthentication
        }
        let expected = authentication(
            id: envelope.id,
            op: envelope.op,
            payload: envelope.payload,
            key: key,
            session: envelope.session
        )
        guard constantTimeEqual(expected, envelope.auth) else {
            throw MaintenanceProtocolError.invalidAuthentication
        }
        guard let payload = Data(base64Encoded: envelope.payload),
              payload.count <= maximumPayloadBytes else {
            throw MaintenanceProtocolError.invalidPayload
        }
        return (envelope, payload)
    }

    private static func authentication(
        id: String,
        op: String,
        payload: String,
        key: Data,
        session: String
    ) -> String {
        let message = Data(
            "\(version)\n\(session)\n\(id)\n\(op)\n\(payload)".utf8
        )
        let code = HMAC<SHA256>.authenticationCode(
            for: message,
            using: SymmetricKey(data: key)
        )
        return code.map { String(format: "%02x", $0) }.joined()
    }

    private static func constantTimeEqual(_ lhs: String, _ rhs: String) -> Bool {
        let left = Array(lhs.utf8)
        let right = Array(rhs.utf8)
        guard left.count == right.count else { return false }
        var difference: UInt8 = 0
        for index in left.indices {
            difference |= left[index] ^ right[index]
        }
        return difference == 0
    }
}
