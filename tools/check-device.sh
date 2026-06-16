#!/bin/sh
# Состояние Car Thing на USB — ТОЛЬКО по VID:PID (никогда по имени).
#   1b8e:c003 = Maskrom / USB Burn Mode (готов к прошивке)
#   0525:a4a1 = загружен, NCM (готов к SSH)
python3 - <<'PY'
import usb.core
burn = usb.core.find(idVendor=0x1b8e, idProduct=0xc003)
ncm  = usb.core.find(idVendor=0x0525, idProduct=0xa4a1)
if burn is not None:
    print("MASKROM/BURN  (1b8e:c003)  -> можно прошивать")
elif ncm is not None:
    print("BOOTED/NCM    (0525:a4a1)  -> можно поднимать сеть и SSH")
else:
    print("NONE  -> устройства нет на USB (переткни кабель)")
PY
