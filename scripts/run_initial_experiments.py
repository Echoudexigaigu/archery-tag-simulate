"""CPU-only baseline, roster imbalance, rack search, and numerical checks.

Run from repository root: PYTHONPATH=src python scripts/run_initial_experiments.py
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import platform
import subprocess
import time

from archery_tag_balance.experiments import SimulationEngine, save_json, source_digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/attack_defense_23x12.json")
    parser.add_argument("--output", default="runs/first_simulation")
    parser.add_argument("--baseline-n", type=int, default=200)
    parser.add_argument("--roster-n", type=int, default=100)
    parser.add_argument("--grid-n", type=int, default=40)
    parser.add_argument("--check-n", type=int, default=20)
    parser.add_argument("--validation-n", type=int, default=200)
    args = parser.parse_args()
    base = json.loads(Path(args.config).read_text())
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "results.json"
    result = {"status": "provisional_uncalibrated", "python": platform.python_version(), "source_sha256": source_digest(), "config_snapshot": base, "conditions": [], "notes": ["Independent seeds within each condition; shared seeds across conditions are paired for comparison.", "95% Wilson intervals describe Monte Carlo uncertainty conditional on this model, not real-world accuracy.", "Exploratory target-position grid; no held-out optimum validation or RL policy training."]}
    try:
        result["code_commit_before_run"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        result["worktree_dirty_before_run"] = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        result["code_commit_before_run"] = None
    start = time.perf_counter()

    def condition(name, config, n, seed_start=1000):
        summary, rows = SimulationEngine(config).batch(range(seed_start, seed_start + n))
        entry = {"name": name, "rack_xyz_m": config["rack"]["position_xyz_m"], "attack_veterans": config["teams"]["attack"]["veterans"], "defense_veterans": config["teams"]["defense"]["veterans"], "dt_s": config["time"]["dt_s"], "policy": config["policy"], "spot_radius_m": config["rack"]["spot_radius_m"], "summary": summary, "episodes": rows}
        result["conditions"].append(entry)
        result["elapsed_s"] = time.perf_counter() - start
        save_json(path, result)
        print(json.dumps({"condition": name, **summary, "elapsed_s": round(result["elapsed_s"], 1)}, ensure_ascii=False), flush=True)

    condition("equal_2v2_veterans", base, args.baseline_n)
    for attack, defense, name in ((3, 1, "attack_3_defense_1_veterans"), (1, 3, "attack_1_defense_3_veterans")):
        c = deepcopy(base)
        c["teams"]["attack"]["veterans"], c["teams"]["defense"]["veterans"] = attack, defense
        condition(name, c, args.roster_n)
    for x in (18.0, 20.0, 21.5):
        for y in (2.5, 6.0, 9.5):
            if (x, y) == tuple(base["rack"]["position_xyz_m"][:2]):
                continue
            c = deepcopy(base)
            c["rack"]["position_xyz_m"] = [x, y, base["rack"]["position_xyz_m"][2]]
            condition(f"rack_{x:g}_{y:g}", c, args.grid_n)
    if args.validation_n:
        c = deepcopy(base)
        c["rack"]["position_xyz_m"] = [18.0, 6.0, base["rack"]["position_xyz_m"][2]]
        condition("heldout_rack_18_6", c, args.validation_n, seed_start=10000)
    if args.check_n:
        condition("time_step_0.1_check", base, args.check_n, seed_start=5000)
        c = deepcopy(base)
        c["time"]["dt_s"] = 0.05
        condition("time_step_0.05_check", c, args.check_n, seed_start=5000)
        for radius in (0.065, 0.11):
            c = deepcopy(base)
            c["rack"]["spot_radius_m"] = radius
            condition(f"spot_radius_{radius:g}", c, args.check_n, seed_start=5000)
        c = deepcopy(base)
        c["policy"]["attack_suppressors"] = 0
        c["policy"]["name"] = "all_clear_v1"
        condition("all_attackers_clear_targets", c, args.check_n, seed_start=5000)
    demo, env = SimulationEngine(base).episode(1000, record=True)
    save_json(out / "demo.json", {"summary": demo, "trace": env.trace, "events": env.events})
    print("Completed", sum(c["summary"]["episodes"] for c in result["conditions"]), "episodes", flush=True)


if __name__ == "__main__":
    main()
