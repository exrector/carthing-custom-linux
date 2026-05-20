import argparse
import asyncio
import logging
import sys
from pathlib import Path

from runtime_paths import BD_ADDRESS, KEYSTORE_PATH, TRANSPORT

SRC_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SRC_DIR / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

from bumble.transport import open_transport_or_link
from bumble.device import Device
from bumble.host import Host
from bumble.keys import JsonKeyStore
from bumble.smp import PairingConfig
from bumble.core import (
    BT_BR_EDR_TRANSPORT,
    UUID,
    BT_RFCOMM_PROTOCOL_ID,
    BT_HANDSFREE_AUDIO_GATEWAY_SERVICE,
    BT_HANDSFREE_SERVICE,
    BT_PHONEBOOK_ACCESS_PSE_SERVICE,
    BT_PHONEBOOK_ACCESS_SERVICE,
    BT_MESSAGE_ACCESS_SERVER_SERVICE,
    BT_MESSAGE_ACCESS_PROFILE_SERVICE,
    BT_AV_REMOTE_CONTROL_TARGET_SERVICE,
    BT_AV_REMOTE_CONTROL_SERVICE,
    BT_AV_REMOTE_CONTROL_CONTROLLER_SERVICE,
    BT_ADVANCED_AUDIO_DISTRIBUTION_SERVICE,
    BT_AUDIO_SOURCE_SERVICE,
)
from bumble import rfcomm, sdp
from bumble.hfp import HfpProtocol


LOG = logging.getLogger(__name__)

PROFILE_UUIDS = [
    ("HFP_AG", BT_HANDSFREE_AUDIO_GATEWAY_SERVICE),
    ("HFP_HF", BT_HANDSFREE_SERVICE),
    ("PBAP_PSE", BT_PHONEBOOK_ACCESS_PSE_SERVICE),
    ("PBAP", BT_PHONEBOOK_ACCESS_SERVICE),
    ("MAP_MAS", BT_MESSAGE_ACCESS_SERVER_SERVICE),
    ("MAP", BT_MESSAGE_ACCESS_PROFILE_SERVICE),
    ("AVRCP_TARGET", BT_AV_REMOTE_CONTROL_TARGET_SERVICE),
    ("AVRCP", BT_AV_REMOTE_CONTROL_SERVICE),
    ("AVRCP_CONTROLLER", BT_AV_REMOTE_CONTROL_CONTROLLER_SERVICE),
    ("A2DP", BT_ADVANCED_AUDIO_DISTRIBUTION_SERVICE),
    ("AUDIO_SOURCE", BT_AUDIO_SOURCE_SERVICE),
]


def make_device(source, sink):
    device = Device(
        name="CarThing Classic Probe",
        address=BD_ADDRESS,
        host=Host(controller_source=source, controller_sink=sink),
    )
    device.classic_enabled = True
    device.le_enabled = False
    device.keystore = JsonKeyStore("CarThing", str(KEYSTORE_PATH))
    device.pairing_config_factory = lambda _connection: PairingConfig(
        sc=True, mitm=False, bonding=True
    )
    return device


async def open_classic_connection(device, peer_address, authenticate):
    LOG.info("Connecting classic BR/EDR to %s", peer_address)
    connection = await device.connect(peer_address, transport=BT_BR_EDR_TRANSPORT)
    LOG.info(
        "Classic connected: peer=%s encrypted=%s",
        connection.peer_address,
        connection.is_encrypted,
    )
    if authenticate:
        LOG.info("Requesting classic authentication")
        await connection.authenticate()
        LOG.info("Classic authentication complete")
    return connection


def extract_rfcomm_channel(attribute_list):
    descriptor_list = sdp.ServiceAttribute.find_attribute_in_list(
        attribute_list,
        sdp.SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    )
    if not descriptor_list or descriptor_list.type != sdp.DataElement.SEQUENCE:
        return None

    for descriptor in descriptor_list.value:
        if descriptor.type != sdp.DataElement.SEQUENCE or not descriptor.value:
            continue
        if descriptor.value[0].type != sdp.DataElement.UUID:
            continue
        if descriptor.value[0].value != BT_RFCOMM_PROTOCOL_ID:
            continue
        if len(descriptor.value) < 2:
            continue
        return descriptor.value[1].value

    return None


async def query_sdp_attributes(sdp_client, service_uuid):
    return await sdp_client.search_attributes(
        [service_uuid],
        [
            sdp.SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
            sdp.SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
            sdp.SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID,
            0x0100,
        ],
    )


