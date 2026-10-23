# Archery Tag Balance Lab

Evaluate asymmetric Archery Tag rules and five-spot target-rack placement through reproducible multi-agent simulation.

**Status: first runnable, uncalibrated attack/defense simulator with scripted players. No trained RL policy or real-world balance estimate.**

## Research questions

- Which target-rack positions produce approximately equal attack and defense win probabilities?
- How do veteran count and individual archery proficiency change those probabilities?
- Which simple resource, life, or respawn adjustments compensate for unequal rosters?

The working scenario uses 120-second attack/defense rounds, a user-supplied 23 x 12 m field, and **one rack holding five fixed target spots**. Rack position is a design variable; individual spots do not move independently.

## Watch a match in Colab

[Open the animation notebook](https://colab.research.google.com/github/Echoudexigaigu/archery-tag-simulate/blob/main/notebooks/02_animation.ipynb)

Use a CPU runtime, run the cells, then click Play. The self-contained Canvas replay shows movement, flying and ground arrows, eliminations, respawns, protection, ammo, proficiency and five target spots on one rack. Pause, step, seek and change playback speed; export `replay.html` for offline playback. No GPU, display server, video encoder or additional plotting dependency is needed. Restart an existing runtime before loading updated simulator modules.

Replay snapshots default to one per physics tick (0.1 seconds); resource metrics remain sampled at one second. Recording does not consume random numbers or alter simulation decisions. Change `record_interval_s` or `stride` to reduce export size; coarser recordings can miss short arrow flights. This is a replay of scripted, uncalibrated players.

## Run the first simulation

[Open attack/defense simulation in Colab](https://colab.research.google.com/github/Echoudexigaigu/archery-tag-simulate/blob/main/notebooks/01_attack_defense.ipynb)

Choose a CPU runtime and run the cells in order. The notebook shows the assumed map, runs one episode, displays target states and resource curves, and compares veteran counts. Review the provisional 1 x 0.6 x 1 m bunker interpretation and all other unmeasured parameters before using results.

- Configuration: `configs/attack_defense_23x12.json`
- Initial report: `reports/first_simulation/README.md`
- Core: Python standard library; Matplotlib is only needed for plots.
- Tests: `PYTHONPATH=src python -m unittest discover -s tests -v`
- Full batch: `PYTHONPATH=src python scripts/run_initial_experiments.py`

## Start in Colab

Repository: https://github.com/Echoudexigaigu/archery-tag-simulate

[Open setup in Colab](https://colab.research.google.com/github/Echoudexigaigu/archery-tag-simulate/blob/main/notebooks/00_setup.ipynb)

The setup notebook uses the public repository URL below and requires no GitHub token for cloning.

1. Click **Open setup in Colab** above.
2. Connect to a standard CPU runtime (hardware accelerator: None).
3. Run the code cells in order; `REPO_URL` is already configured.
4. Review the baseline configuration, unresolved measurements, and Git commit. Setup does not run a simulation.

The clone cell supports public repositories without credentials. For a private repository, follow `docs/colab_workflow.md`; never put credentials in tracked files or notebook outputs.

## Project layout

| Path | Purpose |
| --- | --- |
| `configs/baseline.json` | Original unresolved design template |
| `configs/attack_defense_23x12.json` | Runnable provisional field, rules, skills and policies |
| `docs/model.md` | Mathematical model and balance objective |
| `docs/decisions.md` | Confirmed decisions, provisional assumptions, and open questions |
| `docs/colab_workflow.md` | Colab/Git/Drive workflow |
| `notebooks/00_setup.ipynb` | Clone, inspect configuration, and record repository version |
| `notebooks/02_animation.ipynb` | Run one episode and play/export an interactive replay |
| `src/archery_tag_balance/` | Entities, geometry, environment, policies and evaluation |
| `tests/` | Physics, conservation, observation and rule checks |
| `reports/` | Selected small, reviewed results |

## Reproducibility

Each future run must retain the Git commit, dirty-worktree status and any uncommitted patch, exact configuration snapshot, seeds, policy/checkpoint identifiers, installed package versions, and output artifact locations. A random seed alone does not reproduce a changed environment.

Code, configuration, and selected reports belong in Git. Large trajectories, model checkpoints, and videos belong in Drive. Colab runtime files are temporary; a local commit is not a remote backup until pushed.

## Next milestone

Confirm bunker dimensions, five-hole geometry and assumed boundaries; calibrate arrow dispersion and timings. Compare policy families and refine the model before training or claiming real-world balance.
