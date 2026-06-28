import Foundation
import CoreBluetooth
import ProtocolCore

/// CoreBluetooth-слой: scan → connect → GATT bootstrap → L2CAP CoC stream.
///
/// The link scans for the CTSP bootstrap service, opens its L2CAP channel,
/// and forwards microphone frames to the local assistant bridge.
public final class TransportCore: NSObject {
    /// Колбэк событий. Вызывается на main-очереди.
    public var onEvent: ((TransportEvent) -> Void)?

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var channel: CBL2CAPChannel?
    private var l2capOpening = false

    private let decoder = CTSPFrameDecoder()
    private var outQueue = Data()       // байты, ждущие записи в OutputStream
    private var pendingPSM: UInt16?
    private var bootstrapEmitted = false
    private var clientEnabled = false
    private var seqCounter: UInt32 = 0

    // Прочитанные при bootstrap значения.
    private var readProtocolVersion: UInt8?
    private var readEndpointID: String?
    private var readCapabilities: Data?

    public override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
    }

    // MARK: - Public commands

    /// Начать сканирование по сервису Car Thing. Явное действие пользователя.
    public func startScan() {
        guard central.state == .poweredOn else {
            emit(.log("startScan отклонён: central не poweredOn (\(central.state.rawValue))"))
            return
        }
        emit(.phaseChanged(.scanning))
        emit(.log("scan по сервису \(CarThingGATT.serviceUUID.uuidString)"))
        central.scanForPeripherals(
            withServices: [CarThingGATT.serviceUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )
    }

    public func stopScan() {
        if central.isScanning { central.stopScan() }
    }

    /// Подключиться к обнаруженному peripheral по id.
    public func connect(peripheralID: String) {
        guard let p = lastDiscovered[peripheralID] else {
            emit(.error("connect: неизвестный peripheral \(peripheralID)"))
            return
        }
        stopScan()
        peripheral = p
        p.delegate = self
        emit(.phaseChanged(.connecting))
        emit(.log("connect → \(p.name ?? peripheralID)"))
        central.connect(p, options: nil)
    }

    public func disconnect() {
        closeChannel()
        if let p = peripheral {
            central.cancelPeripheralConnection(p)
        }
        peripheral = nil
        pendingPSM = nil
        bootstrapEmitted = false
        emit(.phaseChanged(.disconnected))
    }

    /// Включить/выключить client (session plane) — пишет в GATT client_toggle.
    public func setClientEnabled(_ enabled: Bool) {
        clientEnabled = enabled
        guard let p = peripheral,
              let ch = characteristic(CarThingGATT.clientToggleUUID) else {
            emit(.log("client_toggle отложен: GATT ещё недоступен"))
            return
        }
        p.writeValue(Data([enabled ? 1 : 0]), for: ch, type: .withResponse)
        emit(.log("client_toggle ← \(enabled ? 1 : 0)"))
        if enabled {
            maybeOpenSession()
        } else {
            closeChannel()
            if pendingPSM != nil {
                emit(.phaseChanged(.bootstrapped))
            }
            emit(.log("Client OFF: L2CAP/CTSP session закрыта"))
        }
    }

    /// Отправить CTSP-кадр по L2CAP CoC. seq проставляется автоматически.
    public func send(_ frame: CTSPFrame) {
        var f = frame
        seqCounter &+= 1
        f.seq = seqCounter
        let bytes = CTSPEncoder.encode(f)
        outQueue.append(bytes)
        flushOutput()
        emit(.bytesOut(bytes.count))
    }

    // MARK: - Internal state

    private var lastDiscovered: [String: CBPeripheral] = [:]

    private func emit(_ event: TransportEvent) {
        onEvent?(event)
    }

    private func characteristic(_ uuid: CBUUID) -> CBCharacteristic? {
        peripheral?.services?
            .first(where: { $0.uuid == CarThingGATT.serviceUUID })?
            .characteristics?
            .first(where: { $0.uuid == uuid })
    }

    private func closeChannel() {
        if let ch = channel {
            ch.inputStream.close()
            ch.outputStream.close()
            ch.inputStream.remove(from: .main, forMode: .default)
            ch.outputStream.remove(from: .main, forMode: .default)
        }
        channel = nil
        l2capOpening = false
        decoder.reset()
        outQueue.removeAll(keepingCapacity: true)
    }

    private func publishBootstrapIfReady() {
        guard let psm = pendingPSM, !bootstrapEmitted else { return }
        bootstrapEmitted = true
        emit(.bootstrap(protocolVersion: readProtocolVersion,
                        endpointID: readEndpointID,
                        psm: psm,
                        capabilities: readCapabilities))
        emit(.phaseChanged(.bootstrapped))
        if !clientEnabled {
            emit(.log("GATT bootstrap готов; Client OFF, L2CAP не открываем"))
        }
    }

    private func maybeOpenSession() {
        publishBootstrapIfReady()
        guard clientEnabled else { return }
        guard let psm = pendingPSM else {
            emit(.log("Client ON: ждём current_psm"))
            return
        }
        guard channel == nil, !l2capOpening else { return }
        openL2CAP(psm: psm)
    }
}

