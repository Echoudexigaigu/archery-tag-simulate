# Archery Tag Balance Lab

Evaluate asymmetric Archery Tag rules and five-spot target-rack placement through reproducible multi-agent simulation.

**Status: mathematical design and repository scaffold. No simulator, trained policy, or measured balance results yet.**

## Research questions

- Which target-rack positions produce approximately equal attack and defense win probabilities?
- How do veteran count and individual archery proficiency change those probabilities?
- Which simple resource, life, or respawn adjustments compensate for unequal rosters?

The working scenario uses 120-second attack/defense rounds, a smaller field whose dimensions still need measurement, and **one rack holding five fixed target spots**. Rack position is a design variable; individual spots do not move independently.

## Start in Colab

1. Create a GitHub repository and upload this scaffold, including the files beginning with a dot.
2. Open `notebooks/00_setup.ipynb` in Google Colab. Choose a standard CPU runtime.
3. Set `REPO_URL` in the notebook to your repository URL and run the setup cells.
4. Review the baseline configuration and unresolved measurements. Setup does not run a simulation.

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
