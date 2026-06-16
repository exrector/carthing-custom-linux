# Кастомный Linux на Car Thing — bring-up (результат)

**Что это:** фундамент проекта — как на Car Thing (Superbird) поднят **собственный Buildroot-Linux** взамен закрытого userspace Spotify. Загрузчик, ядро и dtb от Spotify/Amlogic **переиспользуются намеренно**; заменён только слой userspace: свой rootfs-overlay, свои init-скрипты и документированный контракт рантайма вместо скрытой политики Spotify. Это самая ранняя и самая объёмная по истории часть (**101 коммит**) — замена системного слоя целиком, а не надстройка над стоком; именно на ней стало возможно всё остальное.

Готовый результат: воспроизводимый build-рецепт (`buildroot-external`) + документация bring-up + история.

## Что доказано / достигнуто

- Собственный Buildroot-rootfs грузится на штатном boot-контракте Superbird (bootloader/kernel/dtb не трогаем).
- Скрытый upstream-слой userspace убран, заменён на явный минимальный контракт (`upstream-userspace-contract.md`).
- Ранние находки userspace задокументированы (`early-userspace-findings`), путь миграции описан (`migration-roadmap`).
- Зафиксирован рабочий baseline `device1-v1-working` (cold-boot proven).

## Воспроизводимый рецепт

`buildroot-external/` — внешнее дерево Buildroot (`external.desc`, `external.mk`, `configs/carthing_superbird_rootfs_defconfig`, `package/`, `board/.../post-build.sh`). Это то, чем собирается rootfs поверх базы `frederic/superbird-buildroot`.

## Документы

| Док | Что |
|---|---|
| `buildroot-bringup.md` | как поднят Buildroot под устройство |
| `early-userspace-findings-2026-05-11.md` | ранние находки про userspace Spotify |
| `checkpoint-2026-05-04-device1-bringup.md` | первый bring-up устройства |
| `device1-v1-working-baseline-2026-05-18.md` | рабочий baseline |
| `migration-roadmap.md` | план миграции со стока на своё |
| `upstream-userspace-contract.md` | явный контракт userspace |
| `TIMELINE-git.md` | хронология 101 коммита bring-up |

## Связь
Финальный, отполированный результат этого слоя — корневой `image/` + `source/overlay/` репозитория. Здесь — как он рождался.
