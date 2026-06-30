import Foundation

public enum DisplayPluginArchiveError: LocalizedError {
    case unsupportedArchive
    case extractionFailed(String)
    case missingManifest
    case invalidManifest(String)
    case unsafeArchive(String)
    case missingExecutable

    public var errorDescription: String? {
        switch self {
        case .unsupportedArchive:
            return "Выберите архив с расширением .ctplugin или .zip."
        case .extractionFailed(let message):
            return "Не удалось распаковать модуль: \(message)"
        case .missingManifest:
            return "В архиве отсутствует manifest.json."
        case .invalidManifest(let message):
            return "Некорректный manifest.json: \(message)"
        case .unsafeArchive(let path):
            return "Архив содержит небезопасный путь или ссылку: \(path)"
        case .missingExecutable:
            return "Исполняемый файл модуля не найден."
        }
    }
}

public final class DisplayPluginArchiveInstaller {
    private let fileManager: FileManager
    private let maximumArchiveBytes = 16 * 1024 * 1024
    private let maximumExtractedBytes = 64 * 1024 * 1024
    private let maximumEntries = 512

    public init(fileManager: FileManager = .default) {
        self.fileManager = fileManager
    }

    public func inspect(archiveURL: URL) throws -> DisplayPluginManifest {
        let ext = archiveURL.pathExtension.lowercased()
        guard ext == "ctplugin" || ext == "zip" else {
            throw DisplayPluginArchiveError.unsupportedArchive
        }
        let temporary = fileManager.temporaryDirectory
            .appendingPathComponent("carthing-plugin-\(UUID().uuidString)")
        try fileManager.createDirectory(
            at: temporary,
            withIntermediateDirectories: true
        )
        defer { try? fileManager.removeItem(at: temporary) }
        try extract(archiveURL: archiveURL, to: temporary)
        let packageRoot = try locatePackageRoot(in: temporary)
        try rejectUnsafeEntries(in: packageRoot)
        return try loadManifest(at: packageRoot)
    }

