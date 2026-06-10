#!/usr/bin/env python3
"""Verify the vendored Bumble release and its CTKD implementation."""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = REPO_ROOT / "overlay/usr/lib/carthing"
sys.path.insert(0, str(RUNTIME / "vendor"))
sys.path.insert(0, str(RUNTIME))

import bumble  # noqa: E402
from bumble import hci  # noqa: E402
from bumble.l2cap import (  # noqa: E402
    ClassicChannel,
    L2CAP_Configure_Request,
    L2CAP_Configure_Response,
    L2CAP_Control_Frame,
    TransmissionMode,
)
from bumble.pairing import PairingConfig  # noqa: E402
from bumble.sdp import SDP_SUPPORTED_FEATURES_ATTRIBUTE_ID  # noqa: E402
from bumble.smp import AuthReq, Session  # noqa: E402


EXPECTED_VERSION = "0.0.229"


def reversed_hex(value: str) -> bytes:
    return bytes.fromhex(value.replace(" ", ""))[::-1]


def main() -> int:
    if bumble.__version__ != EXPECTED_VERSION:
        raise SystemExit(
            f"Bumble version mismatch: {bumble.__version__} != {EXPECTED_VERSION}"
        )

    ltk = reversed_hex("368df9bc e3264b58 bd066c33 334fbf64")
    link_key = reversed_hex("05040302 01000908 07060504 03020100")
    vectors = [
        (
            Session.derive_link_key(ltk, False),
            reversed_hex("bc1ca4ef 633fc1bd 0d8230af ee388fb0"),
        ),
        (
            Session.derive_link_key(ltk, True),
            reversed_hex("287ad379 dca40253 0a39f1f4 3047b835"),
        ),
        (
            Session.derive_ltk(link_key, False),
            reversed_hex("a813fb72 f1a3dfa1 8a2c9a43 f10d0a30"),
        ),
        (
            Session.derive_ltk(link_key, True),
            reversed_hex("e85e09eb 5eccb3e2 69418a13 3211bc79"),
        ),
    ]
    if any(actual != expected for actual, expected in vectors):
        raise SystemExit("Bumble CTKD test vector mismatch")

    config = PairingConfig(ct2=True)
    auth_req = AuthReq.from_booleans(
        bonding=config.bonding,
        sc=config.sc,
        mitm=config.mitm,
        ct2=config.ct2,
    )
    if not auth_req & AuthReq.CT2:
        raise SystemExit("Bumble CT2 integration is disabled")

    import a2dp_bridge  # noqa: E402
    import accessory_orchestrator  # noqa: F401
    import carthing_runtime  # noqa: F401
    import media_remote  # noqa: F401

    audio_sink_features = [
        attribute.value.value
        for attribute in a2dp_bridge.make_audio_sink_sdp_records()
        if attribute.id == SDP_SUPPORTED_FEATURES_ATTRIBUTE_ID
    ]
    if audio_sink_features != [a2dp_bridge.A2DP_SINK_FEATURE_SPEAKER]:
        raise SystemExit(f"A2DP AudioSink SupportedFeatures mismatch: {audio_sink_features}")

    flush_timeout_command = hci.HCI_Write_Automatic_Flush_Timeout_Command(
        connection_handle=12,
        flush_timeout=200,
    )
    if flush_timeout_command.op_code != hci.HCI_WRITE_AUTOMATIC_FLUSH_TIMEOUT_COMMAND:
        raise SystemExit("Bumble HCI Write Automatic Flush Timeout opcode mismatch")
    if bytes(flush_timeout_command).hex() != "01280c040c00c800":
        raise SystemExit(
            "Bumble HCI Write Automatic Flush Timeout serialization mismatch: "
            f"{bytes(flush_timeout_command).hex()}"
        )

    responses = []
    channel = object.__new__(ClassicChannel)
    channel.state = ClassicChannel.State.WAIT_CONFIG_REQ_RSP
    channel.mode = TransmissionMode.BASIC
    channel.destination_cid = 0x0041
    channel.peer_flush_timeout_ms = None
    channel.send_control_frame = responses.append
    channel._change_state = lambda state: setattr(channel, "state", state)
    channel.on_configure_request(
        L2CAP_Configure_Request(
            identifier=1,
            destination_cid=0x0040,
            flags=0,
            options=L2CAP_Control_Frame.encode_configuration_options(
                [
                    (
                        L2CAP_Configure_Request.ParameterType.FLUSH_TIMEOUT,
                        bytes.fromhex("c800"),
                    )
                ]
            ),
        )
    )
    if channel.peer_flush_timeout_ms != 200:
        raise SystemExit(
            f"Bumble L2CAP peer flush timeout mismatch: {channel.peer_flush_timeout_ms}"
        )
    if (
        len(responses) != 1
        or not isinstance(responses[0], L2CAP_Configure_Response)
        or responses[0].result != L2CAP_Configure_Response.Result.SUCCESS
    ):
        raise SystemExit("Bumble L2CAP peer flush timeout was not accepted")

    # L2CAP mode negotiation: на запрос не-Basic режима отвечаем
    # UNACCEPTABLE_PARAMETERS с Basic (peer повторит Configure), а не abort.
    # Abort ломал AVCTP/AVRCP от Fosi (run11/run12 2026-06-10).
    import struct

    responses = []
    channel = object.__new__(ClassicChannel)
    channel.state = ClassicChannel.State.WAIT_CONFIG_REQ_RSP
    channel.mode = TransmissionMode.BASIC
    channel.destination_cid = 0x0041
    channel.peer_flush_timeout_ms = None
    channel.send_control_frame = responses.append
    channel._change_state = lambda state: setattr(channel, "state", state)
    channel.on_configure_request(
        L2CAP_Configure_Request(
            identifier=2,
            destination_cid=0x0040,
            flags=0,
            options=L2CAP_Control_Frame.encode_configuration_options(
                [
                    (
                        L2CAP_Configure_Request.ParameterType.RETRANSMISSION_AND_FLOW_CONTROL,
                        struct.pack(
                            "<BBBHHH",
                            int(TransmissionMode.ENHANCED_RETRANSMISSION),
                            8, 3, 2000, 12000, 1010,
                        ),
                    )
                ]
            ),
        )
    )
    if (
        len(responses) != 1
        or not isinstance(responses[0], L2CAP_Configure_Response)
        or responses[0].result
        != L2CAP_Configure_Response.Result.FAILURE_UNACCEPTABLE_PARAMETERS
    ):
        raise SystemExit(
            "Bumble L2CAP mode negotiation must counter with UNACCEPTABLE_PARAMETERS, not abort"
        )
    countered = L2CAP_Control_Frame.decode_configuration_options(responses[0].options)
    if (
        len(countered) != 1
        or countered[0][0]
        != L2CAP_Configure_Request.ParameterType.RETRANSMISSION_AND_FLOW_CONTROL
        or countered[0][1][0] != int(TransmissionMode.BASIC)
    ):
        raise SystemExit("Bumble L2CAP mode counter-proposal must offer BASIC mode")

    print(
        f"Bumble vendor OK: {bumble.__version__}, CTKD vectors, CT2 integration, "
        "AudioSink SDP, HCI automatic flush command, L2CAP peer flush timeout, "
        "and L2CAP mode negotiation OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
