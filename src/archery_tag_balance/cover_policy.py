"""Cover, single-arrow resupply and visible-projectile sidesteps for 6v6."""

from dataclasses import replace
from math import cos, hypot, radians, sin

from .entities import Action
from .skirmish import SkirmishPolicy


class CoverPolicy(SkirmishPolicy):
    def _positions(self, obs):
        a, c = obs["self"], self.config
        team, direction = a["team"], (1 if a["team"] == "attack" else -1)
        mid = c["field"]["length_m"] / 2
        bunkers = sorted((o for o in self.nav.obstacles if (o.center[0] < mid) == (team == "attack")),
                         key=lambda o: o.center[1], reverse=self.mirror_y)
        bunkers = [o for o in bunkers if not o.id.startswith("rack_")]
        # Three assigned players per bunker, in staggered positions behind it.
        n = c["teams"][team]["players"]
        group_size = (n + len(bunkers) - 1) // len(bunkers)
        bunker = bunkers[min(len(bunkers) - 1, self.index // group_size)]
        slot = self.index % group_size
        mirror = -1 if self.mirror_y else 1
        if c["policy"].get("one_person_cover"):
            # One close occupant, one rear shadow, one exposed wide support.
            # Protection is always geometric; even the rear shadow can be hit
            # from the opposite lane. Nobody receives a cover probability buff.
            side = -1 if bunker.center[1] < c["field"]["width_m"] / 2 else 1
            depth = bunker.size[0] / 2 + c["physics"]["player_radius_m"]
            behind = depth + (0.22, 1.55, 0.65)[slot % 3]
            lateral = (0.0, -side * 0.12, side * 1.8)[slot % 3]
            hold = (bunker.center[0] - direction * behind, bunker.center[1] + lateral)
            offset = (side * 0.95, -side * 1.2, side * 1.8)[slot % 3]
            peek = (bunker.center[0] - direction * (0.30, 1.0, 0.8)[slot % 3],
                    max(0.65, min(c["field"]["width_m"] - 0.65, bunker.center[1] + offset)))
            return bunker, hold, peek
        behind = bunker.size[0] / 2 + c["physics"]["player_radius_m"] + 0.35 + slot * 0.7
        hold = (bunker.center[0] - direction * behind,
                bunker.center[1] + mirror * ((slot % 3) - 1) * 0.25)
        offset = (-1.25, -0.65, 1.15)[slot % 3] * mirror
        peek = (bunker.center[0] - direction * (0.85 if slot % 3 == 1 else 0.25),
                max(0.8, min(c["field"]["width_m"] - 0.8, bunker.center[1] + offset)))
        return bunker, hold, peek

    def _sidestep(self, obs, move, crouch):
        a, c = obs["self"], self.config
        if c.get("evasion", {}).get("stamina_enabled"):
            return self._compact_evade(obs, move, crouch)
        if not c.get("evasion", {}).get("movement_enabled", True):
            return move, crouch, False
        x, y = a["position"]
        horizon = c["evasion"]["lookahead_s"]
        for b in sorted(obs["flying_arrows"], key=lambda b: hypot(b["position"][0] - x, b["position"][1] - y)):
            rx, ry = b["position"][0] - x, b["position"][1] - y
            vx, vy, vz = b["velocity"]
            vx -= a["velocity"][0]
            vy -= a["velocity"][1]
            denom = vx * vx + vy * vy
            t = -(rx * vx + ry * vy) / max(1e-9, denom)
            if not 0 < t < horizon:
                continue
            if hypot(rx + vx * t, ry + vy * t) > c["evasion"]["danger_radius_m"]:
                continue
            z = b["position"][2] + vz * t - 0.5 * c["physics"]["gravity_m_s2"] * t * t
            if not 0 < z < c["physics"]["player_height_m"] + 0.2:
                continue
            norm = max(1e-9, hypot(vx, vy))
            sidestep = (-vy / norm, vx / norm)
            xmin, xmax = c["teams"][a["team"]]["move_x_bounds_m"]
            choices = []
            for sign in (-1, 1):
                dx, dy = sign * sidestep[0], sign * sidestep[1]
                distance = c["physics"]["move_speed_m_s"] * c["policy"]["decision_interval_s"]
                goal = (x + dx * distance, y + dy * distance)
                if xmin <= goal[0] <= xmax and 0.3 <= goal[1] <= c["field"]["width_m"] - 0.3 and self.nav.clear((x, y), goal):
                    # Prefer agreement with the intended route, then field interior.
                    score = dx * move[0] + dy * move[1] - 0.01 * abs(goal[1] - c["field"]["width_m"] / 2)
                    choices.append((score, (dx, dy)))
            if choices:
                return max(choices)[1], False, True
            return move, True, True
        return move, crouch, False

    def _compact_evade(self, obs, move, crouch):
        a, c, now = obs["self"], self.config, obs["time"]
        e = c["evasion"]
        self.evade_action = None
        # Finish one short gesture, rather than choosing a fresh jump every tick.
        if now + 1e-9 < getattr(self, "gesture_until", 0):
            self.evade_action = self.gesture
            return self.gesture.move, self.gesture.crouch, True
        if not e.get("movement_enabled", True) or now < max(a["movement_dodge_ready_at"], a["dodge_ready_at"]) or a["stamina"] < min(e["movement_cost"], e["duck_cost"]):
            return move, crouch, False
        x, y = a["position"]
        threats = []
        for b in obs["flying_arrows"]:
            if b.get("team") == a["team"] or now - b.get("released_at", 0) < e["reaction_s"]:
                continue
            key = (b["id"], b.get("released_at", 0))
            if key == getattr(self, "last_reacted", None):
                continue
            rx, ry = b["position"][0] - x, b["position"][1] - y
            vx, vy, vz = b["velocity"]
            # Forecast the arrow, not a hypothetical continuation of our run.
            t = -(rx * vx + ry * vy) / max(1e-9, vx * vx + vy * vy)
            if not 0 < t < e["lookahead_s"] or hypot(rx + vx * t, ry + vy * t) > e["danger_radius_m"]:
                continue
            z = b["position"][2] + vz * t - 0.5 * c["physics"]["gravity_m_s2"] * t * t
            height = c["physics"]["crouched_height_m"] if crouch else c["physics"]["player_height_m"]
            if 0 < z < height + 0.1:
                threats.append((t, b, z))
        if not threats:
            return move, crouch, False
        _, b, z = min(threats, key=lambda v: v[0])
        key = (b["id"], b.get("released_at", 0))
        vx, vy = b["velocity"][:2]
        norm = max(1e-9, hypot(vx, vy))
        side = (-vy / norm, vx / norm)
        direction = 1 if a["team"] == "attack" else -1
        variants = []
        fatigue = 0.6 + 0.4 * a["stamina"]
        if a["stamina"] >= e["movement_cost"]:
            for sign in (-1, 1):
                # Small sidestep, or a small diagonal withdrawal with a dip.
                distance = self.rng.uniform(0.24, 0.42) * fatigue
                variants.append(("sidestep", (side[0] * sign * distance, side[1] * sign * distance), False))
                distance = self.rng.uniform(0.20, 0.32) * fatigue
                dx, dy = side[0] * sign - direction * 0.6, side[1] * sign
                n = hypot(dx, dy)
                variants.append(("withdraw", (dx / n * distance, dy / n * distance), True))
        if z > c["physics"]["crouched_height_m"] + 0.15 and a["stamina"] >= e["duck_cost"]:
            variants.append(("duck", (0.0, 0.0), True))
        self.rng.shuffle(variants)
        lo, hi = c["teams"][a["team"]]["move_x_bounds_m"]
        for style, delta, duck in variants:
            goal = x + delta[0], y + delta[1]
            if not lo <= goal[0] <= hi or not 0.3 <= goal[1] <= c["field"]["width_m"] - 0.3 or not self.nav.clear((x, y), goal):
                continue
            if any(hypot(goal[0] - p["position"][0], goal[1] - p["position"][1]) < 0.65 for p in obs.get("teammates", [])):
                continue
            speed = c["physics"]["move_speed_m_s"] * (c["physics"]["crouch_speed_fraction"] if duck else 1)
            duration = e["movement_duration_s"]
            action = Action(move=(delta[0] / (speed * duration), delta[1] / (speed * duration)),
                            crouch=duck, evasion_kind=style, evade_key=key)
            self.last_reacted, self.gesture, self.gesture_until = key, action, now + duration
            self.evade_action = action
            return action.move, action.crouch, True
        return move, crouch, False

    def _avoid_teammates(self, obs, move):
        """Steer locally around visible teammates, avoiding symmetric deadlocks."""
        norm = hypot(*move)
        if norm < 1e-9:
            return move
        a, c = obs["self"], self.config
        x, y = a["position"]
        nearby = [p for p in obs.get("teammates", []) if hypot(p["position"][0] - x, p["position"][1] - y) < 2]
        if not nearby:
            return move
        lo, hi = c["teams"][a["team"]]["move_x_bounds_m"]
        step = c["physics"]["move_speed_m_s"] * c["policy"]["decision_interval_s"]
        margin = 2 * c["physics"]["player_radius_m"] + 0.08
        choices = []
        for degrees in (0, 35, -35, 70, -70, 110, -110, 150, -150, 180):
            angle = radians(degrees)
            dx = move[0] * cos(angle) - move[1] * sin(angle)
            dy = move[0] * sin(angle) + move[1] * cos(angle)
            goal = x + dx * step, y + dy * step
            if not lo <= goal[0] <= hi or not 0.27 <= goal[1] <= c["field"]["width_m"] - 0.27 or not self.nav.clear((x, y), goal):
                continue
            clearance = 10.0
            for p in nearby:
                rx, ry = x - p["position"][0], y - p["position"][1]
                vx = dx * step - p["velocity"][0] * c["policy"]["decision_interval_s"]
                vy = dy * step - p["velocity"][1] * c["policy"]["decision_interval_s"]
                t = max(0.0, min(1.0, -(rx * vx + ry * vy) / max(1e-9, vx * vx + vy * vy)))
                clearance = min(clearance, hypot(rx + vx * t, ry + vy * t))
            score = (dx * move[0] + dy * move[1]) / norm - 20 * max(0, margin - clearance)
            choices.append((score, (dx, dy)))
        return max(choices, key=lambda p: p[0])[1] if choices else (0.0, 0.0)

    def __call__(self, obs):
        action = self._act(obs)
        if action.evasion_kind:
            return action  # Keep the chosen short gesture's displacement bounded.
        return replace(action, move=self._avoid_teammates(obs, action.move))

    def _act(self, obs):
        a, c, now = obs["self"], self.config, obs["time"]
        if a["status"] == "eliminated":
            return Action()
        # The inherited opening collects three and genuinely returns to baseline.
        if not a["shoot_unlocked"]:
            if c["opening"].get("clear_running_lanes"):
                direction = 1 if a["team"] == "attack" else -1
                lane = a["opening_lane"]
                center = (c["opening"]["center_x_m"] - direction * c["physics"]["player_radius_m"], lane)
                if not a["center_visited"] or a["ammo"] < c["opening"]["arrows_per_player"]:
                    # First sidestep at the baseline if a bunker blocks this lane.
                    goal = (a["spawn"][0], lane) if abs(a["position"][1] - lane) > 0.1 else center
                elif abs(a["position"][0] - a["spawn"][0]) > c["opening"]["baseline_tolerance_m"]:
                    goal = (a["spawn"][0], lane)
                else:
                    goal = a["spawn"]
                return Action(move=self.move_to(a["position"], goal, a["team"], now), interaction="pickup")
            return super().__call__(obs)
        pos, team = a["position"], a["team"]
        bunker, hold, peek = self._positions(obs)
        if c["rules"].get("single_arrow_shooting") and a["ammo"] > 1:
            if hypot(pos[0] - a["spawn"][0], pos[1] - a["spawn"][1]) <= c["rules"]["stash_radius_m"]:
                return Action(interaction="drop")
            return Action(move=self.move_to(pos, a["spawn"], team, now))
        if not obs.get("combat_started", True):
            return Action(move=self.move_to(pos, a["spawn"], team, now))
        aim, key, interaction, crouch = None, None, "none", False
        if a["reload_left"] > 0.15:
            move = self.move_to(pos, hold, team, now)
            crouch = hypot(pos[0] - bunker.center[0], pos[1] - bunker.center[1]) < 3.5
        elif a["ammo"] == 0:
            direction = 1 if team == "attack" else -1
            advance = c["policy"]["max_advance_past_bunker_m"]
            lo, hi = c["teams"][team]["pickup_x_bounds_m"]
            ground = [b for b in obs["ground_arrows"] if lo <= b["position"][0] <= hi
                      and (b["position"][0] - bunker.center[0]) * direction <= advance
                      and (not b["opening_arrow"] or b["opening_owner"] == a["id"])]
            if ground:
                def cost(b):
                    bx, by = b["position"][:2]
                    exposure = max(0.0, (bx - bunker.center[0]) * direction)
                    return hypot(bx - pos[0], by - pos[1]) + 2.5 * exposure
                arrow = min(ground, key=cost)
                goal = arrow["position"][:2]
                if hypot(goal[0] - pos[0], goal[1] - pos[1]) <= c["physics"]["pickup_radius_m"]:
                    return Action(interaction="pickup", crouch=True)
            else:
                # Remember the public initial depot without seeing through cover.
                goal = (a["spawn"][0] + direction * 0.45, a["spawn"][1])
            move = self.move_to(pos, goal, team, now)
            interaction = "pickup"
        else:
            move = self.move_to(pos, peek, team, now)
            enemies = [e for e in obs["enemies"] if e["status"] == "active"
                       and c["rules"]["min_shot_distance_m"] <= hypot(e["position"][0] - pos[0], e["position"][1] - pos[1]) <= c["policy"]["engage_distance_m"]]
            if enemies and hypot(peek[0] - pos[0], peek[1] - pos[1]) < 0.35:
                enemy = min(enemies, key=lambda e: hypot(e["position"][0] - pos[0], e["position"][1] - pos[1]))
                flight = hypot(enemy["position"][0] - pos[0], enemy["position"][1] - pos[1]) / c["physics"]["arrow_speed_m_s"]
                lead = flight * c["policy"]["moving_target_lead_fraction"]
                aim = (enemy["position"][0] + enemy["velocity"][0] * lead,
                       enemy["position"][1] + enemy["velocity"][1] * lead, enemy["height"] * 0.6)
                key, interaction, move = enemy["id"], "shoot", (0.0, 0.0)
            elif not enemies:
                # Wait at a firing angle; do not chase invisible opponents to mid.
                crouch = False
        move, crouch, dodging = self._sidestep(obs, move, crouch)
        if dodging:
            if c.get("evasion", {}).get("stamina_enabled"):
                return self.evade_action
            aim, key, interaction = None, None, "none"
        return Action(move=move, aim=aim, aim_key=key, interaction=interaction, crouch=crouch)
