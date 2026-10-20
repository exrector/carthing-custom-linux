"""Coalesce unsent opposite relative-control steps."""


class RelativeStepQueue:
    def __init__(self):
        self.pending = 0

    def push(self, direction):
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or 1")
        self.pending += direction

    def pop(self):
        if not self.pending:
            return 0
        step = 1 if self.pending > 0 else -1
        self.pending -= step
        return step