// MARK: - CBCentralManagerDelegate

extension TransportCore: CBCentralManagerDelegate {
    public func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            emit(.phaseChanged(.idle))
            emit(.log("Bluetooth готов"))
        case .poweredOff:
            emit(.phaseChanged(.poweredOff))
        case .unauthorized:
            emit(.phaseChanged(.unauthorized))
            emit(.error("нет разрешения Bluetooth (TCC)"))
        default:
            emit(.log("central state = \(central.state.rawValue)"))
        }
    }

    public func centralManager(_ central: CBCentralManager,
                               didDiscover peripheral: CBPeripheral,
                               advertisementData: [String: Any],
                               rssi RSSI: NSNumber) {
        let id = peripheral.identifier.uuidString
        lastDiscovered[id] = peripheral
        let name = peripheral.name
            ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String)
            ?? "Car Thing"
        emit(.discovered(DiscoveredPeripheral(id: id, name: name, rssi: RSSI.intValue)))
    }

    public func centralManager(_ central: CBCentralManager,
                               didConnect peripheral: CBPeripheral) {
        emit(.phaseChanged(.discoveringGATT))
        emit(.log("подключён, ищем GATT-сервис"))
        peripheral.discoverServices([CarThingGATT.serviceUUID])
    }

    public func centralManager(_ central: CBCentralManager,
                               didFailToConnect peripheral: CBPeripheral,
                               error: Error?) {
        emit(.phaseChanged(.failed))
        emit(.error("connect failed: \(error?.localizedDescription ?? "?")"))
    }

    public func centralManager(_ central: CBCentralManager,
                               didDisconnectPeripheral peripheral: CBPeripheral,
                               error: Error?) {
        closeChannel()
        pendingPSM = nil
        bootstrapEmitted = false
        emit(.phaseChanged(.disconnected))
        emit(.l2capClosed)
        if let error { emit(.log("disconnect: \(error.localizedDescription)")) }
    }
}

// MARK: - CBPeripheralDelegate

