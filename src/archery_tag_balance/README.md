# Simulation package

`entities.py` contains Agent, Arrow, Action, Obstacle, and TargetRack. `environment.py` implements the custom simultaneous multi-agent reset/step/observation interface, physics and rules. `policies.py` supplies observation-only scripted players and A* navigation. `experiments.py` provides SimulationEngine, seeded episodes and conditional win-rate summaries. `visualization.py` provides optional plotting.

The core is standard-library Python. Plotting uses Matplotlib. This version is not a Gymnasium/PettingZoo/RLlib adapter and contains no trained RL model.
