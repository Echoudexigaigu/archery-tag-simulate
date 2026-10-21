"""First research model: simultaneous actions, 2-D players and 3-D arrows.

This is a custom multi-agent interface, not a claimed Gym/PettingZoo adapter.
Tick order: timers/respawn, joint movement proposals and releases, chronological
arrow contacts, end-of-tick pickups, termination. Ballistic curves are swept
as short chords; dt is a convergence parameter, not a gameplay speed limit.
"""

from collections import Counter
from copy import deepcopy
from heapq import heappop, heappush
from math import atan2, cos, hypot, isfinite, sin, sqrt
import random

from .entities import Action, Agent, Arrow, Obstacle, Status, TargetRack
from .geometry import ballistic_velocity, lerp, segment_box, segment_cylinder


class Environment:
    def __init__(self, config):
        self.config = deepcopy(config)
        self._validate()
        self.agents = {}
        self.done = False

    def _validate(self):
        c = self.config
        if c.get("status") != "provisional_simulation":
            raise ValueError("Use a complete provisional simulation config, not unresolved baseline.json")
        if c["time"]["dt_s"] <= 0 or c["time"]["round_s"] <= 0:
            raise ValueError("Positive time parameters required")
        if c["rack"]["spot_count"] != 5:
            raise ValueError("This mode uses one five-spot rack")
        width, height = c["rack"]["size_m"]
        r = c["rack"]["spot_radius_m"]
        offsets = c["rack"]["offsets_hv_m"]
        if len(offsets) != 5 or any(abs(y) + r > width / 2 or abs(z) + r > height / 2 for y, z in offsets):
            raise ValueError("All five spots must fit the rack")
        for i, (y, z) in enumerate(offsets):
            if any(hypot(y - a, z - b) < 2 * r for a, b in offsets[:i]):
                raise ValueError("Target spots must not overlap")
        for team in ("attack", "defense"):
            t = c["teams"][team]
            if not 0 <= t["veterans"] <= t["players"]:
                raise ValueError("Invalid veteran count")
            if t["initial_arrows"] < 0 or c["rules"]["carry_limit"] < 1:
                raise ValueError("Invalid resource allocation")
            if t["players"] < 1:
                raise ValueError("Empty teams unsupported")
        if len(c["opening"]["arrow_positions_m"]) != c["teams"]["attack"]["players"]:
            raise ValueError("Opening allocation must match attack player count in this scenario")
        self._validate_rack()

    def _validate_rack(self):
        c = self.config
        x, y, z = c["rack"]["position_xyz_m"]
        width, height = c["rack"]["size_m"]
        L, W = c["field"]["length_m"], c["field"]["width_m"]
        if not (0 < x < L and width / 2 < y < W - width / 2 and z >= height / 2):
            raise ValueError("Rack is outside the field")
        for b in c["obstacles"]:
            bx, by = b["center_xy_m"]
            sx, sy, sz = b["size_xyz_m"]
            if abs(x - bx) <= sx / 2 + 0.05 and abs(y - by) <= sy / 2 + width / 2 and z - height / 2 <= sz:
                raise ValueError("Rack overlaps an obstacle")

    def reset(self, seed=0, record=False, mirror_y=False):
        self.seed, self.rng = seed, random.Random(seed)
        self.t, self.tick, self.done, self.winner = 0.0, 0, False, None
        self.record, self.trace, self.events = record, [], []
        self.counts, self.cover_seconds, self.exposed_seconds = Counter(), 0.0, 0.0
        self.resource_curve, self._metric_clock = [], 0.0
        c, W = self.config, self.config["field"]["width_m"]
        flip = lambda y: W - y if mirror_y else y
        self.mirror_y = mirror_y
        self.obstacles = [Obstacle(b["id"], (b["center_xy_m"][0], flip(b["center_xy_m"][1])), tuple(b["size_xyz_m"])) for b in c["obstacles"]]
        rx, ry, rz = c["rack"]["position_xyz_m"]
        offsets = [(h * (-1 if mirror_y else 1), v) for h, v in c["rack"]["offsets_hv_m"]]
        self.rack = TargetRack((rx, flip(ry), rz), tuple(c["rack"]["size_m"]), offsets, c["rack"]["spot_radius_m"])
        self.agents, self.arrows = {}, {}
        for team in ("attack", "defense"):
            spec = c["teams"][team]
            etas = [self.rng.uniform(*c["skill"]["veteran_eta_range"]) for _ in range(spec["veterans"])]
            etas += [self.rng.uniform(*c["skill"]["novice_eta_range"]) for _ in range(spec["players"] - spec["veterans"])]
            self.rng.shuffle(etas)
            for i, eta in enumerate(etas):
                y = flip(W * (i + 0.5) / spec["players"])
                spawn = (spec["spawn_x_m"], y)
                a = Agent(f"{team}_{i}", team, eta, spawn, spawn, spec["lives"])
                self.agents[a.id] = a
                for j in range(spec["initial_arrows"]):
                    b = self._new_arrow((spawn[0], y, 0.0))
                    if j < c["rules"]["carry_limit"]:
                        self._carry(b, a)
        for x, y in c["opening"]["arrow_positions_m"]:
            self._new_arrow((x, flip(y), 0.0)).opening_arrow = True
        self.total_arrows = len(self.arrows)
        self._sample_metrics()
        return self.get_observation(), {i: {"seed": seed} for i in self.agents}

    def _new_arrow(self, position):
        b = Arrow(len(self.arrows), tuple(position))
        self.arrows[b.id] = b
        return b

    def _carry(self, arrow, agent):
        arrow.state, arrow.carrier = "carried", agent.id
        arrow.velocity = (0.0, 0.0, 0.0)
        arrow.position = (*agent.position, 0.0)
        agent.inventory.append(arrow.id)

    def _ground(self, arrow, position):
        L, W = self.config["field"]["length_m"], self.config["field"]["width_m"]
        arrow.state, arrow.carrier = "ground", None
        arrow.position = (min(L, max(0.0, position[0])), min(W, max(0.0, position[1])), 0.0)
        arrow.velocity, arrow.flight_left = (0.0, 0.0, 0.0), 0.0

    def player_height(self, agent):
        p = self.config["physics"]
        return p["crouched_height_m"] if agent.crouched else p["player_height_m"]

    def release_height(self, agent):
        p = self.config["physics"]
        return p["crouched_release_height_m"] if agent.crouched else p["release_height_m"]

    def line_clear(self, p, q):
        return all(segment_box(p, q, *o.bounds()) is None for o in self.obstacles)

    def valid_move(self, agent, old, new):
        c, r = self.config, self.config["physics"]["player_radius_m"]
        xmin, xmax = c["teams"][agent.team]["move_x_bounds_m"]
        if not (max(r, xmin) <= new[0] <= min(c["field"]["length_m"] - r, xmax) and r <= new[1] <= c["field"]["width_m"] - r):
            return False
        for o in self.obstacles:
            lo, hi = o.bounds(r)
            if segment_box((*old, 0.5), (*new, 0.5), lo, hi) is not None:
                return False
        return True

    def _emit(self, kind, **data):
        self.counts[kind] += 1
        event = {"t": round(self.t, 5), "kind": kind, **data}
        self.step_events.append(event)
        if self.record:
            self.events.append(event)

    def _timers(self, dt):
        c, radius = self.config, self.config["physics"]["player_radius_m"]
        for a in self.agents.values():
            if a.status == Status.ELIMINATED:
                if a.respawn_at is not None and self.t + 1e-9 >= a.respawn_at:
                    free = all(b.status == Status.ELIMINATED or b.id == a.id or hypot(b.position[0] - a.spawn[0], b.position[1] - a.spawn[1]) >= 2 * radius for b in self.agents.values())
                    if free:
                        a.position, a.velocity = a.spawn, (0.0, 0.0)
                        a.protected_until = self.t + c["rules"]["respawn_protection_s"]
                        a.status = Status.INVINCIBLE if a.protected_until > self.t else Status.ACTIVE
                        a.respawn_at, a.aim_elapsed, a.aim_key = None, 0.0, None
                        self._emit("respawn", agent=a.id)
                continue
            if a.status == Status.INVINCIBLE:
                line = c["teams"][a.team]["protection_line_x_m"]
                crossed = a.position[0] > line if a.team == "attack" else a.position[0] < line
                if self.t >= a.protected_until or crossed:
                    a.status = Status.ACTIVE
            a.reload_left = max(0.0, a.reload_left - dt)
            a.catch_left = max(0.0, a.catch_left - dt)
            a.catch_cooldown = max(0.0, a.catch_cooldown - dt)

    def _skill(self, eta, novice, expert):
        return expert + (novice - expert) * (1 - eta)

    def _release(self, a, action):
        c, p, skill = self.config, self.config["physics"], self.config["skill"]
        if a.status != Status.ACTIVE or not a.has_bow or not a.inventory or a.reload_left > 1e-9 or action.aim is None:
            return
        xmin, xmax = c["teams"][a.team]["shoot_x_bounds_m"]
        if not xmin <= a.position[0] <= xmax:
            return
        if hypot(action.aim[0] - a.position[0], action.aim[1] - a.position[1]) < c["rules"]["min_shot_distance_m"]:
            return
        aim_time = self._skill(a.eta, skill["novice_aim_s"], skill["expert_aim_s"])
        if a.aim_elapsed + 1e-9 < aim_time:
            return
        origin = (*a.position, self.release_height(a))
        v = ballistic_velocity(origin, action.aim, p["arrow_speed_m_s"], p["gravity_m_s2"])
        if v is None:
            return
        sigma = self._skill(a.eta, skill["novice_angle_sd_rad"], skill["expert_angle_sd_rad"])
        speed_fraction = hypot(*a.velocity) / p["move_speed_m_s"]
        sigma *= sqrt(1 + skill["movement_variance_multiplier"] * speed_fraction * speed_fraction)
        yaw = atan2(v[1], v[0]) + self.rng.gauss(0, sigma)
        pitch = atan2(v[2], hypot(v[0], v[1])) + self.rng.gauss(0, sigma)
        speed = p["arrow_speed_m_s"]
        b = self.arrows[a.inventory.pop(0)]
        b.state, b.carrier, b.shooter = "flying", None, a.id
        b.position, b.flight_left = origin, p["arrow_max_flight_s"]
        b.velocity = (speed * cos(pitch) * cos(yaw), speed * cos(pitch) * sin(yaw), speed * sin(pitch))
        a.reload_left = self._skill(a.eta, skill["novice_reload_s"], skill["expert_reload_s"])
        a.aim_elapsed = 0.0
        self._emit("shot", agent=a.id, arrow=b.id, team=a.team)

    def _eliminate(self, a, shooter, rewards):
        if a.status != Status.ACTIVE:
            return
        if a.lives is not None:
            a.lives -= 1
        for bid in a.inventory:
            self._ground(self.arrows[bid], (*a.position, 0.0))
        a.inventory.clear()
        a.status, a.velocity = Status.ELIMINATED, (0.0, 0.0)
        a.aim_elapsed, a.reload_left, a.pickup_elapsed = 0.0, 0.0, 0.0
        a.respawn_at = self.t + self.config["teams"][a.team]["respawn_delay_s"] if a.lives is None or a.lives > 0 else None
        rewards[a.id] += self.config["rewards"]["being_hit"]
        rewards[shooter.id] += self.config["rewards"]["hit_enemy"]
        self._emit("hit", victim=a.id, shooter=shooter.id)

    def _contacts(self, b, p, q, old_positions, new_positions):
        c, radius = self.config, self.config["physics"]["arrow_radius_m"]
        hits = []
        for j, o in enumerate(self.obstacles):
            u = segment_box(p, q, *o.bounds(radius))
            if u is not None:
                hits.append((u, 0, "obstacle", j))
        rack = self.rack
        rx, ry, rz = rack.position
        # The rack faces -x. Its surrounding rectangular frame is solid.
        if p[0] < rx <= q[0] and q[0] > p[0]:
            u = (rx - p[0]) / (q[0] - p[0])
            point = lerp(p, q, u)
            if abs(point[1] - ry) <= rack.size[0] / 2 + radius and abs(point[2] - rz) <= rack.size[1] / 2 + radius:
                spot = next((k for k in range(5) if hypot(point[1] - rack.spot(k)[1], point[2] - rack.spot(k)[2]) <= rack.radius + radius), -1)
                # A spot needs the foam head to overlap its disk. A cleared hole
                # permits passage only if the complete arrow head fits through it.
                if spot >= 0 and not rack.standing[spot] and c["rack"]["cleared_holes_pass_through"] and hypot(point[1] - rack.spot(spot)[1], point[2] - rack.spot(spot)[2]) <= max(0, rack.radius - radius):
                    pass
                else:
                    hits.append((u, 0, "rack", spot))
        for a in self.agents.values():
            if a.id == b.shooter or a.status == Status.ELIMINATED:
                continue
            u = segment_cylinder(p, q, old_positions[a.id], new_positions[a.id], c["physics"]["player_radius_m"] + radius, self.player_height(a) + radius)
            if u is not None:
                hits.append((u, 1, "player", a.id))
        if q[2] <= 0 and p[2] >= 0:
            u = p[2] / max(1e-12, p[2] - q[2])
            hits.append((u, 2, "ground", -1))
        L, W = c["field"]["length_m"], c["field"]["width_m"]
        for axis, bound in ((0, 0.0), (0, L), (1, 0.0), (1, W)):
            if (q[axis] < 0 and bound == 0) or (q[axis] > bound and bound > 0):
                u = (bound - p[axis]) / (q[axis] - p[axis])
                if 0 <= u <= 1:
                    hits.append((u, 2, "boundary", -1))
        if b.flight_left <= c["time"]["dt_s"]:
            hits.append((1.0, 2, "expired", -1))
        return sorted(hits)

    def _fly(self, dt, old_positions, new_positions, actions, rewards):
        c, trajectories, candidates, heap = self.config, {}, {}, []
        for b in self.arrows.values():
            if b.state != "flying":
                continue
            p, v = b.position, b.velocity
            q = (p[0] + v[0] * dt, p[1] + v[1] * dt, p[2] + v[2] * dt - 0.5 * c["physics"]["gravity_m_s2"] * dt * dt)
            trajectories[b.id] = (p, q)
            candidates[b.id] = self._contacts(b, p, q, old_positions, new_positions)
            if candidates[b.id]:
                u, priority, kind, target = candidates[b.id][0]
                heappush(heap, (u, priority, b.id, 0, kind, target))
        while heap:
            u = heap[0][0]
            batch = []
            while heap and abs(heap[0][0] - u) < 1e-9:
                batch.append(heappop(heap))
            alive_before = {a.id: a.status for a in self.agents.values()}
            victims = {}
            for _, priority, bid, idx, kind, target in batch:
                b = self.arrows[bid]
                if b.state != "flying":
                    continue
                p, q = trajectories[bid]
                point = lerp(p, q, u)
                if kind == "player":
                    a = self.agents[target]
                    if alive_before[a.id] == Status.ELIMINATED:
                        idx += 1
                        if idx < len(candidates[bid]):
                            uu, pp, kk, tt = candidates[bid][idx]
                            heappush(heap, (uu, pp, bid, idx, kk, tt))
                        continue
                    shooter = self.agents[b.shooter]
                    caught = False
                    if a.team != shooter.team and alive_before[a.id] == Status.ACTIVE and a.catch_left > 0 and len(a.inventory) < c["rules"]["carry_limit"]:
                        action = actions[a.id]
                        if action.aim is not None:
                            fx, fy = action.aim[0] - a.position[0], action.aim[1] - a.position[1]
                            denom = hypot(fx, fy) * hypot(b.velocity[0], b.velocity[1])
                            facing = -(fx * b.velocity[0] + fy * b.velocity[1]) / denom if denom > 0 else -1
                            caught = facing >= c["rules"]["catch_min_cos"] and self.rng.random() < c["rules"]["catch_success_probability"]
                    if caught:
                        self._carry(b, a)
                        rewards[a.id] += c["rewards"]["catch"]
                        self._emit("catch", agent=a.id, arrow=bid)
                    else:
                        self._ground(b, point)
                        if a.team != shooter.team and alive_before[a.id] == Status.ACTIVE:
                            victims.setdefault(a.id, shooter)
                        elif a.team == shooter.team:
                            self._emit("friendly_block", agent=a.id)
                elif kind == "rack":
                    if target >= 0 and self.rack.standing[target] and self.agents[b.shooter].team == "attack":
                        self.rack.standing[target] = False
                        rewards[b.shooter] += c["rewards"]["target"]
                        self._emit("target", spot=target, shooter=b.shooter)
                    self._ground(b, point)
                else:
                    self._ground(b, point)
            for aid, shooter in victims.items():
                self.agents[aid].position = lerp(old_positions[aid], new_positions[aid], u)
                self._eliminate(self.agents[aid], shooter, rewards)
        for bid, (p, q) in trajectories.items():
            b = self.arrows[bid]
            if b.state == "flying":
                b.position = q
                b.velocity = (b.velocity[0], b.velocity[1], b.velocity[2] - c["physics"]["gravity_m_s2"] * dt)
                b.flight_left -= dt

    def _pickup(self, actions, dt):
        c, proposals = self.config, []
        for a in self.agents.values():
            if a.status == Status.ELIMINATED or actions[a.id].interaction != "pickup" or len(a.inventory) >= c["rules"]["carry_limit"]:
                a.pickup_elapsed = 0.0
                continue
            a.pickup_elapsed += dt
            if a.pickup_elapsed + 1e-9 < c["physics"]["pickup_s"]:
                continue
            xmin, xmax = c["teams"][a.team]["pickup_x_bounds_m"]
            for b in self.arrows.values():
                if b.state != "ground" or not xmin <= b.position[0] <= xmax:
                    continue
                if b.opening_arrow and a.team == "attack" and a.opening_received:
                    continue
                distance = hypot(b.position[0] - a.position[0], b.position[1] - a.position[1])
                if distance <= c["physics"]["pickup_radius_m"]:
                    proposals.append((distance, self.rng.random(), a.id, b.id))
        used_agents, used_arrows = set(), set()
        for distance, _, aid, bid in sorted(proposals):
            if aid in used_agents or bid in used_arrows:
                continue
            a, b = self.agents[aid], self.arrows[bid]
            if b.state != "ground":
                continue
            self._carry(b, a)
            if b.opening_arrow and a.team == "attack":
                a.opening_received = True
            b.opening_arrow = False
            a.pickup_elapsed = 0.0
            if a.status == Status.INVINCIBLE:
                a.status = Status.ACTIVE
            self._emit("pickup", agent=aid, arrow=bid)
            used_agents.add(aid)
            used_arrows.add(bid)

    def step(self, actions, observe=True):
        if self.done:
            raise RuntimeError("Episode is finished; call reset()")
        if set(actions) - set(self.agents):
            raise ValueError("Unknown agent id")
        if any(not isinstance(a, Action) for a in actions.values()):
            raise TypeError("Actions must be Action objects")
        if any(len(a.move) != 2 or not all(isfinite(v) for v in a.move) or (a.aim is not None and (len(a.aim) != 3 or not all(isfinite(v) for v in a.aim))) for a in actions.values()):
            raise ValueError("Action coordinates must be finite, with 2-D movement and 3-D aim")
        actions = {aid: actions.get(aid, Action()) for aid in self.agents}
        self.step_events = []
        dt = min(self.config["time"]["dt_s"], self.config["time"]["round_s"] - self.t)
        rewards = {aid: 0.0 for aid in self.agents}
        self._timers(dt)
        old_positions = {aid: a.position for aid, a in self.agents.items()}
        proposals = dict(old_positions)
        active = [a for a in self.agents.values() if a.status != Status.ELIMINATED]
        for a in active:
            action = actions[a.id]
            a.crouched = action.crouch
            dx, dy = action.move
            norm = max(1.0, hypot(dx, dy))
            speed = self.config["physics"]["move_speed_m_s"] * (self.config["physics"]["crouch_speed_fraction"] if a.crouched else 1.0)
            new = (a.position[0] + dx / norm * speed * dt, a.position[1] + dy / norm * speed * dt)
            if self.valid_move(a, a.position, new):
                proposals[a.id] = new
        # Symmetric rejection of crossing/overlapping proposals.
        radius = self.config["physics"]["player_radius_m"]
        # A stopped player can block a third player's previously clear proposal.
        # Repeat until no further movements need cancellation.
        for _ in range(len(active) + 1):
            rejected = set()
            for j, a in enumerate(active):
                for b in active[:j]:
                    p, q = old_positions[a.id], proposals[a.id]
                    u, v = old_positions[b.id], proposals[b.id]
                    rx, ry = p[0] - u[0], p[1] - u[1]
                    dx, dy = q[0] - p[0] - v[0] + u[0], q[1] - p[1] - v[1] + u[1]
                    fraction = max(0.0, min(1.0, -(rx * dx + ry * dy) / max(1e-12, dx * dx + dy * dy)))
                    if hypot(rx + fraction * dx, ry + fraction * dy) < 2 * radius - 1e-8:
                        rejected.update((a.id, b.id))
            changed = [aid for aid in rejected if proposals[aid] != old_positions[aid]]
            if not changed:
                break
            for aid in changed:
                proposals[aid] = old_positions[aid]
        for a in active:
            action = actions[a.id]
            old, new = old_positions[a.id], proposals[a.id]
            a.velocity = ((new[0] - old[0]) / dt, (new[1] - old[1]) / dt)
            if action.aim is None or a.reload_left > 0 or a.status != Status.ACTIVE:
                a.aim_elapsed, a.aim_key = 0.0, None
            else:
                if action.aim_key != a.aim_key:
                    a.aim_elapsed = 0.0
                a.aim_key = action.aim_key
                a.aim_elapsed += dt
            if action.interaction == "catch" and self.config["rules"]["catch_enabled"] and a.status == Status.ACTIVE and a.catch_cooldown == 0:
                a.catch_left = self.config["rules"]["catch_window_s"]
                a.catch_cooldown = self.config["rules"]["catch_cooldown_s"]
            elif action.interaction == "shoot":
                self._release(a, action)
        self._fly(dt, old_positions, proposals, actions, rewards)
        for a in active:
            a.position = proposals[a.id]
        self.t = round(self.t + dt, 10)
        self.tick += 1
        self._pickup(actions, dt)
        if not any(self.rack.standing):
            self.done, self.winner = True, "attack"
            for a in self.agents.values():
                rewards[a.id] += self.config["rewards"]["win"] if a.team == self.winner else 0.0
        elif self.t + 1e-8 >= self.config["time"]["round_s"]:
            self.done, self.winner = True, "defense"
            for a in self.agents.values():
                rewards[a.id] += self.config["rewards"]["win"] if a.team == self.winner else 0.0
        self._metric_clock += dt
        if self._metric_clock + 1e-9 >= self.config["metrics"]["sample_every_s"] or self.done:
            self._sample_metrics(self._metric_clock)
            self._metric_clock = 0.0
        obs = self.get_observation() if observe else {}
        terms = {aid: self.done for aid in self.agents}
        truncs = {aid: False for aid in self.agents}
        infos = {aid: {"events": list(self.step_events), "winner": self.winner} for aid in self.agents}
        return obs, rewards, terms, truncs, infos

    def get_observation(self, agent_id=None):
        if agent_id is None:
            return {aid: self.get_observation(aid) for aid in self.agents}
        a = self.agents[agent_id]
        eye = (*a.position, self.player_height(a) * 0.9)
        reach = self.config["physics"]["vision_range_m"]
        visible = lambda point: hypot(point[0] - a.position[0], point[1] - a.position[1]) <= reach and self.line_clear(eye, point)
        enemies = []
        for b in self.agents.values():
            if b.team != a.team and b.status != Status.ELIMINATED and visible((*b.position, self.player_height(b) * 0.9)):
                enemies.append({"id": b.id, "position": b.position, "velocity": b.velocity, "height": self.player_height(b), "status": b.status.value})
        ground = [{"id": b.id, "position": b.position, "opening_arrow": b.opening_arrow} for b in self.arrows.values() if b.state == "ground" and visible((b.position[0], b.position[1], 0.05))]
        flying = [{"id": b.id, "position": b.position, "velocity": b.velocity} for b in self.arrows.values() if b.state == "flying" and visible(b.position)]
        return {"time": self.t, "self": {"id": a.id, "team": a.team, "position": a.position, "velocity": a.velocity, "status": a.status.value, "eta": a.eta, "ammo": len(a.inventory), "has_bow": a.has_bow, "reload_left": a.reload_left, "aim_elapsed": a.aim_elapsed, "opening_received": a.opening_received},
                "enemies": enemies, "ground_arrows": ground, "flying_arrows": flying,
                "spots": [{"id": k, "position": self.rack.spot(k), "standing": self.rack.standing[k]} for k in range(5)]}

    def assert_invariants(self):
        carried = [bid for a in self.agents.values() for bid in a.inventory]
        assert len(carried) == len(set(carried))
        assert set(carried) == {b.id for b in self.arrows.values() if b.state == "carried"}
        assert len(self.arrows) == self.total_arrows
        for a in self.agents.values():
            assert len(a.inventory) <= self.config["rules"]["carry_limit"]
            assert all(self.arrows[bid].carrier == a.id for bid in a.inventory)
            if a.status == Status.ELIMINATED:
                assert not a.inventory
        for b in self.arrows.values():
            assert b.state in ("ground", "carried", "flying")
            assert (b.carrier is not None) == (b.state == "carried")

    def _sample_metrics(self, elapsed=0.0):
        active = [a for a in self.agents.values() if a.status != Status.ELIMINATED]
        for a in active:
            enemies = [b for b in active if b.team != a.team]
            if enemies:
                self.exposed_seconds += elapsed
                center = (*a.position, self.player_height(a) * 0.6)
                if any(not self.line_clear((*b.position, self.release_height(b)), center) for b in enemies):
                    self.cover_seconds += elapsed
        states = Counter(b.state for b in self.arrows.values())
        self.resource_curve.append({"t": self.t, "ground": states["ground"], "carried": states["carried"], "flying": states["flying"], "attack_ammo": sum(len(a.inventory) for a in active if a.team == "attack"), "defense_ammo": sum(len(a.inventory) for a in active if a.team == "defense"), "shots": self.counts["shot"], "remaining_spots": sum(self.rack.standing)})
        if self.record:
            self.trace.append({"t": self.t, "players": [{"id": a.id, "team": a.team, "position": a.position, "status": a.status.value, "ammo": len(a.inventory), "eta": a.eta, "crouched": a.crouched} for a in self.agents.values()], "arrows": [{"position": b.position, "state": b.state} for b in self.arrows.values() if b.state != "carried"], "spots": list(self.rack.standing)})

    def summary(self):
        return {"seed": self.seed, "winner": self.winner, "duration_s": self.t, "clear_time_s": self.t if self.winner == "attack" else None,
                "remaining_spots": sum(self.rack.standing), "shots": self.counts["shot"], "hits": self.counts["hit"], "pickups": self.counts["pickup"], "respawns": self.counts["respawn"],
                "cover_utilization": self.cover_seconds / self.exposed_seconds if self.exposed_seconds else None,
                "eta": {a.id: a.eta for a in self.agents.values()}, "resource_curve": self.resource_curve}
