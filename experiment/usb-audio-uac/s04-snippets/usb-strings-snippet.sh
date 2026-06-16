# USB strings для composite gadget — врезка в S04-usbgadget
# Кладётся в configfs до того, как функции линкуются в config,
# и до того, как пишется UDC.
#
# Согласовано с [[carthing-factory-identity]]: имя продукта строится из
# /sys/class/efuse/usid, последние 4 символа = serial → "Car Thing (SN: Q917)".
#
# Подготовлено Claude (Opus 4.7) для Codex, 2026-05-28.

GADGET=/sys/kernel/config/usb_gadget/g1

# USB IDs. 0x1d6b = Linux Foundation, 0x0104 — свободный slot для composite.
# Можно сменить на любые валидные, но Linux Foundation легально.
echo 0x1d6b > "$GADGET/idVendor"
echo 0x0104 > "$GADGET/idProduct"
echo 0x0100 > "$GADGET/bcdDevice"     # device release 1.00
echo 0x0200 > "$GADGET/bcdUSB"        # USB 2.0

# Strings (English/US 0x409)
mkdir -p "$GADGET/strings/0x409"

# Manufacturer фиксированный
echo "Car Thing"            > "$GADGET/strings/0x409/manufacturer"

# Product name из efuse usid → "Car Thing (SN: XXXX)"
USID=$(cat /sys/class/efuse/usid 2>/dev/null)
if [ -n "$USID" ]; then
  SERIAL=$(echo "$USID" | tail -c 5 | tr -d '\n')
  echo "Car Thing (SN: ${SERIAL})" > "$GADGET/strings/0x409/product"
  echo "$USID"                     > "$GADGET/strings/0x409/serialnumber"
else
  # Fallback на MAC, если efuse недоступен — но это аварийный случай,
  # см. feedback правила про "MAC только как fallback".
  echo "Car Thing"        > "$GADGET/strings/0x409/product"
  echo "0000000000000000" > "$GADGET/strings/0x409/serialnumber"
fi
