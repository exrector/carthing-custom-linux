// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "CarThingBTLink",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "CarThingBTLink", targets: ["CarThingBTLink"]),
        .library(name: "ProtocolCore", targets: ["ProtocolCore"]),
        .library(name: "TransportCore", targets: ["TransportCore"]),
    ],
    targets: [
        .target(name: "ProtocolCore"),
        .target(
            name: "TransportCore",
            dependencies: ["ProtocolCore"]
        ),
        .executableTarget(
            name: "CarThingBTLink",
            dependencies: ["TransportCore", "ProtocolCore"],
            linkerSettings: [
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "CarThingBTLink-Info.plist",
                ])
            ]
        ),
        .testTarget(
            name: "ProtocolCoreTests",
            dependencies: ["ProtocolCore"]
        ),
    ]
)
