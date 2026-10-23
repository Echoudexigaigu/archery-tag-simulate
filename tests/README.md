# Validation

Run from repository root:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Behavioral checks cover ballistic aim height, swept contacts, resource conservation, delayed pickup, a single rack with five independent disks, cleared-hole passage, frame collisions, bunker blocking, finite lives and empty respawn, observation occlusion, action dictionary order, collision cascades, nonfinite input, terminal timeout, geometry rejection and seeded replay. They verify implementation behavior, not real-world calibration.

Replay checks cover recording independence, snapshot cadence, terminal-frame retention, mirrored geometry, safe HTML embedding and separate player instances. `tests/replay_controls.cjs` exercises controls in Node using a minimal DOM; it does not replace a Colab browser check.

Skirmish checks cover 36-arrow allocation, opening ownership, enforced center/baseline round trips on both teams, no respawn shortcut, two-life empty respawn, protection, permanent elimination, pending respawns, simultaneous elimination, centerline bounds, timeout draws and separate draw statistics. Both replay modes can use the same Node control checks.
