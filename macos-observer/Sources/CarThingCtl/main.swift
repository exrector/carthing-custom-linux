import Darwin
import Foundation
import Network

private func usage() -> Never {
    fputs(
        """
        usage:
          carthingctl status
          carthingctl logs [LINES]
          carthingctl restart
          carthingctl push LOCAL REMOTE [--restart]
          carthingctl deploy OVERLAY_PATH [--restart]

        """,
        stderr
    )
    exit(2)
}

private func commandObject(_ arguments: [String]) -> [String: Any] {
    guard let command = arguments.first else { usage() }
    switch command {
    case "status":
        guard arguments.count == 1 else { usage() }
        return ["op": "status"]
    case "logs":
        guard arguments.count <= 2 else { usage() }
        let lines = arguments.count == 2 ? Int(arguments[1]) ?? 80 : 80
        return ["op": "logs", "lines": max(1, min(200, lines))]
    case "restart":
        guard arguments.count == 1 else { usage() }
        return ["op": "restart"]
    case "push":
        guard arguments.count == 3 || arguments.count == 4 else { usage() }
        if arguments.count == 4 && arguments[3] != "--restart" {
            usage()
        }
        return [
            "op": "push",
            "local": URL(fileURLWithPath: arguments[1]).standardizedFileURL.path,
            "remote": arguments[2],
            "restart": arguments.count == 4,
        ]
    case "deploy":
        guard arguments.count == 2 || arguments.count == 3 else { usage() }
        if arguments.count == 3 && arguments[2] != "--restart" {
            usage()
        }
        let local = URL(fileURLWithPath: arguments[1]).standardizedFileURL
        let marker = "/overlay/"
        guard let range = local.path.range(of: marker) else {
            fputs("carthingctl: deploy path must be inside overlay/\n", stderr)
            exit(2)
        }
        let relative = local.path[range.upperBound...]
        return [
            "op": "push",
            "local": local.path,
            "remote": "/" + relative,
            "restart": arguments.count == 3,
        ]
    default:
        usage()
    }
}

private let command = commandObject(Array(CommandLine.arguments.dropFirst()))
private var request = try JSONSerialization.data(
    withJSONObject: command,
    options: [.sortedKeys]
)
request.append(0x0A)

private let queue = DispatchQueue(label: "carthingctl")
private let done = DispatchSemaphore(value: 0)
private let connection = NWConnection(
    host: "127.0.0.1",
    port: 49_502,
    using: .tcp
)
private var response = Data()
private var failure: String?

private func receive() {
    connection.receive(
        minimumIncompleteLength: 1,
        maximumLength: 64 * 1024
    ) { data, _, complete, error in
        if let data {
            response.append(data)
            if response.contains(0x0A) {
                done.signal()
                return
            }
        }
        if let error {
            failure = error.localizedDescription
            done.signal()
            return
        }
        if complete {
            done.signal()
            return
        }
        receive()
    }
}

connection.stateUpdateHandler = { state in
    switch state {
    case .ready:
        connection.send(
            content: request,
            completion: .contentProcessed { error in
                if let error {
                    failure = error.localizedDescription
                    done.signal()
                } else {
                    receive()
                }
            }
        )
    case .failed(let error):
        failure = error.localizedDescription
        done.signal()
    default:
        break
    }
}
connection.start(queue: queue)

guard done.wait(timeout: .now() + 120) == .success else {
    connection.cancel()
    fputs("carthingctl: operation timed out\n", stderr)
    exit(1)
}
connection.cancel()

if let failure {
    fputs("carthingctl: \(failure)\n", stderr)
    exit(1)
}
guard let newline = response.firstIndex(of: 0x0A),
      let object = try? JSONSerialization.jsonObject(
        with: response[..<newline]
      ) as? [String: Any] else {
    fputs("carthingctl: invalid response\n", stderr)
    exit(1)
}
if command["op"] as? String == "logs",
   object["ok"] as? Bool == true,
   let text = object["text"] as? String {
    print(text)
} else if let pretty = try? JSONSerialization.data(
    withJSONObject: object,
    options: [.prettyPrinted, .sortedKeys]
), let text = String(data: pretty, encoding: .utf8) {
    print(text)
}
exit(object["ok"] as? Bool == true ? 0 : 1)
