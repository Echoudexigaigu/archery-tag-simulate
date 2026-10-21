"""Optional Matplotlib views; simulation itself has no plotting dependency."""

from math import hypot


def plot_layout(config, env=None, frame=None):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Rectangle

    fig, (ax, face) = plt.subplots(1, 2, figsize=(12.5, 6), gridspec_kw={"width_ratios": [4.5, 1]})
    L, W = config["field"]["length_m"], config["field"]["width_m"]
    ax.set(xlim=(0, L), ylim=(0, W), xlabel="Length (m)", ylabel="Width (m)", aspect="equal")
    ax.set_title("23 x 12 m assumed layout | attack left, defense right", loc="left", fontsize=11)
    ax.axvspan(0, config["teams"]["attack"]["move_x_bounds_m"][1], color="#e35d6a", alpha=0.07)
    ax.axvspan(config["teams"]["defense"]["move_x_bounds_m"][0], L, color="#3677c4", alpha=0.08)
    ax.axvline(L / 2, color="#89939c", linestyle="--", linewidth=1)
    ax.axvline(config["teams"]["attack"]["move_x_bounds_m"][1], color="#b64050", linewidth=1)
    ax.axvline(config["teams"]["defense"]["move_x_bounds_m"][0], color="#3677c4", linewidth=1)
    obstacles = [{"id": o.id, "center_xy_m": o.center, "size_xyz_m": o.size} for o in env.obstacles] if env else config["obstacles"]
    for o in obstacles:
        x, y = o["center_xy_m"]
        sx, sy, sz = o["size_xyz_m"]
        ax.add_patch(Rectangle((x - sx / 2, y - sy / 2), sx, sy, facecolor="#667584", edgecolor="#33424f"))
        ax.text(x, y + sy / 2 + 0.2, o["id"], fontsize=8, ha="center")
    rack_pos = env.rack.position if env else config["rack"]["position_xyz_m"]
    x, y, z = rack_pos
    width, height = config["rack"]["size_m"]
    ax.plot([x, x], [y - width / 2, y + width / 2], color="#8b5d2e", linewidth=6)
    ax.text(x - 0.1, y + 0.85, "5-spot rack", fontsize=9, ha="right")
    if frame is None:
        for team, color in (("attack", "#ce394d"), ("defense", "#276cb0")):
            t = config["teams"][team]
            for i in range(t["players"]):
                py = W * (i + 0.5) / t["players"]
                ax.add_patch(Circle((t["spawn_x_m"], py), config["physics"]["player_radius_m"], color=color))
        ground = config["opening"]["arrow_positions_m"]
        ax.scatter([p[0] for p in ground], [p[1] for p in ground], marker="x", color="#d89b22", label="Opening arrows")
        standing = [True] * 5
    else:
        for a in frame["players"]:
            if a["status"] == "eliminated":
                continue
            color = "#ce394d" if a["team"] == "attack" else "#276cb0"
            px, py = a["position"]
            ax.add_patch(Circle((px, py), config["physics"]["player_radius_m"], facecolor=color, edgecolor="#f0b52f" if a["status"] == "invincible" else color, linewidth=2))
            ax.text(px, py + 0.4, f"{a['id'][-1]}:{a['ammo']}", fontsize=7, ha="center")
        for state, color, marker in (("ground", "#969ba0", "."), ("flying", "#df941b", ">")):
            points = [b["position"] for b in frame["arrows"] if b["state"] == state]
            if points:
                ax.scatter([p[0] for p in points], [p[1] for p in points], c=color, marker=marker, s=20)
        ax.set_title(f"t = {frame['t']:.1f} s | labels: player index : carried arrows", loc="left", fontsize=11)
        standing = frame["spots"]
    face.set(xlim=(-0.45, 0.45), ylim=(-0.45, 0.45), aspect="equal", xlabel="Horizontal (m)", ylabel="Vertical offset (m)")
    face.set_title("Rack front view\n0.75 x 0.75 m", fontsize=10)
    face.add_patch(Rectangle((-width / 2, -height / 2), width, height, facecolor="#ece6db", edgecolor="#8b5d2e"))
    for k, (h, v) in enumerate(config["rack"]["offsets_hv_m"]):
        face.add_patch(Circle((h, v), config["rack"]["spot_radius_m"], facecolor="#276cb0" if standing[k] else "white", edgecolor="#276cb0"))
        face.text(h, v, str(k + 1), ha="center", va="center", color="white" if standing[k] else "#276cb0", fontsize=9)
    fig.suptitle("Provisional geometry and uncalibrated scripted players", fontsize=10, color="#6a7178")
    fig.tight_layout()
    return fig


def plot_resources(rows):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    t = [r["t"] for r in rows]
    for key in ("ground", "carried", "flying"):
        axes[0].plot(t, [r[key] for r in rows], label=key)
    axes[0].set(xlabel="Time (s)", ylabel="Arrow count", title="Arrow locations (conserved total)")
    axes[0].legend(frameon=False)
    axes[1].plot(t, [r["shots"] for r in rows], label="Cumulative shots", color="#276cb0")
    axes[1].set(xlabel="Time (s)", ylabel="Shots", title="Resource usage in one episode")
    fig.tight_layout()
    return fig


def animation_html(config, env, stride=2):
    """Compact projected replay, including a separate front view of the rack."""
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.patches import Circle
    fig = plot_layout(config, env=env)
    ax, face = fig.axes
    frames = env.trace[::stride]
    if not frames:
        raise ValueError("Record an episode first")
    players = [ax.add_patch(Circle((0, 0), config["physics"]["player_radius_m"], visible=False)) for _ in env.agents]
    ground = ax.scatter([], [], s=12, color="#969ba0")
    flying = ax.scatter([], [], s=25, marker=">", color="#df941b")
    disks = face.patches[1:]
    import numpy as np

    def update(index):
        frame = frames[index]
        for patch, a in zip(players, frame["players"]):
            patch.center = a["position"]
            patch.set_visible(a["status"] != "eliminated")
            patch.set_facecolor("#ce394d" if a["team"] == "attack" else "#276cb0")
            patch.set_edgecolor("#f0b52f" if a["status"] == "invincible" else patch.get_facecolor())
        for artist, state in ((ground, "ground"), (flying, "flying")):
            artist.set_offsets(np.array([a["position"][:2] for a in frame["arrows"] if a["state"] == state]).reshape(-1, 2))
        for disk, alive in zip(disks, frame["spots"]):
            disk.set_facecolor("#276cb0" if alive else "white")
        ax.set_title(f"t = {frame['t']:.1f} s | remaining spots: {sum(frame['spots'])}", loc="left", fontsize=11)
        return players + [ground, flying]

    animation = FuncAnimation(fig, update, frames=len(frames), interval=150, blit=False)
    html = animation.to_jshtml()
    plt.close(fig)
    return html
