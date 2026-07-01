import Foundation

public enum AssistantTextEvent: Equatable, Sendable {
    case partial(String)
    case user(String)
    case assistant(String)
    case status(String)
}

public enum AssistantTextProtocol {
    public static func parse(_ value: String) -> AssistantTextEvent? {
        let parts = value.split(
            separator: "|",
            maxSplits: 1,
            omittingEmptySubsequences: false
        )
        guard parts.count == 2 else { return nil }
        let text = parts[1].trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        switch parts[0] {
        case "P": return .partial(text)
        case "U": return .user(text)
        case "A": return .assistant(text)
        case "S": return .status(text)
        default: return nil
        }
    }
}
