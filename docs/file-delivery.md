# Доставка файлов на Car Thing — единый канал

Дата фиксации: 2026-06-11. Причина: scp/sftp/dropbear путали каждого агента,
каждый раз заново наступали на одни и те же грабли.

## TL;DR — что использовать

| Задача | Команда |
|---|---|
| Задеплоить файл(ы) из overlay | `tools/deploy usr/lib/carthing/<файл> [--restart]` |
| Забрать файл с устройства | `tools/deploy --pull /путь/на/устройстве /локальный/путь` |
| Каталог целиком | `tools/deploy usr/lib/carthing/vendor/PIL` |

Пути для деплоя — относительно `overlay/` (как лягут в корень rootfs).
`--restart` перезапускает runtime штатно (супервизор-aware) и показывает хвост лога.

## Матрица «что работает / что нет» (проверено эмпирически)

| Канал | Статус | Почему |
|---|---|---|
| `tools/deploy` (tar через ssh) | ✅ канон | remount rw/ro, чистка `._*`, py_compile в окне rw |
| `ssh carthing 'cat f' > local` | ✅ | pull без зависимостей |
| `scp carthing:...` (macOS default) | ❌ МОЛЧА | OpenSSH 9+ ходит по SFTP, sftp-server в образе нет |
| `scp -O` (legacy) | ⚠️ работает, но | не делает remount/чистку/проверку — руками забывают |
| `sftp` / `sshfs` | ❌ пока | нет sftp-server; появится со следующим bake (gesftpserver) |

## Грабли, из-за которых всё это написано

1. **macOS scp молча фейлится**: протокол SFTP по умолчанию, на dropbear-образе
   нет sftp-server. Файл не приходит, ошибки не видно (с `-q` — вообще тишина).
2. **macOS tar гадит AppleDouble**: без `COPYFILE_DISABLE=1` + `--exclude='._*'`
   в `/usr/lib/carthing` появляются мусорные `._*.py`.
3. **rootfs read-only**: перед записью `mount -o remount,rw /`, после — `sync` и
   обратно `ro`. `py_compile` тоже пишет (`__pycache__`) — только в окне rw.
4. **busybox: нет pkill**, kill только по PID. Kill PID runtime валит и
   супервизор-петлю — перезапускать через `/etc/init.d/disabled-S50-carthing-remote`
   (идемпотентен).

## Будущее (со следующим bake)

В defconfig добавлен `BR2_PACKAGE_GESFTPSERVER=y` + симлинк
`overlay/usr/libexec/sftp-server -> /usr/bin/gesftpserver` (путь, который dropbear
ищет для SFTP-подсистемы). После bake заработают современный scp, sftp и
sshfs dev-mount с Mac (`tools/deploy` останется каноном для деплоя — из-за
remount/проверок).
