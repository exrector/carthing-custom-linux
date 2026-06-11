#!/usr/bin/env python3
"""Mac-локальный запуск carthing_runtime с выводом экрана.

Запускается через tools/run_local.sh (он выставляет PYTHONPATH + env).
НЕ дублирует логику рантайма — гоняет тот же carthing_runtime.main(), только
дисплей = MacDisplay (pygame-окно) или WebDisplay (браузер), транспорт = HCI-proxy
по TCP. Так вся инфраструктура (чип через proxy, оркестратор, CTKD, A2DP, маршруты)
отлаживается на Mac, устройство трогаем только финальным деплоем.

Режимы (env, ставит run_local.sh):
  CAR_THING_MAC_DISPLAY=1  -> pygame-окно (нужен main-thread event loop)
  CAR_THING_WEB_DISPLAY=1  -> браузер http://localhost:8766
  ни то, ни другое         -> headless (только BT/логика, без экрана)
"""
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("run_local")

# Defensive duplicate of tools/run_local.sh. This prevents direct
# `python tools/run_local_main.py` from importing carthing_runtime and opening
# the Bumble transport behind the shell wrapper's back.
if (
    os.environ.get("CARTHING_BUMBLE_QUARANTINE", "1") != "0"
    or os.environ.get("CARTHING_ALLOW_BUMBLE_RUN", "0") != "1"
):
    raise SystemExit(
        "[run_local_main] Bumble runtime quarantined; set "
        "CARTHING_BUMBLE_QUARANTINE=0 CARTHING_ALLOW_BUMBLE_RUN=1 for a manual lab run"
    )

# PYTHONPATH (overlay/.../carthing + vendor) уже выставлен run_local.sh.
import carthing_runtime  # noqa: E402

USE_MAC = os.environ.get("CAR_THING_MAC_DISPLAY") == "1"
USE_WEB = os.environ.get("CAR_THING_WEB_DISPLAY") == "1"


def main():
    log.info("run_local: transport=%s mac_display=%s web_display=%s",
             os.environ.get("CAR_THING_TRANSPORT"), USE_MAC, USE_WEB)

    if USE_MAC:
        # pygame требует event loop в MAIN thread: создаём MacDisplay здесь (он
        # регистрируется как mac_display._instance — carthing_runtime его подхватит),
        # затем run_with_display гоняет asyncio.main() в фоне, а pygame.pump — в main.
        from mac_display import MacDisplay, run_with_display
        MacDisplay()
        log.info("run_local: pygame window mode — окно появится сейчас")
        run_with_display(carthing_runtime.main)
        return 0

    # WebDisplay или headless — обычный asyncio.run (WebDisplay крутит свои серверы в потоке).
    import asyncio
    if USE_WEB:
        log.info("run_local: web display — открой http://localhost:8766")
    else:
        log.info("run_local: headless (без экрана)")
    asyncio.run(carthing_runtime.main())
    return 0


if __name__ == "__main__":
    sys.exit(main())
