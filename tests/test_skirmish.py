"""Rules for the opening round-trip, two lives, elimination and draws."""

from collections import Counter
import json
from pathlib import Path
import unittest

from archery_tag_balance import Action, SimulationEngine, SkirmishEnvironment, Status
from archery_tag_balance.experiments import summarize
from archery_tag_balance.replay import replay_payload

ROOT = Path(__file__).resolve().parents[1]


def config():
    return json.loads((ROOT / "configs/skirmish_6v6_23x12.json").read_text())


class SkirmishTests(unittest.TestCase):
    def make_env(self):
        e = SkirmishEnvironment(config())
        e.reset(seed=1000, record=True)
        return e

    def eliminate(self, e, a):
        shooter = next(b for b in e.agents.values() if b.team != a.team)
        e._eliminate(a, shooter, {aid: 0.0 for aid in e.agents})

    def test_initial_allocation_and_symmetric_geometry(self):
        e = self.make_env()
        self.assertIsNone(e.rack)
        self.assertEqual(len(e.agents), 12)
        self.assertEqual(e.total_arrows, 36)
        self.assertEqual(Counter(b.opening_owner for b in e.arrows.values()), {aid: 3 for aid in e.agents})
        self.assertTrue(all(b.position[0] == 11.5 and b.state == "ground" for b in e.arrows.values()))
        self.assertTrue(all(a.lives == 2 and not a.inventory and not a.shoot_unlocked for a in e.agents.values()))
        self.assertEqual({o.center for o in e.obstacles}, {(5.75, 3), (5.75, 9), (17.25, 3), (17.25, 9)})
        e.assert_invariants()

    def test_pickup_gets_three_and_cannot_take_opponents_quota(self):
        e = self.make_env()
        a = e.agents["attack_0"]
        a.position = (11.25, 1)
        for _ in range(18):
            e.step({a.id: Action(interaction="pickup")}, observe=False)
        self.assertEqual(len(a.inventory), 3)
        self.assertEqual(sum(b.opening_owner == "defense_0" for b in e.arrows.values()), 3)
        self.assertTrue(a.center_visited)
        self.assertFalse(a.shoot_unlocked)
        e.assert_invariants()

    def test_round_trip_is_enforced_by_engine_on_both_sides(self):
        for aid, cx in (("attack_0", 11.25), ("defense_0", 11.75)):
            e = self.make_env()
            a = e.agents[aid]
            arrow = next(b for b in e.arrows.values() if b.opening_owner == aid)
            e._carry(arrow, a)
            action = Action(aim=(15 if a.team == "attack" else 8, 1, 1), aim_key="test", interaction="shoot")
            a.aim_key, a.aim_elapsed = "test", 10
            e.step({aid: action}, observe=False)
            self.assertEqual(e.counts["shot"], 0, "spawn alone is not a completed round trip")
            a.position = (cx, a.spawn[1])
            e.step({aid: action}, observe=False)
            self.assertTrue(a.center_visited)
            self.assertEqual(e.counts["shot"], 0)
            a.position = a.spawn
            e.step({aid: Action()}, observe=False)
            self.assertTrue(a.shoot_unlocked)
            a.aim_key, a.aim_elapsed = "test", 10
            e.step({aid: action}, observe=False)
            self.assertEqual(e.counts["shot"], 1)

    def test_respawn_does_not_bypass_unfinished_round_trip(self):
        e = self.make_env()
        a = e.agents["attack_0"]
        a.center_visited = True
        self.eliminate(e, a)
        for _ in range(33):
            e.step({}, observe=False)
        self.assertNotEqual(a.status, Status.ELIMINATED)
        self.assertFalse(a.shoot_unlocked)
        self.assertFalse(a.center_visited)

    def test_first_hit_respawns_empty_with_protection_second_hit_is_final(self):
        e = self.make_env()
        a = e.agents["defense_0"]
        a.shoot_unlocked = True
        e._carry(next(b for b in e.arrows.values() if b.opening_owner == a.id), a)
        self.eliminate(e, a)
        self.assertEqual(a.lives, 1)
        for _ in range(31):
            e.step({}, observe=False)
        self.assertEqual(a.status, Status.INVINCIBLE)
        self.assertEqual(a.inventory, [])
        self.assertTrue(a.shoot_unlocked)
        for _ in range(10):
            e.step({}, observe=False)
        self.assertEqual(a.status, Status.ACTIVE)
        self.eliminate(e, a)
        self.assertEqual(a.lives, 0)
        self.assertIsNone(a.respawn_at)
        for _ in range(40):
            e.step({}, observe=False)
        self.assertEqual(a.status, Status.ELIMINATED)
        e.assert_invariants()

    def test_waiting_for_respawn_is_not_team_elimination(self):
        e = self.make_env()
        for a in e.agents.values():
            if a.team == "attack":
                self.eliminate(e, a)
        e.step({}, observe=False)
        self.assertFalse(e.done)
        self.assertTrue(all(a.respawn_at is not None for a in e.agents.values() if a.team == "attack"))

    def test_full_elimination_rewards_winner_and_simultaneous_elimination_draws(self):
        for wiped, expected in (({"attack"}, "defense"), ({"defense"}, "attack"), ({"attack", "defense"}, "draw")):
            e = self.make_env()
            for a in e.agents.values():
                if a.team in wiped:
                    a.lives = 1
                    self.eliminate(e, a)
            _, rewards, terms, _, _ = e.step({}, observe=False)
            self.assertEqual(e.winner, expected)
            self.assertTrue(all(terms.values()))
            for aid, reward in rewards.items():
                self.assertEqual(reward, 10 if e.agents[aid].team == expected else 0)

    def test_center_is_a_movement_boundary(self):
        e = self.make_env()
        for aid, x, direction in (("attack_0", 11.25, 1), ("defense_0", 11.75, -1)):
            a = e.agents[aid]
            a.position = (x, a.spawn[1])
            e.step({aid: Action(move=(direction, 0))}, observe=False)
            self.assertEqual(a.position[0], x)

    def test_timeout_draw_is_not_counted_as_blue_win(self):
        c = config()
        c["time"]["round_s"] = 0.2
        row, e = SimulationEngine(c).episode(0)
        self.assertEqual(e.winner, "draw")
        stats = summarize([row])
        self.assertEqual((stats["attack_wins"], stats["defense_wins"], stats["draws"]), (0, 0, 1))
        self.assertEqual(stats["draw_rate"], 1)
        self.assertIsNone(stats["attack_win_rate_given_decisive"])
        self.assertIsNone(stats["mean_remaining_spots"])

    def test_scripted_replay_obeys_opening_and_conserves_resources(self):
        c = config()
        row, e = SimulationEngine(c).episode(1000, record=True, check_invariants=True)
        centers, unlocked, shots = {}, {}, []
        for event in e.events:
            if event["kind"] == "center_reached":
                centers[event["agent"]] = event["t"]
            elif event["kind"] == "shoot_unlocked":
                self.assertLess(centers[event["agent"]], event["t"])
                unlocked[event["agent"]] = event["t"]
            elif event["kind"] == "shot":
                self.assertIn(event["agent"], unlocked)
                self.assertLessEqual(unlocked[event["agent"]], event["t"])
                shots.append(event)
        self.assertTrue(shots)
        self.assertTrue(all(sum(f[k] for k in ("ground", "carried", "flying")) == 36 for f in row["resource_curve"]))
        self.assertIsNone(replay_payload(c, e)["rack"])
        self.assertEqual(e.trace[-1]["t"], e.t)
        row_without_record, _ = SimulationEngine(c).episode(1000)
        self.assertEqual(row_without_record, row)


if __name__ == "__main__":
    unittest.main()
