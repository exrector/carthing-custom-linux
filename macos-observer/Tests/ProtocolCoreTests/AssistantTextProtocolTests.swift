import ProtocolCore
import XCTest

final class AssistantTextProtocolTests: XCTestCase {
    func testParsesEveryAssistantRole() {
        XCTAssertEqual(
            AssistantTextProtocol.parse("P|живой текст"),
            .partial("живой текст")
        )
        XCTAssertEqual(
            AssistantTextProtocol.parse("U| вопрос "),
            .user("вопрос")
        )
        XCTAssertEqual(
            AssistantTextProtocol.parse("A|ответ"),
            .assistant("ответ")
        )
        XCTAssertEqual(
            AssistantTextProtocol.parse("S|"),
            .status("")
        )
    }

    func testRejectsUnknownOrMalformedRole() {
        XCTAssertNil(AssistantTextProtocol.parse("X|text"))
        XCTAssertNil(AssistantTextProtocol.parse("text"))
    }
}
