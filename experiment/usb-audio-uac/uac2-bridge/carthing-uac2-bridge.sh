#!/bin/sh
# carthing-uac2-bridge — мост между виртуальной UAC2 ALSA-картой (USB gadget)
# и реальным T9015 DAC + PDM mic.
#
# Назначение: когда macOS видит Car Thing как USB Audio Class 2 устройство,
# звук, который Mac посылает в gadget, должен реально звучать в наушниках/
# динамике через T9015; mic capture с PDM должен идти обратно в Mac.
#
# Запускается из profile hook'а 'ncm,audio'. Останавливается при переключении
# на любой профиль без 'audio'.
#
# Зависимости в rootfs: alsa-utils (alsaloop). См. buildroot-overlay.md.
#
# Подготовлено Claude (Opus 4.7) как staging для Codex, 2026-05-28.
# Не запекать слепо — сверить имена ALSA-карт с реальным `aplay -l`.

set -e

PIDFILE_PLAY=/run/carthing/uac2-bridge-play.pid
PIDFILE_CAP=/run/carthing/uac2-bridge-cap.pid
LOGFILE=/run/carthing/uac2-bridge.log

# Имя виртуальной UAC2 карты. Задаётся через function_name атрибут
# в configfs (см. uac2-configfs-snippet.sh). Если не задано — kernel
# даёт 'UAC2Gadget'.
UAC2_CARD="${UAC2_CARD:-CarThingUAC2}"

# Имя реальной aml audio карты. В acceptance 25.05 это 'AMLAUGESOUND'.
HW_CARD="${HW_CARD:-AMLAUGESOUND}"

# Playback: Mac → gadget → T9015 (PCM 0,0 на AML)
PLAY_SRC="hw:CARD=${UAC2_CARD},DEV=0"
PLAY_DST="hw:CARD=${HW_CARD},DEV=0"

# Capture: PDM mic (PCM 0,1 на AML) → gadget → Mac
CAP_SRC="hw:CARD=${HW_CARD},DEV=1"
CAP_DST="hw:CARD=${UAC2_CARD},DEV=0"

# Латентность alsaloop в микросекундах. 50000 = 50ms — компромисс
# между jitter resilience и user-perceived delay. Подкрутить при
# необходимости (меньше = меньше задержка, больше риск underrun).
LATENCY_US=50000

mkdir -p /run/carthing
exec >>"$LOGFILE" 2>&1
echo "[$(date)] uac2-bridge action=$1"

start() {
  # idempotent: если уже запущен — выходим
  if [ -f "$PIDFILE_PLAY" ] && kill -0 "$(cat "$PIDFILE_PLAY")" 2>/dev/null; then
    echo "  already running"
    return 0
  fi

  # Проверка наличия gadget-карты. Если UAC2 функция ещё не привязана к UDC,
  # карта не существует — выходим с ошибкой, S04 откатит профиль.
  if ! aplay -l 2>/dev/null | grep -q "$UAC2_CARD"; then
    echo "  ERROR: UAC2 gadget card '$UAC2_CARD' not present, aborting"
    return 1
  fi
  if ! aplay -l 2>/dev/null | grep -q "$HW_CARD"; then
    echo "  ERROR: HW card '$HW_CARD' not present, aborting"
    return 1
  fi

  # Playback bridge
  alsaloop -C "$PLAY_SRC" -P "$PLAY_DST" -t "$LATENCY_US" \
           -f S16_LE -r 48000 -c 2 -S 1 &
  echo $! > "$PIDFILE_PLAY"

  # Capture bridge
  alsaloop -C "$CAP_SRC" -P "$CAP_DST" -t "$LATENCY_US" \
           -f S16_LE -r 48000 -c 2 -S 1 &
  echo $! > "$PIDFILE_CAP"

  echo "  started play=$(cat "$PIDFILE_PLAY") cap=$(cat "$PIDFILE_CAP")"
}

stop() {
  for pf in "$PIDFILE_PLAY" "$PIDFILE_CAP"; do
    [ -f "$pf" ] || continue
    pid=$(cat "$pf")
    kill "$pid" 2>/dev/null || true
    rm -f "$pf"
  done
  echo "  stopped"
}

status() {
  for label in play cap; do
    pf="/run/carthing/uac2-bridge-${label}.pid"
    if [ -f "$pf" ] && kill -0 "$(cat "$pf")" 2>/dev/null; then
      echo "  $label: running pid=$(cat "$pf")"
    else
      echo "  $label: stopped"
    fi
  done
}

case "$1" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  status)  status ;;
  *) echo "usage: $0 {start|stop|restart|status}"; exit 1 ;;
esac
