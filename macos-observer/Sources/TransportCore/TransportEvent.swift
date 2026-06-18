import Foundation
import ProtocolCore
import SessionState

/// Обнаруженное в эфире устройство (кандидат на подключение).
public struct DiscoveredPeripheral: Identifiable, Equatable, Sendable {
    public let id: String          // CBPeripheral.identifier.uuidString
    public let name: String
    public let rssi: Int
    public init(id: String, name: String, rssi: Int) {
        self.id = id
        self.name = name
        self.rssi = rssi
    }
}

/// События транспортного слоя, поднимаемые наверх (в AppModel/observer UI).
///
/// Один поток событий вместо набора делегатов — проще завести в SwiftUI.
public enum TransportEvent: Sendable {
    case phaseChanged(TransportPhase)
    case discovered(DiscoveredPeripheral)
    /// GATT bootstrap прочитан: версия протокола, endpoint id, динамический PSM.
    case bootstrap(protocolVersion: UInt8?, endpointID: String?, psm: UInt16?, capabilities: Data?)
    case l2capOpened(psm: UInt16)
    case l2capClosed
    /// Принято сырых байт по CoC (для метрик).
    case bytesIn(Int)
    case bytesOut(Int)
    /// Декодированный кадр CTSP.
    case frame(CTSPFrame)
    case error(String)
    /// Человекочитаемая строка лога для панели.
    case log(String)
}
