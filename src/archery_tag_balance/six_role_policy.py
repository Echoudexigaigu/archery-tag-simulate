"""Public-map six-role tactics; cover has value by denying useful shots."""
from collections import Counter, deque
from math import hypot, log

from .cover_policy import CoverPolicy
from .entities import Action
from .geometry import advance_arrow, ballistic_velocity, segment_box, segment_cylinder
from .human_skirmish import ROLES


class SixRolePolicy(CoverPolicy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = ROLES[self.index]
        self.tempo = self.rng.uniform(0.8, 1.25)
        self.latency = self.rng.uniform(0.2, 0.5)
        self.lead_fraction = self.rng.uniform(0.2, 0.6)
        self.target_interest = self.rng.uniform(0.16, 0.32)
        self.histories = {}
        self.phase, self.next_peek, self.peek_until = 'hide', None, 0
        self.peek_sign = 1
        self.seen_shot, self.need_retreat = -100.0, False
        self.target_key, self.lock_until = None, 0
        self.aim_cache, self.next_aim_update = None, 0
        self.diagnostics = Counter()
        self.shift, self.next_shift = (0, 0), 0
        self.was_nocking = False
        self.depot_checked = False
        self.resupply_scan_next, self.resupply_scan_until = 0.0, 0.0

    def _positions(self, obs):
        a, c = obs['self'], self.config
        direction = 1 if a['team'] == 'attack' else -1
        width, mid = c['field']['width_m'], c['field']['length_m'] / 2
        bunkers = [o for o in self.nav.obstacles if not o.id.startswith('rack_') and (o.center[0] < mid) == (direction == 1)]
        left_y = width - 3 if direction == 1 else 3
        if self.mirror_y:
            left_y = width - left_y
        left = min(bunkers, key=lambda o: abs(o.center[1] - left_y))
        right = max(bunkers, key=lambda o: abs(o.center[1] - left_y))
        bunker = left if self.index < 3 else right
        depth = bunker.size[0] / 2 + c['physics']['player_radius_m']
        if 'cover' in self.role:
            hold = (bunker.center[0] - direction * (depth + 0.13), bunker.center[1])
            inner = -1 if bunker.center[1] > width / 2 else 1
            offset = inner * self.peek_sign * (bunker.size[1] / 2 + c['physics']['player_radius_m'] + 0.12)
            peek = (bunker.center[0] - direction * (depth + 0.12), bunker.center[1] + offset)
        elif 'flank' in self.role:
            outward = 1 if bunker.center[1] > width / 2 else -1
            # The panel cuts off an inside cross-field angle; the outside lane
            # remains open. The flank player never shares the cover occupant.
            hold = (bunker.center[0] - direction * 1.75, bunker.center[1] + outward * 1.35)
            peek = (bunker.center[0] - direction * 0.95 + direction * self.shift[0],
                    bunker.center[1] + outward * 1.65 + self.shift[1])
        else:
            local_y = 5.05 if self.role == 'center_1' else 6.95
            world_y = width - local_y if direction == 1 else local_y
            if self.mirror_y:
                world_y = width - world_y
            depth_x = 6.0 if self.role == 'center_1' else 5.5
            x = depth_x if direction == 1 else c['field']['length_m'] - depth_x
            hold = peek = (x + direction * self.shift[0], world_y + self.shift[1])
        return bunker, hold, peek

    def _clear_arc(self, obs, aim, target_key, crouch=False):
        """Use the nominal flight to reject shots through panels or teammates.

        This is only a visibility/occlusion heuristic; it cannot cancel a later
        imperfect release, target movement or lucky miss into a different object.
        """
        a, p = obs['self'], self.config['physics']
        origin = (*a['position'], p['crouched_release_height_m'] if crouch else p['release_height_m'])
        v = ballistic_velocity(origin, aim, p['arrow_speed_m_s'], p['gravity_m_s2'],
                               p.get('linear_drag_s_inv', 0), p['arrow_max_flight_s'])
        if v is None:
            return False
        distance, horizontal = hypot(aim[0] - origin[0], aim[1] - origin[1]), hypot(v[0], v[1])
        drag = p.get('linear_drag_s_inv', 0)
        flight = -log(max(1e-8, 1 - drag * distance / horizontal)) / drag if drag else distance / horizontal
        ignored = 'rack_' + target_key.split(':')[1] if target_key.startswith('rack:') else None
        previous = origin
        for i in range(1, 9):
            point, _ = advance_arrow(origin, v, flight * i / 8, p['gravity_m_s2'], drag)
            for o in self.nav.obstacles:
                if o.id != ignored and segment_box(previous, point, *o.bounds(p['arrow_radius_m'])) is not None:
                    return False
            for person in obs.get('teammates', []):
                if segment_cylinder(previous, point, person['position'], person['position'],
                                    p['player_radius_m'] + p['arrow_radius_m'], 1.5) is not None:
                    return False
            previous = point
        return True

    def _remember(self, obs):
        for enemy in obs['enemies']:
            history = self.histories.setdefault(enemy['id'], deque(maxlen=12))
            history.append((obs['time'], enemy.copy()))

    def _targets(self, obs):
        a, now = obs['self'], obs['time']
        bodies, racks = [], []
        for enemy in obs['enemies']:
            if enemy['status'] != 'active':
                continue
            distance = hypot(enemy['position'][0] - a['position'][0], enemy['position'][1] - a['position'][1])
            if not self.config['rules']['min_shot_distance_m'] <= distance <= self.config['policy']['engage_distance_m']:
                continue
            point = (*enemy['position'], enemy['height'] * 0.58)
            self.diagnostics['body_candidates'] += 1
            if not self._clear_arc(obs, point, enemy['id']):
                self.diagnostics['blocked_body_candidates_avoided'] += 1
                continue
            bodies.append((enemy['id'], point, enemy, distance))
        for rack in obs['racks']:
            if rack['team'] == a['team']:
                continue
            for k, alive in enumerate(rack['standing']):
                if not alive:
                    continue
                point = rack['spots'][k]
                distance = hypot(point[0] - a['position'][0], point[1] - a['position'][1])
                key = f"rack:{rack['team']}:{k}"
                if self.config['rules']['min_shot_distance_m'] <= distance <= self.config['policy']['engage_distance_m'] and self._clear_arc(obs, point, key):
                    racks.append((key, point, None, distance))
        all_targets = bodies + racks
        # Hold a choice long enough to aim; switching every decision restarts
        # the aim timer and makes both cadence and tactics pathological.
        chosen = next((p for p in all_targets if p[0] == self.target_key), None)
        if chosen is None or now >= self.lock_until:
            pool = racks if racks and (not bodies or self.rng.random() < self.target_interest) else bodies
            if not pool:
                self.target_key, self.aim_cache = None, None
                return None
            chosen = min(pool, key=lambda v: v[3] * self.rng.uniform(0.85, 1.2))
            changed = chosen[0] != self.target_key
            self.target_key, self.lock_until = chosen[0], now + self.rng.uniform(2.5, 5.0)
            if changed:
                self.aim_cache, self.next_aim_update = None, 0
        return chosen

    def _aim(self, obs, target):
        key, point, enemy, distance = target
        now = obs['time']
        if self.aim_cache is None or now >= self.next_aim_update:
            if enemy is not None:
                history = self.histories.get(key, [])
                old = [e for t, e in history if t <= now - self.latency]
                snapshot = old[-1] if old else (history[0][1] if history else enemy)
                lead = distance / self.config['physics']['arrow_speed_m_s'] * self.lead_fraction
                point = (snapshot['position'][0] + snapshot['velocity'][0] * lead,
                         snapshot['position'][1] + snapshot['velocity'][1] * lead,
                         snapshot['height'] * self.rng.uniform(0.5, 0.66))
            self.aim_cache = point
            self.next_aim_update = now + self.rng.uniform(0.25, 0.55)
        return self.aim_cache

    def _resupply(self, obs, bunker):
        a, now, c = obs['self'], obs['time'], self.config
        direction = 1 if a['team'] == 'attack' else -1
        lo, hi = c['teams'][a['team']]['pickup_x_bounds_m']
        lane_width = 1.75 if 'cover' in self.role else 1.6 if 'flank' in self.role else 2.1
        local = [b for b in obs['ground_arrows'] if lo <= b['position'][0] <= hi
                 and (not b['opening_arrow'] or b['opening_owner'] == a['id'])
                 and abs(b['position'][1] - a['spawn'][1]) <= lane_width]
        safe = [b for b in local if (b['position'][0] - bunker.center[0]) * direction <= 2.0]
        ground = safe or local  # Extend forward only to recover a known arrow.
        if ground:
            def cost(b):
                x, y = b['position'][:2]
                exposure = max(0, (x - bunker.center[0]) * direction)
                return hypot(x - a['position'][0], y - a['position'][1]) + 3.0 * exposure + 1.2 * abs(y - a['spawn'][1])
            arrow = min(ground, key=cost)
            goal = tuple(arrow['position'][:2])
            # Stop, bend down, then spend the sampled pickup duration.
            if hypot(goal[0] - a['position'][0], goal[1] - a['position'][1]) < c['physics']['pickup_radius_m'] - 0.05:
                return Action(interaction='pickup', crouch=True)
        else:
            depot = (a['spawn'][0] + direction * 0.45, a['spawn'][1])
            if not self.depot_checked and hypot(a['position'][0] - depot[0], a['position'][1] - depot[1]) > 0.65:
                goal = depot
            else:
                self.depot_checked = True
                _, hold, peek = self._positions(obs)
                if now >= self.resupply_scan_next:
                    self.resupply_scan_until = now + 1.4
                    self.resupply_scan_next = now + self.rng.uniform(3.0, 5.5)
                scanning = now < self.resupply_scan_until
                goal = peek if scanning else hold
                return Action(move=self.move_to(a['position'], goal, a['team'], now),
                              crouch='cover' in self.role and not scanning)
        lo, hi = c['teams'][a['team']]['move_x_bounds_m']
        goal = max(lo, min(hi, goal[0])), max(0.3, min(c['field']['width_m'] - 0.3, goal[1]))
        return Action(move=self.move_to(a['position'], goal, a['team'], now))

    def _act(self, obs):
        a, c, now = obs['self'], self.config, obs['time']
        if a['status'] == 'eliminated':
            self.phase, self.next_peek = 'hide', None
            self.gesture_until = 0
            return Action()
        if not a['shoot_unlocked'] or a['ammo'] > 1 or not obs['combat_started']:
            return super()._act(obs)
        self._remember(obs)
        is_cover = 'cover' in self.role
        if not is_cover and now >= self.next_shift:
            self.shift = (self.rng.uniform(-0.35, 0.35), self.rng.uniform(-0.35, 0.35))
            self.next_shift = now + self.rng.uniform(5.0, 9.0)
        bunker, hold, peek = self._positions(obs)
        pos, team = a['position'], a['team']
        if a['last_shot_at'] > self.seen_shot:
            self._shot_finished(obs)
        follow_through = self._follow_through(obs)
        if follow_through is not None:
            return self._evading_action(obs, follow_through)
        if self.need_retreat:
            if hypot(pos[0] - hold[0], pos[1] - hold[1]) > 0.18:
                return self._evading_action(obs, Action(move=self.move_to(pos, hold, team, now), crouch=True))
            self.need_retreat = False
        if a['ammo'] == 0:
            return self._evading_action(obs, self._resupply(obs, bunker))
        if a['reload_left'] > 0:
            self.phase = 'hide'
            self.was_nocking = True
            return self._evading_action(obs, Action(move=self.move_to(pos, hold, team, now), crouch=is_cover or 'flank' in self.role))
        if is_cover:
            if self.was_nocking:
                # Loaded does not mean everyone instantly exposes themselves.
                self.next_peek = now + self.rng.uniform(0.8, 2.1) * self.tempo
                self.was_nocking = False
            if self.next_peek is None:
                self.next_peek = now + self.rng.uniform(0.5, 2.3) * self.tempo
            if self.phase == 'hide':
                if now < self.next_peek or hypot(pos[0] - hold[0], pos[1] - hold[1]) > 0.22:
                    self.diagnostics['hide_decisions'] += 1
                    return self._evading_action(obs, Action(move=self.move_to(pos, hold, team, now), crouch=True))
                self.phase = 'peek'
                self.peek_sign = 1 if self.rng.random() < 0.7 else -1
                _, hold, peek = self._positions(obs)
                self.peek_until = now + a['aim_required'] + self.rng.uniform(0.9, 1.7)
            if now >= self.peek_until:
                self.phase = 'hide'
                self.next_peek = now + self.rng.uniform(1.5, 3.2) * self.tempo
                self.target_key, self.aim_cache = None, None
                return Action(move=self.move_to(pos, hold, team, now), crouch=True)
            self.diagnostics['peek_decisions'] += 1
        move = self.move_to(pos, peek, team, now)
        if hypot(pos[0] - peek[0], pos[1] - peek[1]) > 0.35:
            return self._evading_action(obs, Action(move=move))
        target = self._targets(obs)
        if target is None:
            return self._evading_action(obs, Action())
        aim = self._aim(obs, target)
        # Recheck the held estimate after a sidestep; never intentionally fire
        # through our own panel or a teammate just because the target is locked.
        if not self._clear_arc(obs, aim, target[0]):
            return self._evading_action(obs, Action())
        return self._evading_action(obs, Action(aim=aim, aim_key=target[0], interaction='shoot'))

    def _evading_action(self, obs, action):
        move, crouch, dodging = self._compact_evade(obs, action.move, action.crouch)
        return self.evade_action if dodging else action

    def _shot_finished(self, obs):
        a, now = obs['self'], obs['time']
        self.seen_shot, self.need_retreat = a['last_shot_at'], 'cover' in self.role
        self.phase = 'hide'
        self.next_peek = now + self.rng.uniform(1.3, 3.0) * self.tempo
        self.target_key, self.aim_cache = None, None

    def _follow_through(self, obs):
        return None