    public func install(
        archiveURL: URL,
        pluginsRoot: URL
    ) throws -> DisplayPluginManifest {
        let ext = archiveURL.pathExtension.lowercased()
        guard ext == "ctplugin" || ext == "zip" else {
            throw DisplayPluginArchiveError.unsupportedArchive
        }

        let temporary = fileManager.temporaryDirectory
            .appendingPathComponent("carthing-plugin-\(UUID().uuidString)")
        try fileManager.createDirectory(
            at: temporary,
            withIntermediateDirectories: true
        )
        defer { try? fileManager.removeItem(at: temporary) }

        try extract(archiveURL: archiveURL, to: temporary)

        let packageRoot = try locatePackageRoot(in: temporary)
        try rejectUnsafeEntries(in: packageRoot)
        let manifestURL = packageRoot.appendingPathComponent("manifest.json")
        let manifest = try JSONDecoder().decode(
            DisplayPluginManifest.self,
            from: Data(contentsOf: manifestURL)
        )
        try validate(manifest)

        let executableURL = try safeChild(
            manifest.executable,
            inside: packageRoot
        )
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(
            atPath: executableURL.path,
            isDirectory: &isDirectory
        ), !isDirectory.boolValue else {
            throw DisplayPluginArchiveError.missingExecutable
        }

        try fileManager.createDirectory(
            at: pluginsRoot,
            withIntermediateDirectories: true
        )
        let destination = pluginsRoot.appendingPathComponent(
            manifest.id,
            isDirectory: true
        )
        let staging = pluginsRoot.appendingPathComponent(
            ".\(manifest.id).\(UUID().uuidString)",
            isDirectory: true
        )
        let backup = pluginsRoot.appendingPathComponent(
            ".\(manifest.id).backup.\(UUID().uuidString)",
            isDirectory: true
        )
        try fileManager.copyItem(at: packageRoot, to: staging)
        var stagingExists = true
        var backupExists = false
        defer {
            if stagingExists {
                try? fileManager.removeItem(at: staging)
            }
            if backupExists {
                try? fileManager.removeItem(at: backup)
            }
        }
        let stagedExecutable = try safeChild(
            manifest.executable,
            inside: staging
        )
        try fileManager.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: stagedExecutable.path
        )
        if fileManager.fileExists(atPath: destination.path) {
            try fileManager.moveItem(at: destination, to: backup)
            backupExists = true
        }
        do {
            try fileManager.moveItem(at: staging, to: destination)
            stagingExists = false
            if backupExists {
                try fileManager.removeItem(at: backup)
                backupExists = false
            }
        } catch {
            if backupExists,
               !fileManager.fileExists(atPath: destination.path) {
                try? fileManager.moveItem(at: backup, to: destination)
                backupExists = false
            }
            throw error
        }
        return manifest
    }

    private func extract(archiveURL: URL, to destination: URL) throws {
        try validateArchiveBeforeExtraction(archiveURL)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        process.arguments = ["-x", "-k", archiveURL.path, destination.path]
        let errorPipe = Pipe()
        process.standardError = errorPipe
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let data = errorPipe.fileHandleForReading.readDataToEndOfFile()
            let message = String(data: data, encoding: .utf8) ?? "ditto failed"
            throw DisplayPluginArchiveError.extractionFailed(message)
        }
    }

    private func validateArchiveBeforeExtraction(_ archiveURL: URL) throws {
        let archiveSize = try archiveURL.resourceValues(
            forKeys: [.fileSizeKey]
        ).fileSize ?? 0
        guard archiveSize <= maximumArchiveBytes else {
            throw DisplayPluginArchiveError.unsafeArchive(
                "archive exceeds 16 MiB"
            )
        }
        let names = try unzipListing(arguments: ["-Z", "-1", archiveURL.path])
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
        guard names.count <= maximumEntries else {
            throw DisplayPluginArchiveError.unsafeArchive(
                "archive contains too many files"
            )
        }
        for name in names {
            _ = try safeChild(
                name,
                inside: URL(fileURLWithPath: "/plugin-archive")
            )
        }

        let detail = try unzipListing(
            arguments: ["-Z", "-l", archiveURL.path]
        )
        var total = 0
        for line in detail.split(separator: "\n") {
            let fields = line.split(
                whereSeparator: { $0 == " " || $0 == "\t" }
            )
            guard fields.count >= 4,
                  let type = fields.first?.first,
                  "-dl".contains(type) else {
                continue
            }
            if type == "l" {
                throw DisplayPluginArchiveError.unsafeArchive(
                    "symbolic links are not allowed"
                )
            }
            total += Int(fields[3]) ?? 0
            if total > maximumExtractedBytes {
                throw DisplayPluginArchiveError.unsafeArchive(
                    "expanded archive exceeds 64 MiB"
                )
            }
        }
    }

    private func unzipListing(arguments: [String]) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
        process.arguments = arguments
        let output = Pipe()
        let errors = Pipe()
        process.standardOutput = output
        process.standardError = errors
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let errorData = errors.fileHandleForReading.readDataToEndOfFile()
            throw DisplayPluginArchiveError.extractionFailed(
                String(data: errorData, encoding: .utf8) ?? "invalid zip"
            )
        }
        return String(data: data, encoding: .utf8) ?? ""
    }

    public func loadManifest(at packageRoot: URL) throws
        -> DisplayPluginManifest {
        try rejectUnsafeEntries(in: packageRoot)
        let data = try Data(
            contentsOf: packageRoot.appendingPathComponent("manifest.json")
        )
        let manifest = try JSONDecoder().decode(
            DisplayPluginManifest.self,
            from: data
        )
        try validate(manifest)
        let executable = try safeChild(
            manifest.executable,
            inside: packageRoot
        )
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(
            atPath: executable.path,
            isDirectory: &isDirectory
        ), !isDirectory.boolValue else {
            throw DisplayPluginArchiveError.missingExecutable
        }
        return manifest
    }

    private func locatePackageRoot(in temporary: URL) throws -> URL {
        let direct = temporary.appendingPathComponent("manifest.json")
        if fileManager.fileExists(atPath: direct.path) {
            return temporary
        }
        let children = try fileManager.contentsOfDirectory(
            at: temporary,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )
        let roots = children.filter {
            fileManager.fileExists(
                atPath: $0.appendingPathComponent("manifest.json").path
            )
        }
        guard roots.count == 1 else {
            throw DisplayPluginArchiveError.missingManifest
        }
        return roots[0]
    }

    private func rejectUnsafeEntries(in root: URL) throws {
        let keys: [URLResourceKey] = [
            .isSymbolicLinkKey,
            .isRegularFileKey,
            .isDirectoryKey,
        ]
        let rootValues = try root.resourceValues(forKeys: Set(keys))
        if rootValues.isSymbolicLink == true {
            throw DisplayPluginArchiveError.unsafeArchive(root.path)
        }
        guard let enumerator = fileManager.enumerator(
            at: root,
            includingPropertiesForKeys: keys
        ) else { return }
        for case let url as URL in enumerator {
            let values = try url.resourceValues(forKeys: Set(keys))
            if values.isSymbolicLink == true {
                throw DisplayPluginArchiveError.unsafeArchive(url.path)
            }
            _ = try safeChild(
                String(url.path.dropFirst(root.path.count + 1)),
                inside: root
            )
        }
    }

    private func safeChild(_ path: String, inside root: URL) throws -> URL {
        guard !path.isEmpty, !path.hasPrefix("/") else {
            throw DisplayPluginArchiveError.unsafeArchive(path)
        }
        let normalizedRoot = root.standardizedFileURL.path + "/"
        let candidate = root.appendingPathComponent(path).standardizedFileURL
        guard candidate.path.hasPrefix(normalizedRoot) else {
            throw DisplayPluginArchiveError.unsafeArchive(path)
        }
        return candidate
    }

    private func validate(_ manifest: DisplayPluginManifest) throws {
        guard manifest.schema == displayPluginProtocolVersion else {
            throw DisplayPluginArchiveError.invalidManifest(
                "unsupported schema \(manifest.schema)"
            )
        }
        let pattern = #"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$"#
        guard manifest.id.range(
            of: pattern,
            options: .regularExpression
        ) != nil else {
            throw DisplayPluginArchiveError.invalidManifest("invalid id")
        }
        guard !manifest.name.isEmpty,
              manifest.name.count <= 80,
              !manifest.version.isEmpty else {
            throw DisplayPluginArchiveError.invalidManifest(
                "name/version is required"
            )
        }
        _ = try safeChild(
            manifest.executable,
            inside: URL(fileURLWithPath: "/plugin-root")
        )
    }
}
