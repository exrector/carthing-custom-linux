#!/usr/bin/env python3
"""Classic-only iPhone A2DP Sink control test using the existing bond."""

import asyncio
import logging
import os
import sys

if (
    os.environ.get("CARTHING_BUMBLE_QUARANTINE", "1") != "0"
    or os.environ.get("CARTHING_ALLOW_BUMBLE_RUN", "0") != "1"
):
    raise SystemExit(
        "[iphone-a2dp-sink-standalone-test] Bumble runtime quarantined; set "
        "CARTHING_BUMBLE_QUARANTINE=0 CARTHING_ALLOW_BUMBLE_RUN=1 for a manual lab run"
    )

sys.path.insert(0, os.environ.get("CAR_THING_LIB", "/usr/lib/carthing"))
sys.path.insert(0, os.path.join(sys.path[0], "vendor"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
for logger_name in ("bumble.avdtp", "bumble.l2cap", "bumble.a2dp", "bumble.avrcp"):
    logging.getLogger(logger_name).setLevel(logging.DEBUG)

SOURCE = os.environ["CARTHING_TEST_SOURCE"]


class SinkState:
    trusted_sources = [{"address": SOURCE}]
    trusted_speakers = []
    transfer_active = False
    transfer_source = ""
    active_desktop = ""
    TRANSFER = "transfer"

    def is_trusted_source(self, address):
        return str(address).split("/", 1)[0].upper() == SOURCE.upper()

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


async def main():
    from a2dp_bridge import A2DPBridge
    from ble_transport import init_ble

    def configure(device):
        device.le_enabled = False
        device.classic_enabled = True
        device.classic_ssp_enabled = True
        device.le_simultaneous_enabled = False
        device.classic_smp_enabled = False

    device, _transport = await init_ble(configure_device=configure)
    bridge = A2DPBridge(device, SinkState(), autoconnect=False)
    bridge.install_sdp_records()
    bridge.install_safe_link_key_provider()
    await bridge.start()

    logging.getLogger(__name__).info(
        "CLASSIC_ONLY_A2DP_READY local=%s source=%s",
        device.public_address,
        SOURCE,
    )
    try:
        await bridge.connect_source(SOURCE)
        logging.getLogger(__name__).info("CLASSIC_ONLY_A2DP_CONNECTED source=%s", SOURCE)
        await asyncio.Event().wait()
    finally:
        for connection in list(device.connections.values()):
            try:
                await connection.disconnect()
            except Exception:
                pass
        await device.power_off()


asyncio.run(main())
