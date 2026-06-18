import XCTest
@testable import ProtocolCore

final class CTSPCodecTests: XCTestCase {

    private func makeFrame(
        type: CTSPFrameType = .status,
        flags: UInt16 = 0,
        seq: UInt32 = 0,
        payload: Data = Data()
    ) -> CTSPFrame {
        CTSPFrame(type: type, flags: flags, seq: seq, payload: payload)
    }

    // MARK: header layout

    func testHeaderLayoutAndMagic() {
        let frame = makeFrame(type: .hello, flags: 0xBEEF, seq: 0x01020304,
                              payload: Data([0xAA, 0xBB]))
        let bytes = CTSPEncoder.encode(frame)

        XCTAssertEqual(bytes.count, CTSP.headerSize + 2)
        XCTAssertEqual(Array(bytes[0..<4]), Array("CTSP".utf8))
        XCTAssertEqual(bytes[4], CTSP.protocolVersion)         // version
        XCTAssertEqual(bytes[5], CTSPFrameType.hello.rawValue) // type
        XCTAssertEqual(bytes[6], 0xBE)                          // flags hi (big-endian)
        XCTAssertEqual(bytes[7], 0xEF)                          // flags lo
        XCTAssertEqual(Array(bytes[8..<12]), [0x01, 0x02, 0x03, 0x04]) // seq BE
        XCTAssertEqual(Array(bytes[12..<16]), [0x00, 0x00, 0x00, 0x02]) // len BE
        XCTAssertEqual(Array(bytes[16..<18]), [0xAA, 0xBB])     // payload
    }

    // MARK: round-trip

    func testRoundTripAllFrameTypes() throws {
        let decoder = CTSPFrameDecoder()
        for type in CTSPFrameType.allCases {
            let original = makeFrame(type: type, flags: 0x1234, seq: 42,
                                     payload: Data("hello-\(type)".utf8))
            let decoded = try decoder.feed(CTSPEncoder.encode(original))
            XCTAssertEqual(decoded.count, 1)
            XCTAssertEqual(decoded.first, original)
        }
    }

    func testEmptyPayloadRoundTrip() throws {
        let decoder = CTSPFrameDecoder()
        let frame = makeFrame(type: .hello, payload: Data())
        let decoded = try decoder.feed(CTSPEncoder.encode(frame))
        XCTAssertEqual(decoded, [frame])
    }

    // MARK: chunked / fragmented input

    func testFragmentedByteByByteReassembles() throws {
        let decoder = CTSPFrameDecoder()
        let frame = makeFrame(type: .audioPCM16, seq: 7,
                              payload: Data((0..<200).map { UInt8($0 & 0xFF) }))
        let encoded = CTSPEncoder.encode(frame)

        var collected: [CTSPFrame] = []
        for byte in encoded {
            collected += try decoder.feed(Data([byte]))
        }
        XCTAssertEqual(collected, [frame])
        XCTAssertEqual(decoder.pendingBytes, 0)
    }

    func testHeaderSplitAcrossFeeds() throws {
        let decoder = CTSPFrameDecoder()
        let frame = makeFrame(type: .telemetry, seq: 9, payload: Data("xyz".utf8))
        let encoded = CTSPEncoder.encode(frame)

        // Заголовок приходит частями, payload отдельно.
        XCTAssertEqual(try decoder.feed(encoded.prefix(5)), [])
        XCTAssertEqual(try decoder.feed(encoded[5..<CTSP.headerSize]), [])
        let frames = try decoder.feed(encoded.suffix(from: CTSP.headerSize))
        XCTAssertEqual(frames, [frame])
    }

    // MARK: multiple frames

    func testMultipleFramesInOneFeed() throws {
        let decoder = CTSPFrameDecoder()
        let f1 = makeFrame(type: .hello, seq: 1, payload: Data("a".utf8))
        let f2 = makeFrame(type: .status, seq: 2, payload: Data())
        let f3 = makeFrame(type: .routeState, seq: 3, payload: Data("ccc".utf8))

        var blob = Data()
        blob.append(CTSPEncoder.encode(f1))
        blob.append(CTSPEncoder.encode(f2))
        blob.append(CTSPEncoder.encode(f3))

        let frames = try decoder.feed(blob)
        XCTAssertEqual(frames, [f1, f2, f3])
    }

