# Validation

Run from repository root:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Behavioral checks cover ballistic aim height, swept contacts, resource conservation, delayed pickup, a single rack with five independent disks, cleared-hole passage, frame collisions, bunker blocking, finite lives and empty respawn, observation occlusion, action dictionary order, collision cascades, nonfinite input, terminal timeout, geometry rejection and seeded replay. They verify implementation behavior, not real-world calibration.
