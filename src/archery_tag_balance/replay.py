"""Lightweight self-contained Canvas replay for IPython.display.HTML in Colab."""

import json
from math import isfinite
from pathlib import Path
import uuid


def replay_payload(config, env, stride=1, speed=2.0):
    if isinstance(stride, bool) or not isinstance(stride, int) or stride < 1:
        raise ValueError("stride must be a positive integer")
    if not isfinite(speed) or speed <= 0:
        raise ValueError("speed must be positive and finite")
    if not env.trace:
        raise ValueError("Run SimulationEngine(config).episode(seed=..., record=True) first")
    frames = env.trace[::stride]
    if frames[-1]["t"] != env.trace[-1]["t"]:
        frames = frames + [env.trace[-1]]

    def compact(value):
        if isinstance(value, float):
            return round(value, 4)
        if isinstance(value, dict):
            return {k: compact(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [compact(v) for v in value]
        return value

    # Copy actual geometry so mirrored episodes render consistently.
    return compact({"frames": frames, "events": env.events, "speed": speed,
                    "duration": frames[-1]["t"], "roundDuration": config["time"]["round_s"],
                    "winner": env.winner, "seed": env.seed,
                    "field": config["field"], "teams": config["teams"],
                    "playerRadius": config["physics"]["player_radius_m"],
                    "obstacles": [{"id": o.id, "center": o.center, "size": o.size} for o in env.obstacles],
                    "rack": {"position": env.rack.position, "size": env.rack.size,
                             "offsets": env.rack.offsets, "radius": env.rack.radius}})


def replay_html(config, env, stride=1, speed=2.0):
    """Return HTML, not a live simulation; controls work without Python callbacks.

    Use display(HTML(replay_html(config, env))) in a trusted Colab output cell.
    Export with Path(...).write_text(html, encoding='utf-8').
    """
    payload = replay_payload(config, env, stride=stride, speed=speed)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # Prevent any strings in the data from closing the script element.
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = Path(__file__).with_name("replay_template.html").read_text(encoding="utf-8")
    return template.replace("__REPLAY_ROOT__", "archery-replay-" + uuid.uuid4().hex).replace("__REPLAY_DATA__", data)
