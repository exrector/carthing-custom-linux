import Foundation
import ProtocolCore
import XCTest

final class MaintenanceProtocolTests: XCTestCase {
    func testAuthenticatedEnvelopeRoundTrip() throws {
        let key = Data(repeating: 0xA5, count: 32)
        let payload = Data(#"{"path":"/usr/lib/carthing/screens.py"}"#.utf8)
        let encoded = try MaintenanceProtocol.encode(
            id: "request-1",
            op: "put_begin",
            payload: payload,
            key: key,
            session: "boot-session"
        )
        let decoded = try MaintenanceProtocol.decode(
            encoded,
            key: key,
            expectedSession: "boot-session"
        )
        XCTAssertEqual(decoded.envelope.id, "request-1")
        XCTAssertEqual(decoded.envelope.op, "put_begin")
        XCTAssertEqual(decoded.payload, payload)
        XCTAssertThrowsError(
            try MaintenanceProtocol.decode(
                encoded,
                key: key,
                expectedSession: "next-boot"
            )
        )
    }

    func testTamperedEnvelopeIsRejected() throws {
        let key = Data(repeating: 0x5A, count: 32)
        let encoded = try MaintenanceProtocol.encode(
            id: "request-2",
            op: "status",
            payload: Data("{}".utf8),
            key: key,
            session: "boot-session"
        )
        var object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encoded) as? [String: Any]
        )
        object["payload"] = Data(#"{"tampered":true}"#.utf8)
            .base64EncodedString()
        let tampered = try JSONSerialization.data(withJSONObject: object)
        XCTAssertThrowsError(
            try MaintenanceProtocol.decode(
                tampered,
                key: key,
                expectedSession: "boot-session"
            )
        )
    }
}