    func testTrailingPartialFrameKeptForNextFeed() throws {
        let decoder = CTSPFrameDecoder()
        let f1 = makeFrame(type: .status, seq: 1, payload: Data("one".utf8))
        let f2 = makeFrame(type: .command, seq: 2, payload: Data("two".utf8))

        var blob = CTSPEncoder.encode(f1)
        let enc2 = CTSPEncoder.encode(f2)
        blob.append(enc2.prefix(4)) // только часть второго кадра

        let firstRound = try decoder.feed(blob)
        XCTAssertEqual(firstRound, [f1])
        XCTAssertEqual(decoder.pendingBytes, 4)

        let secondRound = try decoder.feed(enc2.suffix(from: 4))
        XCTAssertEqual(secondRound, [f2])
    }

    // MARK: error paths

    func testBadMagicThrowsAndClearsBuffer() {
        let decoder = CTSPFrameDecoder()
        let garbage = Data([0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
                            0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F])
        XCTAssertThrowsError(try decoder.feed(garbage)) { error in
            guard case CTSPError.badMagic = error else {
                return XCTFail("expected badMagic, got \(error)")
            }
        }
        XCTAssertEqual(decoder.pendingBytes, 0)
    }

    func testUnknownFrameTypeThrowsButConsumesFrame() throws {
        let decoder = CTSPFrameDecoder()
        // Собираем валидный по структуре кадр с несуществующим типом 0x7F.
        var bytes = Data()
        bytes.append(contentsOf: Array("CTSP".utf8))
        bytes.append(CTSP.protocolVersion)
        bytes.append(0x7F)                       // неизвестный тип
        bytes.append(contentsOf: [0x00, 0x00])   // flags
        bytes.append(contentsOf: [0x00, 0x00, 0x00, 0x00]) // seq
        bytes.append(contentsOf: [0x00, 0x00, 0x00, 0x01]) // len=1
        bytes.append(0x42)                       // payload

        XCTAssertThrowsError(try decoder.feed(bytes)) { error in
            guard case CTSPError.unknownFrameType(0x7F) = error else {
                return XCTFail("expected unknownFrameType, got \(error)")
            }
        }
        // Кадр снят с буфера — следующий валидный кадр читается нормально.
        let good = makeFrame(type: .status, seq: 5)
        XCTAssertEqual(try decoder.feed(CTSPEncoder.encode(good)), [good])
    }

    func testPayloadTooLargeThrows() {
        let decoder = CTSPFrameDecoder()
        var bytes = Data()
        bytes.append(contentsOf: Array("CTSP".utf8))
        bytes.append(CTSP.protocolVersion)
        bytes.append(CTSPFrameType.audioPCM16.rawValue)
        bytes.append(contentsOf: [0x00, 0x00])
        bytes.append(contentsOf: [0x00, 0x00, 0x00, 0x00])
        // len = maxPayloadLength + 1
        let tooBig = CTSP.maxPayloadLength + 1
        bytes.append(UInt8((tooBig >> 24) & 0xFF))
        bytes.append(UInt8((tooBig >> 16) & 0xFF))
        bytes.append(UInt8((tooBig >> 8) & 0xFF))
        bytes.append(UInt8(tooBig & 0xFF))

        XCTAssertThrowsError(try decoder.feed(bytes)) { error in
            guard case CTSPError.payloadTooLarge = error else {
                return XCTFail("expected payloadTooLarge, got \(error)")
            }
        }
    }

    // MARK: large payload

    func testLargePayloadRoundTrip() throws {
        let decoder = CTSPFrameDecoder()
        let big = Data((0..<60_000).map { UInt8(($0 * 7) & 0xFF) })
        let frame = makeFrame(type: .audioPCM16, seq: 12345, payload: big)
        let frames = try decoder.feed(CTSPEncoder.encode(frame))
        XCTAssertEqual(frames, [frame])
    }
}