extension TransportCore: CBPeripheralDelegate {
    public func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            emit(.phaseChanged(.failed))
            emit(.error("discoverServices: \(error.localizedDescription)"))
            return
        }
        guard let service = peripheral.services?
            .first(where: { $0.uuid == CarThingGATT.serviceUUID }) else {
            emit(.phaseChanged(.failed))
            emit(.error("сервис Car Thing не найден"))
            return
        }
        peripheral.discoverCharacteristics(CarThingGATT.allCharacteristicUUIDs, for: service)
    }

    public func peripheral(_ peripheral: CBPeripheral,
                          didDiscoverCharacteristicsFor service: CBService,
                          error: Error?) {
        if let error {
            emit(.phaseChanged(.failed))
            emit(.error("discoverCharacteristics: \(error.localizedDescription)"))
            return
        }
        // Читаем bootstrap-характеристики и подписываемся на PSM/status.
        for ch in service.characteristics ?? [] {
            if CarThingGATT.bootstrapReadUUIDs.contains(ch.uuid) {
                peripheral.readValue(for: ch)
            }
            if ch.uuid == CarThingGATT.currentPSMUUID || ch.uuid == CarThingGATT.statusUUID {
                if ch.properties.contains(.notify) {
                    peripheral.setNotifyValue(true, for: ch)
                }
            }
        }
    }

    public func peripheral(_ peripheral: CBPeripheral,
                          didUpdateValueFor characteristic: CBCharacteristic,
                          error: Error?) {
        if let error {
            emit(.phaseChanged(.failed))
            emit(.error("read \(characteristic.uuid): \(error.localizedDescription)"))
            return
        }
        guard let value = characteristic.value else { return }

        switch characteristic.uuid {
        case CarThingGATT.protocolVersionUUID:
            readProtocolVersion = value.first
        case CarThingGATT.endpointIDUUID:
            readEndpointID = String(data: value, encoding: .utf8)
        case CarThingGATT.capabilitiesUUID:
            readCapabilities = value
        case CarThingGATT.currentPSMUUID:
            pendingPSM = Self.parsePSM(value)
        case CarThingGATT.statusUUID:
            emit(.log("GATT status notify: \(value.count) байт"))
        default:
            break
        }

        // Bootstrap считается готовым, когда есть PSM, но CTSP session открывается
        // только при Client ON. Это сохраняет "тихий Play Now": обнаружение и
        // identity могут быть видны, но session plane не шумит без явного включения.
        maybeOpenSession()
    }

    private func openL2CAP(psm: UInt16) {
        guard let peripheral else { return }
        l2capOpening = true
        emit(.phaseChanged(.l2capOpening))
        emit(.log("openL2CAPChannel psm=\(psm)"))
        peripheral.openL2CAPChannel(CBL2CAPPSM(psm))
    }

    public func peripheral(_ peripheral: CBPeripheral,
                          didOpen channel: CBL2CAPChannel?,
                          error: Error?) {
        l2capOpening = false
        if let error {
            emit(.phaseChanged(.failed))
            emit(.error("openL2CAP: \(error.localizedDescription)"))
            return
        }
        guard let channel else {
            emit(.phaseChanged(.failed))
            emit(.error("openL2CAP: канал не создан"))
            return
        }
        self.channel = channel
        channel.inputStream.delegate = self
        channel.outputStream.delegate = self
        channel.inputStream.schedule(in: .main, forMode: .default)
        channel.outputStream.schedule(in: .main, forMode: .default)
        channel.inputStream.open()
        channel.outputStream.open()

        let psm = UInt16(channel.psm)
        emit(.phaseChanged(.l2capOpen))
        emit(.l2capOpened(psm: psm))
        emit(.log("L2CAP CoC открыт psm=\(psm)"))
    }

    private static func parsePSM(_ data: Data) -> UInt16? {
        guard data.count >= 2 else { return nil }
        // PSM передаётся little-endian.
        return UInt16(data[data.startIndex]) | (UInt16(data[data.startIndex + 1]) << 8)
    }
}

// MARK: - StreamDelegate (L2CAP CoC I/O)

extension TransportCore: StreamDelegate {
    public func stream(_ aStream: Stream, handle eventCode: Stream.Event) {
        switch eventCode {
        case .hasBytesAvailable:
            readAvailable(from: aStream as? InputStream)
        case .hasSpaceAvailable:
            flushOutput()
        case .errorOccurred:
            emit(.error("stream error: \(aStream.streamError?.localizedDescription ?? "?")"))
            closeChannel()
            emit(.l2capClosed)
        case .endEncountered:
            emit(.l2capClosed)
            closeChannel()
        default:
            break
        }
    }

    private func readAvailable(from input: InputStream?) {
        guard let input else { return }
        let bufSize = 4096
        var buf = [UInt8](repeating: 0, count: bufSize)
        while input.hasBytesAvailable {
            let n = input.read(&buf, maxLength: bufSize)
            guard n > 0 else { break }
            let chunk = Data(buf[0..<n])
            emit(.bytesIn(n))
            do {
                let frames = try decoder.feed(chunk)
                for f in frames { emit(.frame(f)) }
            } catch {
                emit(.error("CTSP decode: \(error)"))
            }
        }
    }

    private func flushOutput() {
        guard let out = channel?.outputStream, !outQueue.isEmpty else { return }
        while out.hasSpaceAvailable, !outQueue.isEmpty {
            let n = outQueue.withUnsafeBytes { raw -> Int in
                guard let base = raw.bindMemory(to: UInt8.self).baseAddress else { return 0 }
                return out.write(base, maxLength: outQueue.count)
            }
            guard n > 0 else { break }
            outQueue.removeFirst(n)
        }
    }
}
