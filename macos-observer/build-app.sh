#!/usr/bin/env bash
# Собирает корректный .app-бандл вокруг SwiftPM-исполняемого файла.
#
# Зачем: для устойчивого доступа к CoreBluetooth (и стабильного TCC-разрешения,
# которое привязывается к bundle identifier) лучше запускать .app, а не голый
# бинарь. Info.plist встроен и в бинарь (см. Package.swift linkerSettings), но
# .app даёт корректное имя в System Settings → Privacy → Bluetooth.
#
# Никаких облачных/платных шагов: только локальный swift build + сборка дерева .app.
set -euo pipefail

cd "$(dirname "$0")"

CONFIG="${1:-release}"
APP_NAME="CarThingObserver"
BUILD_DIR=".build/${CONFIG}"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"

echo "==> swift build -c ${CONFIG}"
swift build -c "${CONFIG}"

BIN_PATH="${BUILD_DIR}/${APP_NAME}"
if [[ ! -f "${BIN_PATH}" ]]; then
  echo "Не найден бинарь ${BIN_PATH}" >&2
  exit 1
fi

echo "==> Сборка ${APP_BUNDLE}"
rm -rf "${APP_BUNDLE}"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

cp "${BIN_PATH}" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"
cp "Sources/ObserverApp/Info.plist" "${APP_BUNDLE}/Contents/Info.plist"

# Ad-hoc подпись — TCC требует валидной подписи для запоминания разрешения.
echo "==> codesign (ad-hoc)"
codesign --force --deep --sign - "${APP_BUNDLE}" 2>/dev/null || \
  echo "codesign пропущен (необязательно для первого запуска)"

echo "Готово: ${APP_BUNDLE}"
echo "Запуск:  open \"${APP_BUNDLE}\""
