#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ ВРЕМЕННЫЙ ТЕСТОВЫЙ СКРИПТ КЛИЕНТ-СЕРВЕР (Claude, 2026-06-18).
# Деплой/запуск/останов device-side CTSP TCP-сервера на устройстве Car Thing.
# НЕ трогает hci0/BT (сервер слушает только TCP поверх usb0). См. MANIFEST.md и
# DEVICE-DEPLOY-LOG.md. Всё кладётся в /tmp (эфемерно, чистится ребутом).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

SSH_HOST="${CARTHING_SSH:-carthing}"
DEV_DIR="/tmp/claude-ctsp-test"
DEV_SRV="${DEV_DIR}/ctsp_test_server.py"
PORT="${CTSP_PORT:-7777}"
PIDFILE="${DEV_DIR}/server.pid"

cmd="${1:-help}"

case "$cmd" in
  deploy)
    echo "==> mkdir ${DEV_DIR} на устройстве"
    ssh "$SSH_HOST" "mkdir -p ${DEV_DIR}"
    echo "==> копирую ctsp_test_server.py (через ssh stdin, без scp)"
    ssh "$SSH_HOST" "cat > ${DEV_SRV}" < device/ctsp_test_server.py
    ssh "$SSH_HOST" "ls -l ${DEV_SRV}"
    ;;
  start)
    echo "==> запуск сервера на :${PORT} (nohup, background)"
    ssh "$SSH_HOST" "cd ${DEV_DIR} && nohup python3 -u ${DEV_SRV} ${PORT} > ${DEV_DIR}/server.log 2>&1 & echo \$! > ${PIDFILE}; sleep 1; echo PID=\$(cat ${PIDFILE}); cat ${DEV_DIR}/server.log"
    ;;
  status)
    ssh "$SSH_HOST" "if [ -f ${PIDFILE} ] && kill -0 \$(cat ${PIDFILE}) 2>/dev/null; then echo 'РАБОТАЕТ PID='\$(cat ${PIDFILE}); else echo 'не запущен'; fi; echo '--- лог ---'; tail -n 30 ${DEV_DIR}/server.log 2>/dev/null || true"
    ;;
  stop)
    echo "==> останов сервера и очистка"
    ssh "$SSH_HOST" "if [ -f ${PIDFILE} ]; then kill \$(cat ${PIDFILE}) 2>/dev/null || true; fi; pkill -f ctsp_test_server.py 2>/dev/null || true; sleep 1; echo 'остановлен'"
    ;;
  clean)
    echo "==> полное удаление тестовой папки с устройства"
    ssh "$SSH_HOST" "pkill -f ctsp_test_server.py 2>/dev/null || true; rm -rf ${DEV_DIR}; echo 'удалено ${DEV_DIR}'"
    ;;
  verify-no-bt)
    echo "==> проверка, что сервер НЕ держит hci0/bluetooth сокетов"
    ssh "$SSH_HOST" "pid=\$(cat ${PIDFILE} 2>/dev/null); echo PID=\$pid; ls -l /proc/\$pid/fd 2>/dev/null | grep -iE 'ttyS1|bluetooth' && echo 'ВНИМАНИЕ: держит BT!' || echo 'BT-сокетов нет — ok'"
    ;;
  *)
    echo "usage: $0 {deploy|start|status|stop|clean|verify-no-bt}"
    ;;
esac
