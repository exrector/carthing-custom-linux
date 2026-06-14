"""Режимы работы Car Thing — чтобы устройство не гоняло код по кругу.

Идея владельца 2026-06-13: устройство не должно вечно сканировать/пейджить/держать
коммутатор, если он сейчас не нужен. Один явный режим определяет, какие подсистемы
вообще запущены.

Режимы (по нарастанию активности радио/CPU):
  • PLAYNOW   — «просто пульт». Только BLE-управление iPhone (AMS/ANCS/CTS):
                метаданные, кнопки, уведомления, часы. НЕ запускается коммутатор:
                ни standby-пейджинг колонок, ни receiver-цикл, ни скан. Радио
                почти простаивает -> ноль контеншена с GUI, ноль «PAGE_TIMEOUT по
                кругу». Это дефолт «спокойного» состояния.
  • COMMUTATOR — полный транскод-хаб: standby доверенных выходов, receiver-цикл,
                форвард/транскод A2DP, переключение маршрутов. Включается, когда
                реально нужно гонять звук на колонки.
  • RESERVED  — задел под будущий режим (идей было много: голосовой ассистент,
                автономный плеер с ЦАП и т.д.). Сейчас ведёт себя как PLAYNOW.

Режим персистится в settings.operation_mode (единый state.json, атомарно).
Переключение мгновенное: гейты читают current() на старте циклов; смена режима
поднимает/гасит коммутатор через apply_mode() без рестарта рантайма.

[CLAUDE 2026-06-13] новый модуль, по слову владельца «переключение режимов».
"""
from __future__ import annotations

PLAYNOW = "playnow"
COMMUTATOR = "commutator"
RESERVED = "reserved"

ALL = (PLAYNOW, COMMUTATOR, RESERVED)
LABELS = {PLAYNOW: "Play Now", COMMUTATOR: "Коммутатор", RESERVED: "Резерв"}

# Дефолт — PLAYNOW (повторено владельцем многократно: спокойное состояние,
# без гоняния коммутатора по кругу).
DEFAULT = PLAYNOW


def current(settings) -> str:
    """Активный режим из settings (с откатом на DEFAULT)."""
    try:
        mode = settings.get("operation_mode", DEFAULT) if settings is not None else DEFAULT
    except Exception:
        mode = DEFAULT
    return mode if mode in ALL else DEFAULT


def commutator_enabled(settings) -> bool:
    """True только в полном режиме коммутатора: запускать standby/receiver/scan."""
    return current(settings) == COMMUTATOR


def label(mode: str) -> str:
    return LABELS.get(mode, mode)


def cycle(mode: str) -> str:
    """Следующий режим по кругу (для тапа в настройках)."""
    try:
        return ALL[(ALL.index(mode) + 1) % len(ALL)]
    except ValueError:
        return DEFAULT
