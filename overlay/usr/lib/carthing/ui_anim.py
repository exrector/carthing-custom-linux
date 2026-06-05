"""Animation driver — two tiers, both idle-friendly.

  transient: swipe slide between desktops (runs only during a switch)
  ambient:   pulsing status-bar indicator (runs only while something pulses
             AND the screen is awake)

needs_tick() tells the loop whether to schedule another frame. When nothing is
animating, the loop renders on events only and the CPU idles — which is what the
no-traffic sleep policy wants.
"""
import math
import time


class AnimDriver:
    def __init__(self):
        self._pulsing = False
        self._t0 = time.monotonic()
        # transient transition
        self.transition_active = False
        self.transition_dir = 0          # +1 next desktop, -1 prev
        self.transition_from = None      # [CLAUDE] явный исходный экран (индексы вью НЕ соседние)
        self.transition_progress = 0.0   # 0..1
        self._trans_dur = 0.22           # seconds — light, no excess

    # ── ambient pulse ──────────────────────────────────────────────────────
    def set_pulsing(self, on):
        self._pulsing = bool(on)

    def pulse_alpha(self):
        """0..1 brightness for a pulsing indicator (slow, calm ~0.5 Hz)."""
        if not self._pulsing:
            return 1.0
        phase = (time.monotonic() - self._t0) * 2 * math.pi * 0.5
        return 0.35 + 0.65 * (0.5 + 0.5 * math.sin(phase))

    # ── transient swipe transition ─────────────────────────────────────────
    def start_transition(self, direction, from_index=None):
        self.transition_active = True
        self.transition_dir = direction
        self.transition_from = from_index
        self.transition_progress = 0.0
        self._trans_start = time.monotonic()

    def _advance_transition(self):
        if not self.transition_active:
            return
        p = (time.monotonic() - self._trans_start) / self._trans_dur
        if p >= 1.0:
            self.transition_progress = 1.0
            self.transition_active = False
        else:
            # ease-out cubic — light, natural
            self.transition_progress = 1 - (1 - p) ** 3

    def tick(self):
        self._advance_transition()

    def needs_tick(self):
        return self.transition_active or self._pulsing
