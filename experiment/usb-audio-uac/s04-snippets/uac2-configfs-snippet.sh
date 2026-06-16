# UAC2 function в configfs — врезка в S04-usbgadget при профиле,
# содержащем 'audio'. Параметры подобраны под macOS class-compliant driver.
#
# Подготовлено Claude (Opus 4.7) для Codex, 2026-05-28.
# Источники: kernel.org gadget-testing UAC2, Apple TN3190.

GADGET=/sys/kernel/config/usb_gadget/g1
UAC2_DIR="$GADGET/functions/uac2.usb0"

mkdir -p "$UAC2_DIR"

# Sample rates — comma-separated список. macOS выберет одну.
# Начинаем с одной 48000 для гарантии; расширить позже до "48000,44100,96000".
echo 48000 > "$UAC2_DIR/c_srate"   # capture (host→device, Mac пишет, девайс читает)
echo 48000 > "$UAC2_DIR/p_srate"   # playback (device→host, девайс пишет, Mac читает)

# Sample size в байтах. 2 = S16_LE — самый совместимый. 3 = S24, 4 = S32.
echo 2 > "$UAC2_DIR/c_ssize"
echo 2 > "$UAC2_DIR/p_ssize"

# Channel mask. 3 = бит 0 + бит 1 = FL+FR (stereo).
echo 3 > "$UAC2_DIR/c_chmask"
echo 3 > "$UAC2_DIR/p_chmask"

# Sync type. async = device-clocked, стандарт хороших USB DAC'ов;
# совместимо с macOS audio engine. adaptive — компромисс, использовать
# не нужно если железо умеет async.
echo async > "$UAC2_DIR/c_sync" 2>/dev/null || true

# Выставить регуляторы громкости/mute хосту. macOS прицепит системный
# громкость-слайдер к этим контролам.
echo 1 > "$UAC2_DIR/c_mute_present"     2>/dev/null || true
echo 1 > "$UAC2_DIR/c_volume_present"   2>/dev/null || true
echo 1 > "$UAC2_DIR/p_mute_present"     2>/dev/null || true
echo 1 > "$UAC2_DIR/p_volume_present"   2>/dev/null || true

# Громкость в 1/256 дБ. -50dB..0dB шагом 1dB — разумный диапазон.
echo -12800 > "$UAC2_DIR/c_volume_min" 2>/dev/null || true
echo      0 > "$UAC2_DIR/c_volume_max" 2>/dev/null || true
echo    256 > "$UAC2_DIR/c_volume_res" 2>/dev/null || true
echo -12800 > "$UAC2_DIR/p_volume_min" 2>/dev/null || true
echo      0 > "$UAC2_DIR/p_volume_max" 2>/dev/null || true
echo    256 > "$UAC2_DIR/p_volume_res" 2>/dev/null || true

# Имя виртуальной ALSA-карты на устройстве. Должно совпадать с UAC2_CARD
# в carthing-uac2-bridge.sh.
echo "CarThingUAC2" > "$UAC2_DIR/function_name" 2>/dev/null || true

# Прилинковать в первый config. Имя 'c.1' предполагается уже существующим.
ln -sf "$UAC2_DIR" "$GADGET/configs/c.1/uac2.usb0"

# ВАЖНО: после добавления функций обязательно один раз echo udc_name > UDC
# (это делает основной поток S04, не здесь). Порядок функций в config:
# рекомендуется ncm первым, потом acm/uac2/hid/mass_storage.
