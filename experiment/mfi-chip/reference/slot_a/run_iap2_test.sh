#!/bin/sh
# Wrapper to run iap2_agent with test HID parameters
export IAP2_ACTIVE_CONNECT=0
export IAP2_REGISTER_CLIENT_PROFILE=1
export IAP2_FORCE_RECONNECT=0
export IAP2_CERT_RAW_BLOB=1
export IAP2_TEST_HID_USAGE=0x00CD
export IAP2_TEST_HID_MODE=6
export IAP2_HID_RESET_FIRST=1
export IAP2_HID_FIRST=1

exec /home/superbird/slot_a/iap2_agent "$@"
