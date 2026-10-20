"""Short signed accumulation window for an incremental rotary encoder."""


class EncoderWindow:
    def __init__(self):
        self.pending = 0

    def add(self, value):
        if value == 0:
            return
        self.pending += 1 if value > 0 else -1

    def drain(self):
        value = self.pending
        self.pending = 0
        return value
