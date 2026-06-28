import AVFoundation
import Foundation
import Speech

final class AppleSpeechPipeline {
    typealias ResultHandler = (_ text: String, _ isFinal: Bool) -> Void

    private let onResult: ResultHandler
    private var analyzer: Any?
    private var inputContinuation: Any?
    private var resultsTask: Task<Void, Never>?
    private var formats: [Int: AVAudioFormat] = [:]

    init(onResult: @escaping ResultHandler) {
        self.onResult = onResult
    }

    func start() {
        guard #available(macOS 26.0, *) else {
            fputs("carthing-btlink: Apple Speech requires macOS 26+\n", stderr)
            return
        }
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                guard let self else { return }
                guard status == .authorized else {
                    fputs("carthing-btlink: speech authorization=\(status.rawValue)\n", stderr)
                    return
                }
                self.configure()
            }
        }
    }

    func append(samples: [Int16], sampleRate: Int) {
        guard #available(macOS 26.0, *),
              !samples.isEmpty,
              let continuation = inputContinuation
                as? AsyncStream<AnalyzerInput>.Continuation
        else {
            return
        }
        let format: AVAudioFormat
        if let cached = formats[sampleRate] {
            format = cached
        } else {
            guard let newFormat = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: Double(sampleRate),
                channels: 1,
                interleaved: false
            ) else {
                return
            }
            formats[sampleRate] = newFormat
            format = newFormat
        }
        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: AVAudioFrameCount(samples.count)
        ), let destination = buffer.int16ChannelData?[0] else {
            return
        }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBytes { source in
            guard let baseAddress = source.baseAddress else { return }
            memcpy(destination, baseAddress, source.count)
        }
        continuation.yield(AnalyzerInput(buffer: buffer))
    }

    @available(macOS 26.0, *)
    private func configure() {
        Task { [weak self] in
            guard let self else { return }
            let requestedLocale = Locale(identifier: "ru_RU")
            guard let locale = await DictationTranscriber.supportedLocale(
                equivalentTo: requestedLocale
            ) else {
                fputs("carthing-btlink: ru_RU speech model is unsupported\n", stderr)
                return
            }
            let transcriber = DictationTranscriber(
                locale: locale,
                contentHints: [],
                transcriptionOptions: [.punctuation],
                reportingOptions: [.volatileResults],
                attributeOptions: [.audioTimeRange]
            )
            do {
                let modules: [any SpeechModule] = [transcriber]
                let status = await AssetInventory.status(forModules: modules)
                if status != .installed,
                   let request = try await AssetInventory.assetInstallationRequest(
                       supporting: modules
                   ) {
                    fputs("carthing-btlink: installing ru_RU speech model\n", stderr)
                    try await request.downloadAndInstall()
                }

                let analyzer = SpeechAnalyzer(modules: modules)
                let (stream, continuation) = AsyncStream<AnalyzerInput>.makeStream(
                    bufferingPolicy: .bufferingNewest(200)
                )
                self.analyzer = analyzer
                self.inputContinuation = continuation
                self.resultsTask = Task { [weak self] in
                    do {
                        for try await result in transcriber.results {
                            let text = String(result.text.characters)
                                .trimmingCharacters(in: .whitespacesAndNewlines)
                            if !text.isEmpty {
                                self?.onResult(text, result.isFinal)
                            }
                        }
                    } catch {
                        fputs("carthing-btlink: speech results error: \(error)\n", stderr)
                    }
                }
                fputs(
                    "carthing-btlink: Apple DictationTranscriber ready locale=\(locale.identifier)\n",
                    stderr
                )
                try await analyzer.start(inputSequence: stream)
            } catch {
                fputs("carthing-btlink: speech setup error: \(error)\n", stderr)
            }
        }
    }
}
