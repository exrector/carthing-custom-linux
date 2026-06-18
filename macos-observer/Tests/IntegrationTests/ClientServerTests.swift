// ─────────────────────────────────────────────────────────────────────────────
// ВРЕМЕННЫЙ ФАЙЛ ДЛЯ ТЕСТОВ КЛИЕНТ-СЕРВЕР (Claude, 2026-06-18).
// Интеграционные тесты связки CTSP по реальному TCP-сокету (loopback, без BT).
// Проверяют bootstrap/route_state/RTT/on-demand mic поверх настоящего транспорта.
// См. macos-observer/MANIFEST.md.
// ─────────────────────────────────────────────────────────────────────────────
import XCTest
import ProtocolCore
import SessionState
import AudioPipeline
@testable import LinkKit

final class ClientServerTests: XCTestCase {

    /// Поднять mock-сервер на эфемерном порту и дождаться его готовности.
    private func startServer(route: SessionSnapshot? = nil) throws -> (MockCarThingServer, UInt16) {
        let server = try MockCarThingServer(route: route)
        let ready = expectation(description: "listening")
        var port: UInt16 = 0
        server.onListening = { p in port = p; ready.fulfill() }
        server.start()
        wait(for: [ready], timeout: 3)
        return (server, port)
    }

    func testConnectAndReceiveRouteState() throws {
        var route = SessionSnapshot()
        route.mode = .playNow
        route.activeAudioInput = .iPhone
        route.activeOutputSink = .local
        route.clientEnabled = true
        route.sessionPhase = .connected

        let (server, port) = try startServer(route: route)
        defer { server.stop() }

        let gotRoute = expectation(description: "route_state")
        var received: SessionSnapshot?

        let client = CTSPSession(link: TCPClientLink(host: "127.0.0.1", port: port))
        client.onFrame = { frame in
            if frame.type == .routeState {
                received = try? JSONDecoder().decode(SessionSnapshot.self, from: frame.payload)
                if received != nil { gotRoute.fulfill() }
            }
        }
        client.start()
        defer { client.stop() }

        wait(for: [gotRoute], timeout: 5)
        XCTAssertEqual(received?.mode, .playNow)
        XCTAssertEqual(received?.activeAudioInput, .iPhone)
        XCTAssertEqual(received?.sessionPhase, .connected)
        XCTAssertEqual(received?.clientEnabled, true)
    }

    func testHelloRoundTripMeasuresRTT() throws {
        let (server, port) = try startServer()
        defer { server.stop() }

        let gotHello = expectation(description: "hello echo")
        let sentAt = Date()
        var rtt: TimeInterval?

        let client = CTSPSession(link: TCPClientLink(host: "127.0.0.1", port: port))
        client.onConnected = { up in
            if up { client.send(CTSPFrame(type: .hello, payload: Data("ping".utf8))) }
        }
        client.onFrame = { frame in
            if frame.type == .hello {
                rtt = Date().timeIntervalSince(sentAt)
                XCTAssertEqual(String(data: frame.payload, encoding: .utf8), "ping")
                gotHello.fulfill()
            }
        }
        client.start()
        defer { client.stop() }

        wait(for: [gotHello], timeout: 5)
        XCTAssertNotNil(rtt)
        XCTAssertGreaterThan(rtt!, 0)
    }

    func testOnDemandMicStreamFlowsThenStops() throws {
        let (server, port) = try startServer()
        server.micConfig.frameMillis = 20
        defer { server.stop() }

        let audio = AudioPipeline()
        let gotAudio = expectation(description: "audio frames")
        var audioFrames = 0

        let client = CTSPSession(link: TCPClientLink(host: "127.0.0.1", port: port))
        client.onConnected = { up in
            if up {
                // mic НЕ должен течь до явной команды.
                client.send(CTSPFrame(type: .command, payload: Data("start_mic".utf8)))
            }
        }
        client.onFrame = { frame in
            if frame.type == .audioPCM16 {
                audio.ingest(frame.payload)
                audioFrames += 1
                if audioFrames == 10 { gotAudio.fulfill() }
            }
        }
        client.start()
        defer { client.stop() }

        wait(for: [gotAudio], timeout: 5)
        XCTAssertGreaterThanOrEqual(audioFrames, 10)
        XCTAssertGreaterThan(audio.totalBytes, 0)
        // Синтетический тон → ненулевой уровень.
        XCTAssertGreaterThan(audio.lastRMS, 0)

        client.send(CTSPFrame(type: .command, payload: Data("stop_mic".utf8)))
    }

    func testUnknownCommandReturnsError() throws {
        let (server, port) = try startServer()
        defer { server.stop() }

        let gotError = expectation(description: "error frame")
        let client = CTSPSession(link: TCPClientLink(host: "127.0.0.1", port: port))
        client.onConnected = { up in
            if up { client.send(CTSPFrame(type: .command, payload: Data("frobnicate".utf8))) }
        }
        client.onFrame = { frame in
            if frame.type == .error { gotError.fulfill() }
        }
        client.start()
        defer { client.stop() }

        wait(for: [gotError], timeout: 5)
    }
}
