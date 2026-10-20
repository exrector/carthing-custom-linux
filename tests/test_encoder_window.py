import sys
import unittest
from pathlib import Path


sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "overlay/usr/lib/carthing"),
)
from encoder_window import EncoderWindow


class EncoderWindowTests(unittest.TestCase):
    def test_opposite_ticks_cancel_within_one_window(self):
        window = EncoderWindow()
        window.add(1)
        window.add(-1)
        self.assertEqual(window.drain(), 0)

    def test_same_direction_ticks_are_preserved(self):
        window = EncoderWindow()
        window.add(-1)
        window.add(-1)
        window.add(-1)
        self.assertEqual(window.drain(), -3)
        self.assertEqual(window.drain(), 0)


if __name__ == "__main__":
    unittest.main()
