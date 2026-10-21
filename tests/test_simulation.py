"""Behavioral checks for geometry, resource conservation, and game rules."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from archery_tag_balance import Action, Environment, SimulationEngine, Status
from archery_tag_balance.geometry import ballistic_velocity, segment_box, segment_cylinder


ROOT = Path(__file__).resolve().parents[1]


def config():
    return json.loads((ROOT / "configs/attack_defense_23x12.json").read_text())


class SimulationTests(unittest.TestCase):
    def make_env(self):
        e = Environment(config())
        e.reset(seed=7)
        return e

    def flying(self, env, origin, velocity, shooter="attack_0", arrow_id=0):
        arrow = env.arrows[arrow_id]
        if arrow.carrier:
            env.agents[arrow.carrier].inventory.remove(arrow.id)
        arrow.carrier, arrow.state, arrow.shooter = None, "flying", shooter
        arrow.position, arrow.velocity, arrow.flight_left = origin, velocity, 3.0
        return arrow

    def test_swept_geometry_catches_between_endpoints(self):
        self.assertAlmostEqual(segment_box((0, 0, 0), (10, 0, 0), (4, -1, -1), (6, 1, 1)), 0.4)
        self.assertIsNotNone(segment_cylinder((0, 0, 1), (10, 0, 1), (5, 0), (5, 0), 0.25, 1.7))
        self.assertIsNone(segment_cylinder((0, 0, 2), (10, 0, 2), (5, 0), (5, 0), 0.25, 1.7))

    def test_ballistic_launch_hits_aimed_height(self):
        p, target = (0, 0, 1.25), (15, 0, 1.1)
        v = ballistic_velocity(p, target, 25, 9.81)
        t = 15 / v[0]
        self.assertAlmostEqual(p[2] + v[2] * t - 0.5 * 9.81 * t * t, target[2])

    def test_initial_resource_allocation(self):
        e = self.make_env()
        self.assertEqual(e.total_arrows, 24)
        self.assertEqual(sum(len(a.inventory) for a in e.agents.values()), 12)
        self.assertEqual(sum(b.state == "ground" for b in e.arrows.values()), 12)
        e.assert_invariants()

    def test_pickup_is_delayed_and_opening_quota_applies_once(self):
        e = self.make_env()
        a = e.agents["attack_0"]
        a.position = (11.5, 2)
        for _ in range(2):
            e.step({a.id: Action(interaction="pickup")}, observe=False)
        self.assertEqual(len(a.inventory), 0)
        e.step({a.id: Action(interaction="pickup")}, observe=False)
        self.assertEqual(len(a.inventory), 1)
        self.assertTrue(a.opening_received)
        self.assertFalse(e.arrows[a.inventory[0]].opening_arrow)
        e.assert_invariants()

    def test_one_flight_only_knocks_one_spot(self):
        e = self.make_env()
        x, y, z = e.rack.spot(4)
        self.flying(e, (x - 1, y, z), (25, 0, 0))
        e.step({}, observe=False)
        self.assertFalse(e.rack.standing[4])
        self.assertEqual(sum(e.rack.standing), 4)
        self.assertEqual(e.counts["target"], 1)
        e.assert_invariants()

    def test_cleared_hole_does_not_award_again(self):
        e = self.make_env()
        e.rack.standing[4] = False
        x, y, z = e.rack.spot(4)
        b = self.flying(e, (x - 1, y, z), (25, 0, 0))
        e.step({}, observe=False)
        self.assertEqual(e.counts["target"], 0)
        self.assertEqual(b.state, "flying")

    def test_frame_is_not_a_spot(self):
        e = self.make_env()
        x, y, z = e.rack.position
        b = self.flying(e, (x - 1, y + 0.35, z), (25, 0, 0))
        e.step({}, observe=False)
        self.assertEqual(sum(e.rack.standing), 5)
        self.assertEqual(b.state, "ground")

    def test_bunker_blocks_before_player(self):
        e = self.make_env()
        a = e.agents["attack_0"]
        a.position = (9, 6)
        self.flying(e, (6.5, 6, 0.6), (25, 0, 0), shooter="defense_0")
        e.step({}, observe=False)
        self.assertEqual(a.status, Status.ACTIVE)
        self.assertEqual(e.counts["hit"], 0)

    def test_defender_loses_life_drops_arrows_and_respawns_empty(self):
        e = self.make_env()
        a = e.agents["defense_0"]
        a.position = (20, 2)
        self.flying(e, (19, 2, 1), (25, 0, 0))
        e.step({}, observe=False)
        self.assertEqual(a.status, Status.ELIMINATED)
        self.assertEqual(a.lives, 1)
        self.assertEqual(a.inventory, [])
        for _ in range(32):
            e.step({}, observe=False)
        self.assertNotEqual(a.status, Status.ELIMINATED)
        self.assertEqual(a.inventory, [])
        e.assert_invariants()

    def test_no_observation_leak_through_tall_bunker(self):
        c = config()
        c["obstacles"] = [{"id": "wall", "center_xy_m": [10, 6], "size_xyz_m": [1, 10, 3]}]
        e = Environment(c)
        e.reset(7)
        e.agents["attack_0"].position = (7, 6)
        e.agents["defense_0"].position = (17, 6)
        self.assertNotIn("defense_0", [a["id"] for a in e.get_observation("attack_0")["enemies"]])

    def test_joint_action_order_does_not_change_episode(self):
        a, b = self.make_env(), self.make_env()
        actions = {aid: Action() for aid in a.agents}
        for _ in range(10):
            a.step(actions, observe=False)
            b.step(dict(reversed(list(actions.items()))), observe=False)
        self.assertEqual(a.summary(), b.summary())

    def test_three_player_collision_cascade_does_not_overlap(self):
        e = self.make_env()
        a, b, c = [e.agents[f"attack_{k}"] for k in range(3)]
        a.position, b.position, c.position = (3.0, 3.0), (3.6, 3.0), (2.4, 3.0)
        e.step({a.id: Action(move=(1, 0)), b.id: Action(), c.id: Action(move=(1, 0))}, observe=False)
        self.assertEqual(a.position, (3.0, 3.0))
        self.assertEqual(c.position, (2.4, 3.0))

    def test_nonfinite_action_is_rejected(self):
        e = self.make_env()
        with self.assertRaises(ValueError):
            e.step({"attack_0": Action(move=(float("nan"), 0))})

    def test_timeout_is_terminal_not_training_truncation(self):
        c = config()
        c["time"]["round_s"] = 0.1
        e = Environment(c)
        e.reset(5)
        _, _, terminated, truncated, _ = e.step({})
        self.assertTrue(all(terminated.values()))
        self.assertFalse(any(truncated.values()))
        self.assertEqual(e.winner, "defense")

    def test_invalid_rack_is_rejected(self):
        c = config()
        c["rack"]["position_xyz_m"][1] = 0.1
        with self.assertRaises(ValueError):
            Environment(c)

    def test_seeded_episode_and_conservation(self):
        c = config()
        c["time"]["round_s"] = 15
        first, _ = SimulationEngine(c).episode(11, check_invariants=True)
        second, _ = SimulationEngine(c).episode(11, check_invariants=True)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
