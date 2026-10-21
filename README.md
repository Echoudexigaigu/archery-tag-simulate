# Archery Tag Balance Lab

Evaluate asymmetric Archery Tag rules and five-spot target-rack placement through reproducible multi-agent simulation.

**Status: mathematical design and repository scaffold. No simulator, trained policy, or measured balance results yet.**

## Research questions

- Which target-rack positions produce approximately equal attack and defense win probabilities?
- How do veteran count and individual archery proficiency change those probabilities?
- Which simple resource, life, or respawn adjustments compensate for unequal rosters?

The working scenario uses 120-second attack/defense rounds, a smaller field whose dimensions still need measurement, and **one rack holding five fixed target spots**. Rack position is a design variable; individual spots do not move independently.

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
| `configs/baseline.json` | Proposed game rules and explicitly missing measurements |
| `docs/model.md` | Mathematical model and balance objective |
| `docs/decisions.md` | Confirmed decisions, provisional assumptions, and open questions |
| `docs/colab_workflow.md` | Colab/Git/Drive workflow |
| `notebooks/00_setup.ipynb` | Clone, inspect configuration, and record repository version |
| `src/archery_tag_balance/` | Reserved for future simulator modules |
| `tests/` | Reserved for physics and rules checks |
| `reports/` | Selected small, reviewed results |

## Reproducibility

Each future run must retain the Git commit, dirty-worktree status and any uncommitted patch, exact configuration snapshot, seeds, policy/checkpoint identifiers, installed package versions, and output artifact locations. A random seed alone does not reproduce a changed environment.

Code, configuration, and selected reports belong in Git. Large trajectories, model checkpoints, and videos belong in Drive. Colab runtime files are temporary; a local commit is not a remote backup until pushed.

## Next milestone

Measure field/rack geometry and resolve the rule questions before implementing a single 4v4 episode. Validate the rules before training or claiming balance.
