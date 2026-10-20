import sys
import unittest
from pathlib import Path


sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "overlay/usr/lib/carthing"),
)
from relative_step_queue import RelativeStepQueue


class RelativeStepQueueTests(unittest.TestCase):
    def test_opposite_unsent_steps_cancel(self):
        queue = RelativeStepQueue()
        queue.push(1)
        queue.push(1)
        queue.push(-1)
        self.assertEqual(queue.pending, 1)
        self.assertEqual(queue.pop(), 1)
        self.assertEqual(queue.pop(), 0)

    def test_reversal_replaces_old_pending_direction(self):
        queue = RelativeStepQueue()
        for _ in range(12):
            queue.push(1)
        for _ in range(15):
            queue.push(-1)
        self.assertEqual(queue.pending, -3)
        self.assertEqual([queue.pop() for _ in range(3)], [-1, -1, -1])

    def test_rejects_invalid_direction(self):
        with self.assertRaises(ValueError):
            RelativeStepQueue().push(0)


if __name__ == "__main__":
    unittest.main()
