// swift-tools-version:5.9
import PackageDescription

// CarThing macOS Observer / helper.
//
// Назначение: наблюдаемый (observer) хелпер на стороне Mac для нового
// Bluetooth-first session-транспорта Car Thing (см.
// ../docs/INPUT-SESSION-OUTPUT-ARCHITECTURE-2026-06-18.md).
//
// Модульная раскладка повторяет требуемые слои:
//   ProtocolCore   — бинарный кодек кадров CTSP (чистый Foundation, тестируется headless).
//   DeviceRegistry — стабильная identity CarThing endpoint + persisted pairing/session metadata.
//   SessionState   — состояние соединения/маршрута, client on/off, ошибки, метрики.
//   AudioPipeline  — приём PCM16 16k mono кадров, ring buffer + debug WAV.
//   TransportCore  — CoreBluetooth scan/connect/GATT bootstrap/L2CAP CoC (только macOS).
//   ObserverApp    — SwiftUI окно живого наблюдения (исполняемый таргет).
let package = Package(
    name: "CarThingObserver",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "CarThingObserver", targets: ["ObserverApp"]),
        // ВРЕМЕННЫЙ CLI для loopback-проб связки клиент-сервер (см. MANIFEST.md).
        .executable(name: "CTSPProbe", targets: ["CTSPProbe"]),
        .executable(name: "CarThingBTAudioCap", targets: ["CarThingBTAudioCap"]),
        .library(name: "ProtocolCore", targets: ["ProtocolCore"]),
        .library(name: "DeviceRegistry", targets: ["DeviceRegistry"]),
        .library(name: "SessionState", targets: ["SessionState"]),
        .library(name: "AudioPipeline", targets: ["AudioPipeline"]),
        .library(name: "TransportCore", targets: ["TransportCore"]),
        .library(name: "LinkKit", targets: ["LinkKit"]),
    ],
    targets: [
        // Чистый Foundation, без платформенных зависимостей — полностью тестируется.
        .target(name: "ProtocolCore"),

        .target(name: "DeviceRegistry", dependencies: ["ProtocolCore"]),

        .target(name: "SessionState", dependencies: ["ProtocolCore"]),

        .target(name: "AudioPipeline"),

        // CoreBluetooth-зависимый слой.
        .target(
            name: "TransportCore",
            dependencies: ["ProtocolCore", "SessionState", "DeviceRegistry"]
        ),

        // SwiftUI observer.
        .executableTarget(
            name: "ObserverApp",
            dependencies: [
                "TransportCore",
                "ProtocolCore",
                "SessionState",
                "DeviceRegistry",
                "AudioPipeline",
            ],
            // Встраиваем Info.plist прямо в бинарь, чтобы macOS TCC показал
            // запрос разрешения на Bluetooth даже при запуске `swift run`.
            linkerSettings: [
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Sources/ObserverApp/Info.plist",
                ])
            ]
        ),

        // ВРЕМЕННЫЙ слой для loopback-проб связки клиент-сервер (TCP, без BT).
        .target(
            name: "LinkKit",
            dependencies: ["ProtocolCore", "SessionState"]
        ),

        // ВРЕМЕННЫЙ CLI: поднимает mock-сервер + клиент, печатает живые метрики.
        .executableTarget(
            name: "CTSPProbe",
            dependencies: ["ProtocolCore", "LinkKit", "SessionState", "AudioPipeline"]
        ),

        // audiocap-compatible source for voice-assistant: BLE CTSP input, local TTS playback.
        .executableTarget(
            name: "CarThingBTAudioCap",
            dependencies: ["TransportCore", "ProtocolCore", "SessionState"],
            linkerSettings: [
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Sources/ObserverApp/Info.plist",
                ])
            ]
        ),
        // Headless-тесты кодека CTSP (запускаются без устройства и без BT).
        .testTarget(
            name: "ProtocolCoreTests",
            dependencies: ["ProtocolCore"]
        ),

        // Интеграционные тесты связки клиент-сервер по реальному сокету.
        .testTarget(
            name: "IntegrationTests",
            dependencies: ["ProtocolCore", "LinkKit", "SessionState", "AudioPipeline"]
        ),
    ]
)
