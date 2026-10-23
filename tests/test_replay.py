"""Replay must remain an observer of the seeded simulation."""

import json
from pathlib import Path
import unittest

from archery_tag_balance import Environment, SimulationEngine
from archery_tag_balance.replay import replay_html, replay_payload

ROOT = Path(__file__).resolve().parents[1]


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "configs/attack_defense_23x12.json").read_text())
        cls.row, cls.env = SimulationEngine(cls.config).episode(1000, record=True)

    def test_recording_does_not_change_results_or_rng(self):
        row, env = SimulationEngine(self.config).episode(1000, record=False)
        self.assertEqual(row, self.row)
        self.assertEqual(env.rng.getstate(), self.env.rng.getstate())
        self.assertEqual(env.trace, [])
        self.assertEqual(self.row["winner"], "attack")
        self.assertAlmostEqual(self.row["duration_s"], 46.4)

    def test_dense_recording_keeps_initial_and_terminal_frames(self):
        trace = self.env.trace
        self.assertEqual(trace[0]["t"], 0)
        self.assertEqual(trace[-1]["t"], self.env.t)
        self.assertTrue(all(0 < b["t"] - a["t"] <= 0.100001 for a, b in zip(trace, trace[1:])))
        self.assertGreater(len(trace), 5 * len(self.env.resource_curve))
        flying = [a for f in trace for a in f["arrows"] if a["state"] == "flying"]
        self.assertTrue(flying)
        self.assertIn("velocity", flying[0])
        self.assertEqual(trace[-1]["spots"], [False] * 5)

    def test_stride_always_keeps_final_outcome(self):
        data = replay_payload(self.config, self.env, stride=37)
        self.assertAlmostEqual(data["frames"][-1]["t"], self.env.t)
        self.assertEqual(data["frames"][-1]["spots"], [False] * 5)
        self.assertEqual(data["winner"], "attack")

    def test_payload_uses_actual_mirrored_geometry_and_copies_frames(self):
        e = Environment(self.config)
        e.reset(seed=1, record=True, mirror_y=True)
        data = replay_payload(self.config, e)
        self.assertEqual(data["rack"]["offsets"], [list(v) for v in e.rack.offsets])
        self.assertEqual(data["obstacles"][0]["center"], list(e.obstacles[0].center))
        data["frames"][0]["spots"][0] = False
        self.assertTrue(e.trace[0]["spots"][0])

    def test_html_is_safe_and_widgets_have_distinct_ids(self):
        e = Environment(self.config)
        e.reset(record=True)
        e.trace[0]["players"][0]["id"] = "</script><script>alert(1)</script>"
        a, b = replay_html(self.config, e), replay_html(self.config, e)
        self.assertNotEqual(a.split('class="archery-replay"')[0], b.split('class="archery-replay"')[0])
        self.assertNotIn("__REPLAY_", a)
        self.assertNotIn("</script><script>alert", a)
        self.assertIn("\\u003c/script>", a)
        self.assertEqual(a.count("</script>"), 1)

    def test_invalid_options_and_unrecorded_episode(self):
        for stride in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                replay_payload(self.config, self.env, stride=stride)
        for speed in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                replay_payload(self.config, self.env, speed=speed)
        e = Environment(self.config)
        e.reset()
        with self.assertRaisesRegex(ValueError, "record=True"):
            replay_html(self.config, e)
        for interval in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                e.reset(record_interval_s=interval)

    def test_coarse_recording_preserves_terminal_frame_and_metrics(self):
        row, env = SimulationEngine(self.config).episode(1000, record=True, record_interval_s=0.7)
        self.assertEqual(row, self.row)
        self.assertEqual(env.trace[-1]["t"], env.t)
        self.assertLess(len(env.trace), len(self.env.trace))


if __name__ == "__main__":
    unittest.main()
