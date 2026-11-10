"""Symmetric elimination mode, sharing physics and respawn behavior with attack/defense."""

from math import hypot, isfinite
from dataclasses import replace

from .entities import Action, Status, Obstacle, TargetRack
from .environment import Environment
from .geometry import lerp, segment_box
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
        if c["physics"].get("linear_drag_s_inv", 0) < 0:
            raise ValueError("Arrow drag must be nonnegative")
        evade = c.get("evasion", {})
        if evade.get("enabled"):
            if any(not 0 <= evade[k] <= 1 for k in ("novice_probability", "expert_probability", "moving_bonus", "probability_cap")):
                raise ValueError("Invalid evasion probability")
            if evade["cooldown_s"] < 0 or evade["reaction_s"] < 0:
                raise ValueError("Invalid evasion timing")
        if evade.get("stamina_enabled"):
            for key in ("movement_cost", "duck_cost", "roll_cost"):
                if not 0 < evade[key] <= 1:
                    raise ValueError("Evasion costs must be in (0, 1]")
            if any(evade[k] <= 0 for k in ("movement_duration_s", "movement_cooldown_s", "stamina_recovery_per_s")):
                raise ValueError("Positive evasion duration, cooldown and recovery required")
        seen = set()
        for spec in c.get("skirmish_racks", []):
            team = spec["team"]
            if team not in c["teams"] or team in seen:
                raise ValueError("One rack per valid team")
            seen.add(team)
            x, y, z = spec["position_xyz_m"]
            w, h = spec["size_m"]
            r = spec["spot_radius_m"]
            if w <= 0 or h <= 0 or r <= 0 or not (w / 2 < y < c["field"]["width_m"] - w / 2 and z >= h / 2):
                raise ValueError("Invalid rack size or position")
            if not ((0 < x < mid) if team == "attack" else (mid < x < c["field"]["length_m"])):
                raise ValueError("Rack must be in its team's half")
            offsets = spec["offsets_hv_m"]
            if len(offsets) != 5 or any(abs(a) + r > w / 2 or abs(b) + r > h / 2 for a, b in offsets):
                raise ValueError("Five rack spots must fit inside frame")
            if any(hypot(a - aa, b - bb) < 2 * r for i, (a, b) in enumerate(offsets) for aa, bb in offsets[:i]):
                raise ValueError("Rack spots overlap")

    def _setup_opening(self):
        c = self.config
        mid = c["opening"]["center_x_m"]
        self.combat_started = not c["opening"].get("synchronized_start", False)
        self.combat_started_at = None
        W = c["field"]["width_m"]
        flip = lambda y: W - y if self.mirror_y else y
        self.skirmish_racks = {}
        self.rack_footprints = []
        for spec in c.get("skirmish_racks", []):
            x, y, z = spec["position_xyz_m"]
            offsets = [(h * (-1 if self.mirror_y else 1), v) for h, v in spec["offsets_hv_m"]]
            rack = TargetRack((x, flip(y), z), tuple(spec["size_m"]), offsets, spec["spot_radius_m"])
            self.skirmish_racks[spec["team"]] = rack
            self.rack_footprints.append(Obstacle("rack_" + spec["team"], rack.position[:2],
                                                 (0.12, rack.size[0], z + rack.size[1] / 2)))
        self.navigation_obstacles = self.obstacles + self.rack_footprints
        for a in self.agents.values():
            a.shoot_unlocked = False
            lane = self.opening_lane(a)
            for _ in range(c["opening"]["arrows_per_player"]):
                b = self._new_arrow((mid, lane, 0.0))
                b.opening_arrow, b.opening_owner = True, a.id

    def opening_lane(self, a):
        c = self.config
        if not c["opening"].get("clear_running_lanes"):
            return a.spawn[1]
        # Move the two obstructed lanes sideways once, then run straight at full
        # speed. Both teams use the same public map, including the target stands.
        width = c["field"]["width_m"]
        margin = c["physics"]["player_radius_m"] + 0.12
        candidates = [a.spawn[1]]
        for offset in (0.85, -0.85, 1.05, -1.05, 1.3, -1.3):
            candidates.append(a.spawn[1] + offset)
        mid = c["opening"]["center_x_m"]
        for y in candidates:
            if not margin < y < width - margin:
                continue
            if all(segment_box((a.spawn[0], y, 0.5), (mid, y, 0.5), *o.bounds(margin)) is None
                   for o in self.navigation_obstacles):
                return y
        raise ValueError("No clear opening lane for " + a.id)

    def valid_move(self, a, old, new):
        return super().valid_move(a, old, new) and all(
            segment_box((*old, 0.5), (*new, 0.5), *o.bounds(self.config["physics"]["player_radius_m"])) is None
            for o in self.rack_footprints)

    def line_clear(self, p, q):
        if not super().line_clear(p, q):
            return False
        for rack in getattr(self, "skirmish_racks", {}).values():
            if abs(q[0] - p[0]) < 1e-12:
                continue
            u = (rack.position[0] - p[0]) / (q[0] - p[0])
            if not 0 < u < 1:
                continue
            point = lerp(p, q, u)
            if abs(point[1] - rack.position[1]) <= rack.size[0] / 2 and abs(point[2] - rack.position[2]) <= rack.size[1] / 2:
                if not any(not rack.standing[k] and hypot(point[1] - rack.spot(k)[1], point[2] - rack.spot(k)[2]) <= rack.radius
                           for k in range(5)):
                    return False
        return True

    def _contacts(self, b, p, q, old_positions, new_positions):
        hits = super()._contacts(b, p, q, old_positions, new_positions)
        radius = self.config["physics"]["arrow_radius_m"]
        for team, rack in self.skirmish_racks.items():
            rx, ry, rz = rack.position
            if abs(q[0] - p[0]) < 1e-12:
                continue
            u = (rx - p[0]) / (q[0] - p[0])
            if not 0 <= u <= 1:
                continue
            point = lerp(p, q, u)
            if abs(point[1] - ry) > rack.size[0] / 2 + radius or abs(point[2] - rz) > rack.size[1] / 2 + radius:
                continue
            spot = next((k for k in range(len(rack.offsets)) if hypot(point[1] - rack.spot(k)[1], point[2] - rack.spot(k)[2]) <= rack.radius + radius), -1)
            if spot >= 0 and not rack.standing[spot] and hypot(point[1] - rack.spot(spot)[1], point[2] - rack.spot(spot)[2]) <= max(0, rack.radius - radius):
                continue
            hits.append((u, 0, "skirmish_rack", (team, spot)))
        return sorted(hits)

    def _contact_skirmish_rack(self, arrow, target, point, rewards):
        team, spot = target
        rack = self.skirmish_racks[team]
        if spot >= 0 and rack.standing[spot] and self.agents[arrow.shooter].team != team:
            rack.standing[spot] = False
            self._emit("rack_target", team=team, spot=spot, shooter=arrow.shooter)
        self._ground(arrow, point)

    def _timers(self, dt):
        super()._timers(dt)
        e = self.config.get("evasion", {})
        if not e.get("stamina_enabled"):
            return
        for a in self.agents.values():
            if self.t >= a.evasion_until:
                a.evasion_kind = None
            # Recover only after the effort, including for the collision save.
            if self.t >= max(a.evasion_until, a.dodge_ready_at):
                a.stamina = min(1.0, a.stamina + e["stamina_recovery_per_s"] * dt)

    def step(self, actions, observe=True):
        e = self.config.get("evasion", {})
        if e.get("stamina_enabled"):
            actions = dict(actions)
            for aid, action in list(actions.items()):
                if aid not in self.agents or not isinstance(action, Action) or not action.evasion_kind:
                    continue
                a = self.agents[aid]
                continuing = a.evade_key == action.evade_key and self.t + 1e-9 < a.evasion_until
                cost = e["duck_cost"] if action.evasion_kind == "duck" else e["movement_cost"]
                if not continuing:
                    if a.evade_key == action.evade_key or self.t < max(a.movement_dodge_ready_at, a.dodge_ready_at) or a.stamina < cost:
                        actions[aid] = Action()
                        continue
                    a.stamina -= cost
                    a.evade_key = action.evade_key
                    a.evasion_kind = action.evasion_kind
                    a.evasion_until = self.t + e["movement_duration_s"]
                    fatigue = 1.0 + (1.0 - a.stamina) * e["fatigue_cooldown_multiplier"]
                    a.movement_dodge_ready_at = self.t + e["movement_cooldown_s"] * fatigue
                    self._emit("evade_move", agent=aid, style=action.evasion_kind, stamina=a.stamina)
        return super().step(actions, observe=observe)

    def _pickup_allowed(self, a, b):
        # Reserve only the initial pile, so one player cannot take another's quota.
        # Once picked up, a dropped or shot arrow is a shared recoverable resource.
        if self.config["rules"].get("single_arrow_shooting") and a.shoot_unlocked and a.inventory:
            return False
        return not b.opening_arrow or b.opening_owner == a.id

    def _release(self, a, action):
        if not self.combat_started:
            return
        if self.config["rules"].get("single_arrow_shooting") and len(a.inventory) != 1:
            return
        super()._release(a, action)

    def _drop(self, a):
        if not self.config["rules"].get("single_arrow_shooting") or a.status != Status.ACTIVE:
            return
        tolerance = self.config["rules"].get("stash_radius_m", 0.75)
        if not a.shoot_unlocked or hypot(a.position[0] - a.spawn[0], a.position[1] - a.spawn[1]) > tolerance:
            return
        direction = 1 if a.team == "attack" else -1
        while len(a.inventory) > 1:
            bid = a.inventory.pop()
            self._ground(self.arrows[bid], (a.spawn[0] + direction * 0.45, a.spawn[1], 0.0))
            self._emit("stash", agent=a.id, arrow=bid)

    def _try_dodge(self, a, b, action):
        evasion = self.config.get("evasion", {})
        if not evasion.get("enabled") or self.t < a.dodge_ready_at:
            return False
        if self.t - b.released_at + 1e-9 < evasion["reaction_s"]:
            return False
        eye = (*a.position, self.player_height(a) * 0.9)
        if hypot(b.position[0] - a.position[0], b.position[1] - a.position[1]) > self.config["physics"]["vision_range_m"] or not self.line_clear(eye, b.position):
            return False
        moving = min(1.0, hypot(*a.velocity) / self.config["physics"]["move_speed_m_s"])
        probability = min(evasion["probability_cap"],
                          self._skill(a.eta, evasion["novice_probability"], evasion["expert_probability"])
                          + evasion["moving_bonus"] * moving)
        if evasion.get("stamina_enabled"):
            if a.stamina < evasion["roll_cost"]:
                return False
            probability *= 0.35 + 0.65 * a.stamina
            a.stamina -= evasion["roll_cost"]
        self._emit("dodge_roll", agent=a.id, arrow=b.id, probability=probability)
        success = self.rng.random() < probability
        # Both outcomes consume this attempt; subsequent arrows cannot give an
        # unlimited series of rerolls in the same burst.
        a.dodge_ready_at = self.t + evasion["cooldown_s"]
        if success:
            self._emit("dodge", agent=a.id, arrow=b.id)
        return success

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
        if not self.combat_started and all(a.shoot_unlocked for a in self.agents.values()):
            self.combat_started, self.combat_started_at = True, self.t
            self._emit("combat_start")

    def get_observation(self, agent_id=None):
        obs = super().get_observation(agent_id)
        if agent_id is not None:
            a = self.agents[agent_id]
            obs["combat_started"] = self.combat_started
            obs["self"].update(stamina=a.stamina, movement_dodge_ready_at=a.movement_dodge_ready_at,
                               dodge_ready_at=a.dodge_ready_at, evasion_until=a.evasion_until,
                               opening_lane=self.opening_lane(a))
            for row in obs["flying_arrows"]:
                arrow = self.arrows[row["id"]]
                row.update(released_at=arrow.released_at, shooter=arrow.shooter,
                           team=self.agents[arrow.shooter].team)
        return obs

    def _record_frame(self):
        super()._record_frame()
        f = self.trace[-1]
        f["combat_started"] = self.combat_started
        f["racks"] = {team: list(r.standing) for team, r in self.skirmish_racks.items()}
        for p in f["players"]:
            a = self.agents[p["id"]]
            p.update(stamina=a.stamina, evasion_kind=a.evasion_kind)

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
        row.update(dodge_rolls=self.counts["dodge_roll"], dodges=self.counts["dodge"],
                   stashed_arrows=self.counts["stash"])
        row.update(combat_started_at=self.combat_started_at, movement_evades=self.counts["evade_move"],
                   rack_hits=self.counts["rack_target"])
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
