// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "CarThingBTLink",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "CarThingBTLink", targets: ["CarThingBTLink"]),
        .executable(name: "carthingctl", targets: ["CarThingCtl"]),
        .library(name: "ProtocolCore", targets: ["ProtocolCore"]),
        .library(name: "ServerPlugins", targets: ["ServerPlugins"]),
        .library(name: "TransportCore", targets: ["TransportCore"]),
    ],
    targets: [
        .systemLibrary(
            name: "COpus",
            pkgConfig: "opus",
            providers: [
                .brew(["opus"])
            ]
        ),
        .target(name: "ProtocolCore"),
        .target(name: "ServerPlugins"),
        .target(
            name: "TransportCore",
            dependencies: ["ProtocolCore"]
        ),
        .executableTarget(
            name: "CarThingBTLink",
            dependencies: [
                "TransportCore",
                "ProtocolCore",
                "ServerPlugins",
                "COpus",
            ],
            linkerSettings: [
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "CarThingBTLink-Info.plist",
                ])
            ]
        ),
        .executableTarget(name: "CarThingCtl"),
        .testTarget(
            name: "ProtocolCoreTests",
            dependencies: ["ProtocolCore", "ServerPlugins"]
        ),
    ]
)