async def run_sdp_sweep(args):
    LOG.info("Opening transport %s", args.transport)
    transport = await asyncio.wait_for(
        open_transport_or_link(args.transport), timeout=args.transport_timeout
    )
    async with transport as (source, sink):
        device = make_device(source, sink)
        if args.skip_power_on:
            device.powered_on = True
            LOG.info("Skipping device.power_on(); assuming controller is already configured")
        else:
            LOG.info("Powering on probe device")
            await asyncio.wait_for(device.power_on(), timeout=args.power_on_timeout)
            LOG.info("Probe device ON at %s", device.public_address)
        connection = await asyncio.wait_for(
            open_classic_connection(device, args.peer, args.authenticate),
            timeout=args.connect_timeout,
        )
        sdp_client = sdp.Client(device)
        LOG.info("Opening SDP client")
        await sdp_client.connect(connection)
        try:
            for profile_name, profile_uuid in PROFILE_UUIDS:
                LOG.info("Querying SDP for %s", profile_name)
                try:
                    attribute_lists = await query_sdp_attributes(sdp_client, profile_uuid)
                except Exception as error:
                    print(f"{profile_name}: error={error}")
                    continue

                if not attribute_lists:
                    print(f"{profile_name}: absent")
                    continue

                for index, attribute_list in enumerate(attribute_lists, start=1):
                    channel = extract_rfcomm_channel(attribute_list)
                    print(
                        f"{profile_name}[{index}]: "
                        f"rfcomm_channel={channel if channel is not None else '-'}"
                    )
                    for attribute in attribute_list:
                        print(f"  {attribute}")
        finally:
            await sdp_client.disconnect()
            await connection.disconnect()


async def run_hfp_probe(args):
    LOG.info("Opening transport %s", args.transport)
    transport = await asyncio.wait_for(
        open_transport_or_link(args.transport), timeout=args.transport_timeout
    )
    async with transport as (source, sink):
        device = make_device(source, sink)
        if args.skip_power_on:
            device.powered_on = True
            LOG.info("Skipping device.power_on(); assuming controller is already configured")
        else:
            LOG.info("Powering on probe device")
            await asyncio.wait_for(device.power_on(), timeout=args.power_on_timeout)
            LOG.info("Probe device ON at %s", device.public_address)
        connection = await asyncio.wait_for(
            open_classic_connection(device, args.peer, args.authenticate),
            timeout=args.connect_timeout,
        )
        sdp_client = sdp.Client(device)
        LOG.info("Opening SDP client for HFP lookup")
        await sdp_client.connect(connection)
        rfcomm_client = None
        try:
            attribute_lists = await query_sdp_attributes(
                sdp_client, BT_HANDSFREE_AUDIO_GATEWAY_SERVICE
            )
            if not attribute_lists:
                attribute_lists = await query_sdp_attributes(
                    sdp_client, BT_HANDSFREE_SERVICE
                )

            if not attribute_lists:
                raise RuntimeError("No HFP service record found on peer")

            channel = extract_rfcomm_channel(attribute_lists[0])
            if channel is None:
                raise RuntimeError("HFP SDP record has no RFCOMM channel")

            LOG.info("Opening RFCOMM channel %s for HFP", channel)
            rfcomm_client = rfcomm.Client(device, connection)
            multiplexer = await rfcomm_client.start()
            dlc = await multiplexer.open_dlc(channel)
            protocol = HfpProtocol(dlc)

            await protocol.initialize_service()
            print(f"HFP initialized on RFCOMM channel {channel}")

            for command in args.command:
                print(f">>> {command}")
                protocol.send_command_line(command)
                while True:
                    try:
                        line = await asyncio.wait_for(protocol.next_line(), timeout=1.0)
                    except asyncio.TimeoutError:
                        break
                    print(f"<<< {line}")

            if args.linger > 0:
                deadline = asyncio.get_running_loop().time() + args.linger
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        line = await asyncio.wait_for(protocol.next_line(), timeout=remaining)
                    except asyncio.TimeoutError:
                        break
                    print(f"<<< {line}")
        finally:
            await sdp_client.disconnect()
            if rfcomm_client is not None:
                await rfcomm_client.shutdown()
            await connection.disconnect()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Classic Bluetooth profile probes for iPhone-facing CarThing tests."
    )
    parser.add_argument(
        "--transport",
        default=TRANSPORT,
        help="Bumble transport spec. Often serial:/dev/ttyS1,3000000 after stopping btattach.",
    )
    parser.add_argument("--peer", required=True, help="Peer BR/EDR address")
    parser.add_argument(
        "--authenticate",
        action="store_true",
        help="Request classic authentication before opening profile channels",
    )
    parser.add_argument(
        "--transport-timeout",
        type=float,
        default=15.0,
        help="Seconds to wait while opening the transport",
    )
    parser.add_argument(
        "--power-on-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for controller power-on",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for the BR/EDR connection",
    )
    parser.add_argument(
        "--skip-power-on",
        action="store_true",
        help="Assume the controller is already configured and skip Bumble device.power_on()",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python log level",
    )

    subparsers = parser.add_subparsers(dest="command_name", required=True)
    subparsers.add_parser("sdp-sweep", help="Query the main classic profile records")

    hfp_parser = subparsers.add_parser(
        "hfp", help="Bring up HFP service level and log AT traffic"
    )
    hfp_parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="Extra AT command to send after HFP initialization. Repeatable.",
    )
    hfp_parser.add_argument(
        "--linger",
        type=float,
        default=15.0,
        help="Seconds to keep logging unsolicited HFP lines after initialization",
    )

    return parser.parse_args()


async def async_main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.command_name == "sdp-sweep":
        await run_sdp_sweep(args)
        return

    if args.command_name == "hfp":
        await run_hfp_probe(args)
        return

    raise ValueError(f"Unknown command: {args.command_name}")


if __name__ == "__main__":
    asyncio.run(async_main())
