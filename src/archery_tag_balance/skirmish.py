"""Symmetric elimination mode, sharing physics and respawn behavior with attack/defense."""

from math import hypot, isfinite

from .entities import Action, Status
from .environment import Environment
from .policies import ScriptedPolicy


class SkirmishEnvironment(Environment):
    def _validate(self):
        super()._validate()
        c = self.config
        if self.mode != "skirmish":
            raise ValueError("SkirmishEnvironment requires mode='skirmish'")
        mid, radius = c["field"]["length_m"] / 2, c["physics"]["player_radius_m"]
        if c["opening"]["center_x_m"] != mid:
            raise ValueError("Opening arrows must be on the geometric field centerline")
        if not 1 <= c["opening"]["arrows_per_player"] <= c["rules"]["carry_limit"]:
            raise ValueError("Opening allocation must fit carry limit")
        tolerance = c["opening"]["baseline_tolerance_m"]
        if not isfinite(tolerance) or tolerance <= 0 or tolerance >= mid - radius:
            raise ValueError("Invalid baseline tolerance")
        if c["rules"]["timeout_result"] not in ("draw", "attack", "defense"):
            raise ValueError("Unknown timeout result")
        for team, t in c["teams"].items():
            lo, hi = t["move_x_bounds_m"]
            if t["initial_arrows"] != 0 or t["lives"] is None or t["lives"] < 1:
                raise ValueError("Skirmish starts empty with finite positive lives")
            if (team == "attack" and hi > mid - radius + 1e-9) or (team == "defense" and lo < mid + radius - 1e-9):
                raise ValueError("Players must remain wholly inside their own half")
        if c["opening"]["arrow_positions_m"]:
            raise ValueError("Skirmish creates individual opening piles; no extra loose opening arrows")

    def _setup_opening(self):
        c = self.config
        mid = c["opening"]["center_x_m"]
        for a in self.agents.values():
            a.shoot_unlocked = False
            for _ in range(c["opening"]["arrows_per_player"]):
                b = self._new_arrow((mid, a.spawn[1], 0.0))
                b.opening_arrow, b.opening_owner = True, a.id

    def _pickup_allowed(self, a, b):
        # Reserve only the initial pile, so one player cannot take another's quota.
        # Once picked up, a dropped or shot arrow is a shared recoverable resource.
        return not b.opening_arrow or b.opening_owner == a.id

    def _picked_up(self, a, b):
        if b.opening_arrow:
            a.opening_received = True
        b.opening_arrow, b.opening_owner = False, None

    def _update_rule_state(self):
        c = self.config
        mid, radius = c["opening"]["center_x_m"], c["physics"]["player_radius_m"]
        tolerance = c["opening"]["baseline_tolerance_m"]
        for a in self.agents.values():
            if a.status == Status.ELIMINATED or a.shoot_unlocked:
                continue
            if abs(a.position[0] - mid) <= radius + 1e-8:
                if not a.center_visited:
                    self._emit("center_reached", agent=a.id)
                a.center_visited = True
            if a.center_visited and abs(a.position[0] - a.spawn[0]) <= tolerance:
                a.shoot_unlocked = True
                self._emit("shoot_unlocked", agent=a.id)

    def _eliminate(self, a, shooter, rewards):
        was_active = a.status == Status.ACTIVE
        super()._eliminate(a, shooter, rewards)
        if was_active and not a.shoot_unlocked:
            # Teleporting to spawn after a hit cannot substitute for running back.
            a.center_visited = False

    def _resolve_winner(self):
        remaining = {team: any(a.lives > 0 for a in self.agents.values() if a.team == team)
                     for team in ("attack", "defense")}
        if not any(remaining.values()):
            return "draw"
        if not remaining["attack"]:
            return "defense"
        if not remaining["defense"]:
            return "attack"
        if self.t + 1e-8 >= self.config["time"]["round_s"]:
            return self.config["rules"]["timeout_result"]
        return None

    def summary(self):
        row = super().summary()
        row.update(mode="skirmish", remaining_lives={team: sum(a.lives for a in self.agents.values() if a.team == team)
                                                    for team in ("attack", "defense")})
        return row


class SkirmishPolicy(ScriptedPolicy):
    """Same observation-only policy on both teams; opening route is explicit."""

    def move_to(self, position, goal, team, now):
        # Finish the last few centimeters, needed to touch center and baseline.
        distance = hypot(goal[0] - position[0], goal[1] - position[1])
        if distance < 0.4 and self.nav.clear(position, goal):
            denominator = max(distance, self.config["physics"]["move_speed_m_s"] * self.config["policy"]["decision_interval_s"])
            return ((goal[0] - position[0]) / denominator, (goal[1] - position[1]) / denominator)
        return super().move_to(position, goal, team, now)

    def __call__(self, obs):
        a, c, now = obs["self"], self.config, obs["time"]
        if a["status"] == "eliminated":
            return Action()
        team, pos = a["team"], a["position"]
        direction = 1 if team == "attack" else -1
        mid, radius = c["opening"]["center_x_m"], c["physics"]["player_radius_m"]
        if not a["shoot_unlocked"]:
            center = (mid - direction * radius, a["spawn"][1])
            owned = [b for b in obs["ground_arrows"] if b["opening_owner"] == a["id"]]
            if not a["center_visited"] or (a["ammo"] < c["opening"]["arrows_per_player"] and owned):
                goal = center
            else:
                goal = a["spawn"]
            return Action(move=self.move_to(pos, goal, team, now), interaction="pickup")
        lo, hi = c["teams"][team]["pickup_x_bounds_m"]
        ground = [b for b in obs["ground_arrows"] if lo <= b["position"][0] <= hi
                  and (not b["opening_arrow"] or b["opening_owner"] == a["id"])]
        if a["ammo"] == 0:
            if ground:
                b = min(ground, key=lambda b: hypot(b["position"][0] - pos[0], b["position"][1] - pos[1]))
                # A centerline arrow can be reached from the legal edge of either half.
                bounds = c["teams"][team]["move_x_bounds_m"]
                goal = (max(bounds[0], min(bounds[1], b["position"][0])), b["position"][1])
            else:
                slot = (int(now / 4) + self.index) % 2
                goal = (mid - direction * (2.5 if slot else 5.0), a["spawn"][1])
            return Action(move=self.move_to(pos, goal, team, now), interaction="pickup")
        lane_jitter = -self.jitter if self.mirror_y else self.jitter
        goal = (mid - direction * 1.8, max(0.8, min(c["field"]["width_m"] - 0.8, a["spawn"][1] + lane_jitter)))
        move = self.move_to(pos, goal, team, now)
        enemies = [e for e in obs["enemies"] if e["status"] == "active"
                   and hypot(e["position"][0] - pos[0], e["position"][1] - pos[1]) >= c["rules"]["min_shot_distance_m"]]
        if not enemies:
            return Action(move=move)
        enemy = min(enemies, key=lambda e: hypot(e["position"][0] - pos[0], e["position"][1] - pos[1]))
        flight = hypot(enemy["position"][0] - pos[0], enemy["position"][1] - pos[1]) / c["physics"]["arrow_speed_m_s"]
        aim = (enemy["position"][0] + enemy["velocity"][0] * flight,
               enemy["position"][1] + enemy["velocity"][1] * flight, enemy["height"] * 0.6)
        cover = any(hypot(o.center[0] - pos[0], o.center[1] - pos[1]) < 1.3 for o in self.nav.obstacles)
        return Action(move=move, aim=aim, aim_key=enemy["id"], interaction="shoot", crouch=cover and a["reload_left"] > 0.2)
