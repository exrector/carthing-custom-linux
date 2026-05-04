 Общая оценка: высокое качество, профессионально организовано                                                                     
                                                                                                                                   
  Это совершенно другой уровень по сравнению с тем что было — не Франкенштейн, а аккуратная инженерная работа. Контракт явный,     
  замены явные, ничего скрытого.                                                       
                                                                                                                                   
  Что сделано правильно (сильные стороны)                                                                                          
                                                                                                                                   
  1. Архитектурная честность. Файл docs/upstream-userspace-contract.md — лучшее, что я видел в этом проекте за всё время. Он не    
  игнорирует upstream-зависимости и не пытается их обойти, а явно перечисляет что делает NixOS-стек, и где наша замена. Каждая     
  зависимость отображается на конкретный init-скрипт или пакет. Это убирает 90% будущих сюрпризов.                                 
                                                                                                                                   
  2. carthing-bt-fwload — собственная реализация Broadcom patchram. Это самая важная часть.                                        
  - Чистый C, ~506 строк, libc-only (никакого bluez как зависимости).
  - Корректно делает протокол: HCI_RESET → HCI_DOWNLOAD_MINIDRIVER → stream HCD → HCI_LAUNCH_RAM → HCI_RESET → set_baud →          
  HCI_RESET.                                                                                                              
  - Обработка Command Complete событий на каждом шаге, статус-коды, debug-режим.                                                   
  - Bin уже собран (/private/tmp/carthing-bt-fwload — 35 КБ, готовый бинарь).          
  - Это ровно то, что я предлагал в этапе 1, но вы сделали на C — правильнее, чем на Python, для one-shot kernel-side операции.    
                                                                                                                                   
  3. Buildroot br2-external структура — каноничная.                                                                                
  - external.desc, external.mk, Config.in — по стандарту.                                                                          
  - package/carthing-bt-fwload/ со своим .mk и Config.in — собственный пакет.                                                      
  - BR2_EXTERNAL_CARTHING_CUSTOM_LINUX_PATH используется для путей.                                                                
  - defconfig минимальный (busybox, dropbear, libgpiod, python3, наш fwload — никакого systemd, никакого bluez).                   
                                                                                                                                   
  4. Init-контракт — простой и понятный.                                                                                           
  - BusyBox-init + inittab + /etc/init.d/S??-* — классический SysV-style.                                                          
  - 7 скриптов с чёткой нумерацией порядка: S10-firmware-stage → S20-bt-init → S25-bt-metadata → S30-usbnet → S40-ssh →            
  S45-input-links → S50-carthing-remote.                                                                                           
  - Конфиг через /etc/default/carthing — все пути и параметры в одном месте, никакой магии.                                        
  - Каждый скрипт самодостаточный (set -eu, проверки [ -x ... ]).                          
                                                                                                                                   
  5. macOS host-specific фиксы есть.                                                                                               
  - host-tools/bin/{patch,find,xargs,flock,install} — собственные GNU-утилиты для билда на маке.                                   
  - patch-buildroot-darwin.sh — патч для совместимости.                                                                            
  - buildroot-host-env.sh — выбор Homebrew gcc вместо clang.                                                                       
  - ASCII-симлинк на репо (потому что путь содержит "ПРОЕКТЫ" — кириллица ломает Buildroot Kconfig).                               
  - Это очень практичная часть, без неё на маке никак.                                                                             
                                                                                                                                   
  6. contract-selftest — отдельный helper который проверяет на устройстве что все ожидаемые пути существуют. Пример хорошей        
  операционной практики.                                                                                                           
                                                                                                                                   
  7. Stop conditions и protected-device явно указаны.                                                                              
  - target device for risky work: №1, protected device: №2. Разделение работающего и испытательного. Это именно то, чего не хватало
   в предыдущих сессиях.                                                                                                           
  - Экзит-критерии по фазам — недвусмысленные.                                         
                                                                                                                                   
  8. README.md называет вещи своими именами:                                                                                       
                                                                                                                                   
  ▎ "This repository is intentionally not based on the local carthing-nixos or carthing-media-remote project copies."              
                                                                                                                                   
  Это правильно — старые проекты как источник истории, а не архитектуры.                                                           
                                                                                       
  Замечания / потенциальные проблемы                                                                                               
                                                                                       
  1. gpio493 reset уверенности нет.                                                                                                
  В S20-bt-init используется reset через /sys/class/gpio/gpio493. В прошлых memory-заметках (carthing-debug-log.md, сессия 7-8 о
  WiFi) обсуждались GPIOX_*, и WL_REG_ON был "hardwired HIGH". Для BT-чипа reset GPIO не упоминался — нужно убедиться что 493 это  
  действительно reset BT (а не питание WiFi или ничто). Если №2 сейчас работает БЕЗ reset GPIO, то и в S20-bt-init его можно
  сначала пропустить. Источник числа 493 неочевиден из текущего проекта — это требует подтверждения с реального DTB.               
                                                                                       
  2. Зависимость carthing-bt-fwload от текущего baudrate.                                                                          
  По умолчанию --download-baud 115200 --baudrate 3000000. После reset чип может быть в другом начальном baudrate (некоторые BCM по
  умолчанию 921600). Если первая команда HCI_RESET не получит ответа — нужен fallback (попробовать 921600). На устройстве №2 точное
   состояние не верифицировано.                                                        
                                                                                                                                   
  3. Питание чипа после reset.                                                         
  Между echo 0 > value и echo 1 > value стоит sleep 0.1 (100мс). Для BCM20703A2 рекомендованное reset-pulse ≥ 5мс, после reset до
  начала HCI ≥ 100мс. По спецификации стоит сделать sleep 0.5 после echo 1, иначе чип не успевает отойти. Сейчас в скрипте 0.3 — на
   грани.
                                                                                                                                   
  4. Patches dir пустая.                                                               
  buildroot-external/patches/ существует, но пуста. В Buildroot 2026.02.1 уже могут быть нужны хотfix-патчи для macOS. На сейчас
  проект собирается без них, но тестов в dl/ не вижу — BR2_GLOBAL_PATCH_DIR стоит, при первой проблемной сборке надо будет         
  наполнять.
                                                                                                                                   
  5. Python3 в defconfig — но нет указания версии или модулей.                                                                     
  BR2_PACKAGE_PYTHON3=y тянет интерпретатор. Но bumble требует cffi → cryptography → нативные библиотеки. В defconfig не вижу:
  - BR2_PACKAGE_PYTHON_PIP (или способ положить bumble)                                                                            
  - BR2_PACKAGE_PYTHON_PYSERIAL (зависимость bumble)                                                                               
  - BR2_PACKAGE_LIBFFI, BR2_PACKAGE_OPENSSL (для cryptography)                                                                     
  - BR2_PACKAGE_FREETYPE + BR2_PACKAGE_LIBPNG (для pillow → шрифты экрана)                                                         
                                                                                                                                   
  Скорее всего поэтому CARTHING_RUNTIME_LIB=/usr/lib/carthing/vendor — план класть зависимости вручную после билда. Но как? Из     
  существующего /opt/car-thing/lib устройства №2? Нужно явно прописать в post-build.                                               
                                                                                                                                   
  6. DRM и шрифты.                                                                                                                 
  media_remote.py хочет /dev/dri/card0 (kernel — есть) и шрифт DejaVuSans.ttf. В defconfig не вижу BR2_PACKAGE_DEJAVU или
  BR2_PACKAGE_FONTCONFIG. На №2 шрифт был на пути /nix/store/.../dejavu-fonts-minimal-2.37/.... На custom rootfs его нет — UI      
  запустится, но шрифт fallback'нет на default bitmap (некрасиво). Надо или добавить в Buildroot, или класть руками.
                                                                                                                                   
  7. В S30-usbnet включён режим static 172.16.42.2/24 без конфигурации хост-стороны.                                               
  На маке конфиг с DHCP уже не работал (см. memory feedback_carthing_access.md). Static — лучший выбор. Но в /etc/default/carthing
  стоит CARTHING_USB_ENABLE_DHCP=0 — это правильно.                                                                                
                                                                                       
  8. SSH через dropbear.                                                                                                           
  Аргументы -R -E: -R — генерит host key если нет, -E — лог в stderr. Но нет -E который перенаправляет логи. На самом деле -E это
  --inetd? нет, в dropbear -E значит "stderr". Проверить надо. Также нет authorized_keys, нужно класть в                           
  /etc/dropbear/authorized_keys через post-build (пока пусто, значит первый login через пароль root — а пароль не задан). Это
  большой gap — нужно добавить ключ из ~/.ssh/id_ed25519.pub через post-build.                                                     
                                                                                       
  9. inittab без respawn для другого — стандартный инит, всё OK.                                                                   
  
  10. S25-bt-metadata генерит /etc/superbird для совместимости с upstream-приложениями. Если наш media_remote.py его не читает —   
  этот шаг можно пропустить. Лишний шаг, но безвредный.                                
                                                                                                                                   
  11. Нет шага для прошивки.                                                           
  Проект собирает только rootfs.tar / rootfs.ext2. bootfs.bin (kernel + dtb + initrd) — НЕ заменяется. Это правильное решение для
  первого этапа, но нужно явно указать как новый rootfs пакуется в существующий bootfs.bin или как заменяется system_a партиция    
  через pyamlboot. Это в migration-roadmap.md пока не описано — Phase 1 говорит "boot минимальный rootfs", но как именно прошить —
  не указано.                                                                                                                      
                                                                                       
  12. Нет упоминания media_remote_v3.py и патча bumble/host.py:max_latency.                                                        
  Эти два критических артефакта с №2 пока не учтены в проекте. Где они должны лежать на новой системе?
  - v3 → /usr/lib/carthing/media_remote.py (по CARTHING_RUNTIME_ENTRY)                                                             
  - Патченый bumble → /usr/lib/carthing/vendor/bumble/host.py (по CARTHING_RUNTIME_LIB)                                            
                                                                                                                                   
  Нужен helper-скрипт scripts/install-runtime.sh который их кладёт в overlay.                                                      

  13. CARTHING_AUTOSTART_REMOTE=0 по умолчанию.
  Это правильно для первого boot (избежать петли проблем) — но финальный таргет обязан быть =1. Стоит явно отметить в roadmap'е.

  Что я не вижу вообще (gap'ы)

  1. План прошивки. Как rootfs.ext2 → eMMC system_a? Ручная команда pyamlboot writeLargeMemory или скрипт?
  2. Bumble deploy. Где лежит pip-stack + патч max_latency? В overlay нет.
  3. SSH key authorized_keys. В /etc/dropbear/authorized_keys положить твой id_ed25519.pub через post-build.
  4. DRM/шрифты. DejaVu не в defconfig.
  5. UART baudrate fallback. Что если чип в другом baud при первом контакте.
  6. Hardware validation log. В README "hardware validation on device №1 is still pending" — никаких логов попыток нет.

  Сравнение с тем что есть на №2

  ┌──────────────────────────────┬────────────────────────┬──────────────────────────────┐
  │                              │   №2 (Франкенштейн)    │ carthing-custom-linux (план) │
  ├──────────────────────────────┼────────────────────────┼──────────────────────────────┤
  │ OS                           │ NixOS 25.05            │ Buildroot 2026.02.1          │
  ├──────────────────────────────┼────────────────────────┼──────────────────────────────┤
  │ Init                         │ systemd                │ BusyBox                      │
  ├──────────────────────────────┼────────────────────────┼──────────────────────────────┤
  │ BlueZ                        │ в системе, ручной kill │ отсутствует                  │
  ├──────────────────────────────┼────────────────────────┼──────────────────────────────┤
  │ BT bring-up                  │ btattach -P bcm        │ carthing-bt-fwload (свой C)  │
  ├──────────────────────────────┼────────────────────────┼──────────────────────────────┤
  │ Autostart media_remote       │ нет, ручной            │ systemd-style через S50      │
  ├──────────────────────────────┼────────────────────────┼──────────────────────────────┤
  │ Конфиг                       │ спрятан в nix-store    │ явный /etc/default/carthing  │
  ├──────────────────────────────┼────────────────────────┼──────────────────────────────┤
  │ Размер rootfs                │ ~1.7 ГБ                │ вероятно <100 МБ             │
  ├──────────────────────────────┼────────────────────────┼──────────────────────────────┤
  │ Время на разбор "что внутри" │ дни                    │ минуты (всё видно)           │
  ├──────────────────────────────┼────────────────────────┼──────────────────────────────┤
  │ macOS host build             │ docker only            │ docker не нужен              │
  └──────────────────────────────┴────────────────────────┴──────────────────────────────┘

  Вердикт

  Это не "примерно накидали" — это рабочий design с явным контрактом и собственной реализацией ключевого куска (fwload). Buildroot
  — правильный выбор: NixOS себя действительно не оправдала для этого устройства, Buildroot минимален и предсказуем.

  Готовность к hardware validation на №1: ~70%. Основные пробелы — план прошивки rootfs на eMMC, packaging bumble + max_latency
  патча в overlay, authorized_keys, и опциональные шрифты для DRM UI.

  Главный риск не в коде, а в hardware validation: gpio493 reset, baudrate negotiation, init-порядок при первом cold boot. Эти три
  места проявят себя только на железе.
