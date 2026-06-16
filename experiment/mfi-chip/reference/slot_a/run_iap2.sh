#!/bin/sh
while true; do
    /home/superbird/slot_a/iap2_agent >> /tmp/iap2.log 2>&1
    echo "[restart] iap2_agent exited, restarting in 2s..." >> /tmp/iap2.log
    sleep 2
done
