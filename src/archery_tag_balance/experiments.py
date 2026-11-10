"""Seeded episodes and conditional win-rate summaries, using scripted policies."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics

from .environment import Environment
from .policies import Navigator, ScriptedPolicy
from .skirmish import SkirmishEnvironment, SkirmishPolicy
from .cover_policy import CoverPolicy
from .human_skirmish import HumanSkirmishEnvironment
from .six_role_policy import SixRolePolicy
from .varied_environment import VariedSkirmishEnvironment
from .varied_policy import VariedRolePolicy
from .runout_environment import RunoutSkirmishEnvironment
from .rebound_environment import ReboundSkirmishEnvironment
from .cache_policy import CacheRolePolicy
from .tactical_environment import SuzhouEnvironment
from .tactical_policy import SuzhouPolicy


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
    for path in sorted([*root.glob("*.py"), *root.glob("*.html")]):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class SimulationEngine:
    def __init__(self, config):
        self.config = deepcopy(config)

    def episode(self, seed=0, record=False, check_invariants=False, record_interval_s=0.1):
        skirmish = self.config.get("mode") == "skirmish"
        suzhou=self.config.get('ruleset_id')=='suzhou_2026_next_battle'
        if suzhou:
            env,policy_class=SuzhouEnvironment(self.config),SuzhouPolicy
        else:
            env = SkirmishEnvironment(self.config) if skirmish else Environment(self.config)
            policy_class = (CoverPolicy if self.config["policy"].get("cover_based") else SkirmishPolicy) if skirmish else ScriptedPolicy
            if skirmish and self.config["policy"].get("six_roles"):
                env, policy_class = HumanSkirmishEnvironment(self.config), SixRolePolicy
            if skirmish and self.config['policy'].get('varied_v5'):
                env,policy_class=VariedSkirmishEnvironment(self.config),VariedRolePolicy
            if skirmish and self.config.get('ground_runout',{}).get('enabled'):
                env,policy_class=RunoutSkirmishEnvironment(self.config),VariedRolePolicy
            if skirmish and self.config.get('panel_rebound',{}).get('enabled'):
                env,policy_class=ReboundSkirmishEnvironment(self.config),CacheRolePolicy
        mirror = bool(seed % 2) and self.config["policy"].get("mirror_layout", True)
        env.reset(seed=seed, record=record, mirror_y=mirror, record_interval_s=record_interval_s)
        navigator = Navigator(self.config, getattr(env, "navigation_obstacles", env.obstacles))
        profile_seed=self.config.get('roster_seed',20261107) if suzhou else seed
        policies = {aid: policy_class(self.config, navigator, aid, profile_seed * 101 + i + 17, mirror) for i, aid in enumerate(env.agents)}
        next_decision, actions = -1.0, {}
        while not env.done:
            if env.t + 1e-9 >= next_decision:
                actions = {aid: policies[aid](env.get_observation(aid)) for aid in env.agents}
                if suzhou:env.policy_intents={aid:dict(p.intent) for aid,p in policies.items()}
                next_decision = env.t + self.config["policy"]["decision_interval_s"]
            env.step(actions, observe=False)
            if check_invariants:
                env.assert_invariants()
        env.assert_invariants()
        row = env.summary()
        if self.config["policy"].get("six_roles"):
            row['policy_diagnostics'] = {aid: dict(p.diagnostics) for aid, p in policies.items()}
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
    defense_wins = sum(r["winner"] == "defense" for r in rows)
    draws = sum(r["winner"] == "draw" for r in rows)
    decisive = wins + defense_wins
    cleared = [r["clear_time_s"] for r in rows if r["clear_time_s"] is not None]
    covers = [r["cover_utilization"] for r in rows if r["cover_utilization"] is not None]
    return {"episodes": n, "attack_wins": wins, "defense_wins": defense_wins, "draws": draws,
            "draw_rate": draws / n if n else None,
            "attack_win_rate_given_decisive": wins / decisive if decisive else None,
            "wilson_95_given_decisive": wilson(wins, decisive),
            "attack_win_rate": wins / n if n else None, "wilson_95": wilson(wins, n),
            "mean_duration_s": statistics.mean(r["duration_s"] for r in rows) if rows else None,
            "mean_clear_time_given_success_s": statistics.mean(cleared) if cleared else None,
            "mean_remaining_spots": statistics.mean(r["remaining_spots"] for r in rows if r["remaining_spots"] is not None) if any(r["remaining_spots"] is not None for r in rows) else None,
            "mean_shots": statistics.mean(r["shots"] for r in rows) if rows else None,
            "mean_cover_utilization": statistics.mean(covers) if covers else None}


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
