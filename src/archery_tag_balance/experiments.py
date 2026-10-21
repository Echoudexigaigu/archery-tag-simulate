"""Seeded episodes and conditional win-rate summaries, using scripted policies."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics

from .environment import Environment
from .policies import Navigator, ScriptedPolicy


def wilson(wins, n, z=1.959963984540054):
    if n == 0:
        return (None, None)
    p, z2 = wins / n, z * z
    center = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5) / (1 + z2 / n)
    return center - half, center + half


def source_digest():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class SimulationEngine:
    def __init__(self, config):
        self.config = deepcopy(config)

    def episode(self, seed=0, record=False, check_invariants=False):
        env = Environment(self.config)
        mirror = bool(seed % 2)
        env.reset(seed=seed, record=record, mirror_y=mirror)
        navigator = Navigator(self.config, env.obstacles)
        policies = {aid: ScriptedPolicy(self.config, navigator, aid, seed * 101 + i + 17, mirror) for i, aid in enumerate(env.agents)}
        next_decision, actions = -1.0, {}
        while not env.done:
            if env.t + 1e-9 >= next_decision:
                actions = {aid: policies[aid](env.get_observation(aid)) for aid in env.agents}
                next_decision = env.t + self.config["policy"]["decision_interval_s"]
            env.step(actions, observe=False)
            if check_invariants:
                env.assert_invariants()
        env.assert_invariants()
        row = env.summary()
        row["mirror_y"] = mirror
        return row, env

    def batch(self, seeds, keep_curves=False):
        rows = []
        for seed in seeds:
            row, _ = self.episode(seed)
            if not keep_curves:
                row.pop("resource_curve")
            rows.append(row)
        return summarize(rows), rows


def summarize(rows):
    n = len(rows)
    wins = sum(r["winner"] == "attack" for r in rows)
    cleared = [r["clear_time_s"] for r in rows if r["clear_time_s"] is not None]
    covers = [r["cover_utilization"] for r in rows if r["cover_utilization"] is not None]
    return {"episodes": n, "attack_wins": wins, "defense_wins": n - wins,
            "attack_win_rate": wins / n if n else None, "wilson_95": wilson(wins, n),
            "mean_duration_s": statistics.mean(r["duration_s"] for r in rows) if rows else None,
            "mean_clear_time_given_success_s": statistics.mean(cleared) if cleared else None,
            "mean_remaining_spots": statistics.mean(r["remaining_spots"] for r in rows) if rows else None,
            "mean_shots": statistics.mean(r["shots"] for r in rows) if rows else None,
            "mean_cover_utilization": statistics.mean(covers) if covers else None}


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
