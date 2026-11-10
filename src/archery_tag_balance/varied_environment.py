"""Bounded variable flights, personal aim styles and communicated arrow recovery."""
from math import atan2, cos, exp, hypot, log, radians, sin, sqrt

from .entities import Status
from .geometry import advance_arrow
from .human_skirmish import HumanSkirmishEnvironment


def landing_time(origin, velocity, gravity, drag, ceiling=2.4):
    """First ground crossing; the ceiling is only an emergency safety limit."""
    if advance_arrow(origin, velocity, ceiling, gravity, drag)[0][2] > 0:
        return ceiling
    lo, hi = 0.0, ceiling
    for _ in range(42):
        mid = (lo + hi) / 2
        if advance_arrow(origin, velocity, mid, gravity, drag)[0][2] > 0:
            lo = mid
        else:
            hi = mid
    return hi


class VariedSkirmishEnvironment(HumanSkirmishEnvironment):
    def _setup_opening(self):
        self.supply_memory = {t: {} for t in self.config['teams']}
        self.supply_claims = {t: {} for t in self.config['teams']}
        self.supply_snapshot = {t: [] for t in self.config['teams']}
        self.supply_progress, self.supply_avoid = {}, {}
        self.next_supply_update, self.supply_dirty = 0.0, True
        self.empty_since = {}
        super()._setup_opening()
        # Nine ordinary follow-through habits and three small-step habits per
        # match, shuffled independently of skill and playing position.
        habits = ['continue'] * 9 + ['sidestep', 'sidestep', 'withdraw']
        self.rng.shuffle(habits)
        for j, a in enumerate(self.agents.values()):
            style = self.rng.choices(['snap', 'balanced', 'deliberate'], [0.28, 0.44, 0.28])[0]
            bounds = {'snap': (0.25, 0.65), 'balanced': (0.8, 1.5), 'deliberate': (1.8, 3.1)}[style]
            a.human_profile.update(aim_style=style, personal_aim_s=self.rng.uniform(*bounds),
                                   follow_through=habits[j], draw_power=self.rng.uniform(0.93, 1.05))
            self.empty_since[a.id] = 0.0

    def _sample_aim_duration(self, a):
        base = a.human_profile['personal_aim_s'] * (1.15 - 0.3 * a.eta)
        return self._sample_duration(base, 0.18, 0.2, 4.1)

    def _on_aim_progress(self, a, action, dt):
        if a.aim_elapsed <= 0 or a.reload_left > 0 or action.evasion_kind or hypot(*a.velocity) > 0.3:
            a.steady_aim_s, a.steady_aim_key = 0.0, None
        else:
            if a.steady_aim_key != action.aim_key:
                a.steady_aim_s = 0.0
            a.steady_aim_s += dt
            a.steady_aim_key = action.aim_key

    def _accuracy_multiplier(self, a):
        # Quick releases pay a real dispersion cost. Standing still and aiming
        # helps, with diminishing returns and a nonzero accuracy floor.
        steady = min(3.0, a.steady_aim_s)
        factor = 1.30 - 0.52 * (1 - exp(-steady / 0.95))
        overholding = min(0.25, max(0.0, a.aim_elapsed - 4.0) * 0.08)
        return factor + overholding

    def _launch_velocity(self, a, origin, target):
        v = super()._launch_velocity(a, origin, target)
        if v is None:
            return None
        physics = self.config['physics']
        speed = min(self.config['flight_variation']['max_speed_m_s'], sqrt(sum(x*x for x in v)) * a.human_profile['draw_power'])
        yaw = atan2(v[1], v[0])
        pitch = max(-0.12, min(radians(self.config['flight_variation']['max_elevation_degrees']), atan2(v[2], hypot(v[0], v[1]))))
        v = speed*cos(pitch)*cos(yaw), speed*cos(pitch)*sin(yaw), speed*sin(pitch)
        duration = landing_time(origin, v, physics['gravity_m_s2'], physics.get('linear_drag_s_inv', 0), physics['arrow_max_flight_s'])
        self.last_launch[a.id].update(speed=speed, planned_flight_s=duration,
                                     aim_style=a.human_profile['aim_style'], steady_aim_s=a.steady_aim_s,
                                     accuracy_multiplier=self._accuracy_multiplier(a))
        return v

    def _release(self, a, action):
        bid = a.inventory[0] if a.inventory else None
        before = self.counts['shot']
        super()._release(a, action)
        if self.counts['shot'] != before:
            b = self.arrows[bid]
            b.planned_flight_s = self.last_launch[a.id]['planned_flight_s']
            b.flight_left = b.planned_flight_s + 1e-8
            self.empty_since[a.id] = self.t

    def _ground(self, arrow, position):
        if arrow.state == 'flying' and arrow.shooter is not None:
            p = self.config['physics']
            horizontal = hypot(*arrow.velocity[:2])
            distance = hypot(position[0]-arrow.position[0], position[1]-arrow.position[1])
            drag = p.get('linear_drag_s_inv', 0)
            partial = -log(max(1e-8, 1-drag*distance/max(1e-9,horizontal)))/drag if drag else distance/max(1e-9,horizontal)
            self._emit('flight_end', arrow=arrow.id, shooter=arrow.shooter,
                       duration=max(0.0,self.t-arrow.released_at)+min(self.config['time']['dt_s'],partial),
                       planned_flight_s=arrow.planned_flight_s)
        super()._ground(arrow, position)
        self.supply_dirty = True

    def _carry(self, arrow, agent):
        super()._carry(arrow, agent)
        for memory in getattr(self, 'supply_memory', {}).values():
            memory.pop(arrow.id, None)
        self.supply_dirty = True

    def _update_rule_state(self):
        super()._update_rule_state()
        if self.combat_started and (self.supply_dirty or self.t + 1e-9 >= self.next_supply_update):
            for team in self.config['teams']:
                self._refresh_supply(team)
            self.next_supply_update, self.supply_dirty = self.t + 0.4, False

    def _refresh_supply(self, team):
        """Radio reports of arrows actually seen by at least one teammate."""
        friends = [a for a in self.agents.values() if a.team == team and a.status != Status.ELIMINATED]
        lo, hi = self.config['teams'][team]['pickup_x_bounds_m']
        memory = self.supply_memory[team]
        for b in self.arrows.values():
            if b.state != 'ground' or b.opening_arrow or not lo <= b.position[0] <= hi:
                continue
            for friend in friends:
                eye = (*friend.position, self.player_height(friend)*0.9)
                if hypot(b.position[0]-friend.position[0],b.position[1]-friend.position[1]) <= self.config['physics']['vision_range_m'] and self.line_clear(eye,(*b.position[:2],0.05)):
                    memory[b.id] = dict(id=b.id,position=b.position,seen_at=self.t,observer=friend.id)
                    break
        for bid in list(memory):
            # Every pickup is broadcast by the team; hidden undiscovered ground
            # arrows are never inserted into this memory.
            if self.arrows[bid].state != 'ground' or self.t-memory[bid]['seen_at'] > 12:
                memory.pop(bid)
        empty = {a.id:a for a in friends if not a.inventory and a.shoot_unlocked}
        claims = self.supply_claims[team]
        for aid, bid in list(claims.items()):
            if aid not in empty or bid not in memory:
                claims.pop(aid)
                continue
            a = empty[aid]
            stamp, old = self.supply_progress.get(aid,(self.t,a.position))
            if hypot(a.position[0]-old[0],a.position[1]-old[1]) > 0.18:
                self.supply_progress[aid] = self.t,a.position
            elif self.t-stamp > 3.0:
                claims.pop(aid)
                self.supply_avoid[(aid,bid)] = self.t+3.0
        occupied = set(claims.values())
        choices = []
        for aid,a in empty.items():
            if aid in claims:
                continue
            for bid,b in memory.items():
                if bid in occupied or self.supply_avoid.get((aid,bid),0)>self.t:
                    continue
                x,y = b['position'][:2]
                lateral = abs(y-a.spawn[1])
                distance = hypot(x-a.position[0],y-a.position[1])
                lane_weight = 0.8 if 'cover' in a.role else 0.45
                choices.append((distance+lane_weight*lateral,aid,bid))
        for _,aid,bid in sorted(choices):
            if aid not in claims and bid not in occupied:
                claims[aid],self.supply_progress[aid] = bid,(self.t,empty[aid].position)
                occupied.add(bid)
                self.human_stats['supply_assignments'] += 1
                if abs(memory[bid]['position'][1]-empty[aid].spawn[1])>1.75:
                    self.human_stats['cross_lane_recovery_assignments'] += 1
        self.supply_snapshot[team] = [dict(b) for _,b in sorted(memory.items())]

    def get_observation(self, agent_id=None):
        obs = super().get_observation(agent_id)
        if agent_id is not None:
            a = self.agents[agent_id]
            obs['self'].update(aim_style=a.human_profile['aim_style'],
                               follow_through=a.human_profile['follow_through'],steady_aim_s=a.steady_aim_s)
            obs['team_ground_arrows'] = [dict(b) for b in self.supply_snapshot[a.team]]
            obs['team_roster'] = [dict(id=f.id,position=f.position,velocity=f.velocity,ammo=len(f.inventory))
                                  for f in self.agents.values() if f.team==a.team and f.id!=a.id and f.status!=Status.ELIMINATED]
            bid = self.supply_claims[a.team].get(a.id)
            obs['supply_assignment'] = dict(self.supply_memory[a.team][bid]) if bid in self.supply_memory[a.team] else None
        return obs

    def _record_frame(self):
        super()._record_frame()
        for p in self.trace[-1]['players']:
            a = self.agents[p['id']]
            bid = self.supply_claims[a.team].get(a.id)
            target = self.supply_memory[a.team].get(bid)
            p.update(aim_style=a.human_profile['aim_style'],follow_through=a.human_profile['follow_through'],
                     aim_required=a.human_aim_s,steady_aim_s=a.steady_aim_s,
                     supply_goal=target['position'][:2] if target and not a.inventory else None)
        for b in self.trace[-1]['arrows']:
            b['flight_left'] = self.arrows[b['id']].flight_left

    def assert_invariants(self):
        super().assert_invariants()
        for team,claims in self.supply_claims.items():
            assert len(claims.values()) == len(set(claims.values()))
            lo,hi=self.config['teams'][team]['move_x_bounds_m']
            assert all(lo-1e-8<=a.position[0]<=hi+1e-8 for a in self.agents.values() if a.team==team)
