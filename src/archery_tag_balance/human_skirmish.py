"""Six-role play, sequential arrow preparation, noisy release and rack points.

All distributions are exploratory configuration values, not fitted human data.
"""
from collections import Counter
from math import atan2, cos, hypot, log, sin, sqrt

from .entities import Action, Status
from .geometry import advance_arrow, ballistic_velocity
from .skirmish import SkirmishEnvironment

ROLES = ('left_flank', 'left_cover', 'center_1', 'center_2', 'right_cover', 'right_flank')


class HumanSkirmishEnvironment(SkirmishEnvironment):
    def _validate(self):
        super()._validate()
        if any(t['players'] != 6 for t in self.config['teams'].values()):
            raise ValueError('Six-role policy needs exactly six players per team')
        s = self.config['human_shooting']
        if any(s[k] <= 0 for k in ('novice_nock_s', 'expert_nock_s', 'novice_aim_s', 'expert_aim_s')):
            raise ValueError('Human preparation durations must be positive')
        if not 0 <= self.config['target_scoring']['knockdown_probability'] <= 1:
            raise ValueError('Target knockdown probability must be in [0,1]')

    def _sample_duration(self, mean, cv, lower=0.2, upper=12.0):
        return max(lower, min(upper, mean * self.rng.lognormvariate(-cv * cv / 2, cv)))

    def _setup_opening(self):
        self.scores = {team: {'body': 0, 'target': 0} for team in self.config['teams']}
        self.human_stats = Counter()
        self.victory_reason = None
        self.last_launch = {}
        W = self.config['field']['width_m']
        for a in self.agents.values():
            i = int(a.id.rsplit('_', 1)[1])
            a.role = ROLES[i]
            # Start in own-left order, avoiding everyone crossing after opening.
            y = W * (i + 0.5) / 6
            if a.team == 'attack':
                y = W - y
            if self.mirror_y:
                y = W - y
            a.spawn = a.position = (a.spawn[0], y)
            a.human_profile = dict(tempo=self.rng.uniform(0.8, 1.25),
                                   accuracy=self.rng.uniform(0.85, 1.2),
                                   range_bias=self.rng.gauss(0, 0.035 + 0.045 * (1 - a.eta)),
                                   yaw_bias=self.rng.gauss(0, 0.012 + 0.012 * (1 - a.eta)),
                                   pitch_bias=self.rng.gauss(0, 0.009),
                                   pickup_tempo=self.rng.uniform(0.8, 1.3))
            self._next_pickup_duration(a)
        super()._setup_opening()

    def _next_pickup_duration(self, a):
        a.pickup_required_s = self._sample_duration(0.9 * a.human_profile['pickup_tempo'], 0.27, 0.45, 1.8)

    def _prepare_arrow(self, a):
        c, s = self.config, self.config['human_shooting']
        tempo = a.human_profile['tempo']
        nock = self._sample_duration(self._skill(a.eta, s['novice_nock_s'], s['expert_nock_s']) * tempo, s['timing_cv'], 1.7, 8.0)
        fumble = self.rng.random() < s['fumble_probability'] * (1 - 0.65 * a.eta)
        if fumble:
            nock += self.rng.uniform(0.5, 1.8)
        a.reload_left = max(a.reload_left, nock)
        a.human_aim_s = self._sample_aim_duration(a)
        a.aim_elapsed, a.aim_key = 0.0, None
        self._emit('nock', agent=a.id, duration=nock, aim_required=a.human_aim_s, fumble=fumble)
        self.human_stats['fumbles'] += int(fumble)

    def _sample_aim_duration(self, a):
        s = self.config['human_shooting']
        return self._sample_duration(self._skill(a.eta, s['novice_aim_s'], s['expert_aim_s']) * a.human_profile['tempo'],
                                     s['timing_cv'], 0.65, 4.0)

    def _accuracy_multiplier(self, a):
        return 1.0

    def _aim_duration(self, a):
        return a.human_aim_s

    def _pickup_duration(self, a):
        if not a.shoot_unlocked or not self.combat_started:
            return self.config['physics']['pickup_s']
        return a.pickup_required_s

    def _pickup_progress_allowed(self, a):
        if not a.shoot_unlocked or not self.combat_started:
            return True
        # Walking towards an arrow must not prepay the pickup time.
        return hypot(*a.velocity) <= 0.3 and any(
            b.state == 'ground' and self._pickup_allowed(a, b)
            and hypot(b.position[0] - a.position[0], b.position[1] - a.position[1]) <= self.config['physics']['pickup_radius_m']
            for b in self.arrows.values())

    def _picked_up(self, a, b):
        opening = b.opening_arrow
        super()._picked_up(a, b)
        if not opening and a.shoot_unlocked and self.combat_started:
            self._prepare_arrow(a)
            self._next_pickup_duration(a)

    def _drop(self, a):
        before = len(a.inventory)
        super()._drop(a)
        if before > 1 and len(a.inventory) == 1:
            self._prepare_arrow(a)

    def _timers(self, dt):
        super()._timers(dt)
        for a in self.agents.values():
            if hypot(*a.velocity) > 0.4:
                a.last_move_at = self.t

    def _launch_velocity(self, a, origin, target):
        p, s, profile = self.config['physics'], self.config['human_shooting'], a.human_profile
        # Individual distance bias persists; a fresh distance estimate adds noise.
        estimate = max(0.72, min(1.25, 1 + profile['range_bias'] + self.rng.gauss(0, 0.018 + 0.026 * (1 - a.eta))))
        perceived = (origin[0] + (target[0] - origin[0]) * estimate,
                     origin[1] + (target[1] - origin[1]) * estimate, target[2])
        v = ballistic_velocity(origin, perceived, p['arrow_speed_m_s'], p['gravity_m_s2'],
                               p.get('linear_drag_s_inv', 0), p['arrow_max_flight_s'])
        if v is None:
            return None
        sigma = self._skill(a.eta, s['novice_angle_sd_rad'], s['expert_angle_sd_rad']) * profile['accuracy']
        sigma *= self._accuracy_multiplier(a)
        unsettled = max(0, 1 - (self.t - a.last_move_at) / s['settle_s'])
        fatigue = 1 - a.stamina
        pressure = 1 if self.t < a.movement_dodge_ready_at else 0
        sigma *= 1 + 0.35 * unsettled + 0.35 * fatigue + 0.2 * pressure
        # A minority of releases are noticeably poor, rather than every shot
        # being an identically shaped Gaussian cloud.
        poor_release = self.rng.random() < s['poor_release_probability'] * (1 - 0.45 * a.eta)
        if poor_release:
            sigma *= 1.8
        yaw = atan2(v[1], v[0]) + profile['yaw_bias'] + self.rng.gauss(0, sigma)
        pitch = atan2(v[2], hypot(v[0], v[1])) + profile['pitch_bias'] + self.rng.gauss(0, sigma * 0.8)
        speed = p['arrow_speed_m_s'] * max(0.84, min(1.06, self.rng.gauss(0.985, 0.025 + 0.028 * (1 - a.eta))))
        self.last_launch[a.id] = dict(sigma=sigma, speed=speed, range_estimate=estimate,
                                      poor_release=poor_release, aim_required=a.human_aim_s)
        return (speed * cos(pitch) * cos(yaw), speed * cos(pitch) * sin(yaw), speed * sin(pitch))

    def _release(self, a, action):
        before = self.counts['shot']
        super()._release(a, action)
        if self.counts['shot'] != before:
            a.reload_left = self._sample_duration(0.9 * a.human_profile['tempo'], 0.3, 0.45, 1.6)
            a.last_shot_at = self.t
            kind = 'target' if str(action.aim_key).startswith('rack:') else 'body'
            self.human_stats[kind + '_shots'] += 1
            self.human_stats['poor_releases'] += int(self.last_launch[a.id]['poor_release'])
            self._emit('shot_detail', agent=a.id, role=a.role, target_kind=kind,
                       target_key=action.aim_key, **self.last_launch[a.id])

    def _eliminate(self, a, shooter, rewards):
        before = a.lives
        super()._eliminate(a, shooter, rewards)
        if a.lives < before:
            self.scores[shooter.team]['body'] += 1

    def _contact_skirmish_rack(self, arrow, target, point, rewards):
        team, spot = target
        rack = self.skirmish_racks[team]
        shooter = self.agents[arrow.shooter]
        if spot >= 0 and rack.standing[spot] and shooter.team != team:
            s = self.config['target_scoring']
            horizontal = hypot(*arrow.velocity[:2])
            distance = hypot(point[0] - arrow.position[0], point[1] - arrow.position[1])
            drag = self.config['physics'].get('linear_drag_s_inv', 0)
            travel = -log(max(1e-8, 1 - drag * distance / max(1e-9, horizontal))) / drag if drag else distance / max(1e-9, horizontal)
            _, velocity = advance_arrow(arrow.position, arrow.velocity, travel, self.config['physics']['gravity_m_s2'], drag)
            speed = sqrt(sum(v * v for v in velocity))
            incidence = abs(velocity[0]) / max(1e-9, speed)
            probability = s['knockdown_probability'] * min(1.0, speed / s['reference_speed_m_s']) * (0.6 + 0.4 * incidence)
            roll = self.rng.random()
            success = roll < probability
            self._emit('rack_roll', team=team, spot=spot, shooter=shooter.id,
                       probability=probability, roll=roll, success=success)
            if success:
                rack.standing[spot] = False
                self.scores[shooter.team]['target'] += 1
                rewards[shooter.id] += self.config['rewards']['target']
                self._emit('rack_target', team=team, spot=spot, shooter=shooter.id)
        self._ground(arrow, point)

    def _resolve_winner(self):
        remaining = {team: any(a.lives > 0 for a in self.agents.values() if a.team == team) for team in self.scores}
        if not all(remaining.values()):
            self.victory_reason = 'mutual_elimination' if not any(remaining.values()) else 'elimination'
            return 'draw' if not any(remaining.values()) else next(t for t in remaining if remaining[t])
        if self.t + 1e-8 >= self.config['time']['round_s']:
            self.victory_reason = 'score'
            totals = {team: sum(score.values()) for team, score in self.scores.items()}
            return 'draw' if totals['attack'] == totals['defense'] else max(totals, key=totals.get)
        return None

    def get_observation(self, agent_id=None):
        obs = super().get_observation(agent_id)
        if agent_id is not None:
            a = self.agents[agent_id]
            obs['self'].update(role=a.role, last_shot_at=a.last_shot_at, aim_required=a.human_aim_s)
            obs['racks'] = [{'team': team, 'position': r.position, 'spots': [r.spot(k) for k in range(5)],
                             'standing': list(r.standing)} for team, r in self.skirmish_racks.items()]
            obs['scores'] = {t: dict(v) for t, v in self.scores.items()}
        return obs

    def _record_frame(self):
        super()._record_frame()
        self.trace[-1]['scores'] = {t: dict(v) for t, v in self.scores.items()}
        for p in self.trace[-1]['players']:
            a = self.agents[p['id']]
            stage = ('out' if a.status == Status.ELIMINATED else 'opening' if not a.shoot_unlocked else
                     'pickup' if a.pickup_elapsed > 0 else ('waiting_arrow' if hypot(*a.velocity) < 0.15 else 'search') if not a.inventory else
                     'nocking' if a.reload_left > 0 else 'aiming' if a.aim_elapsed > 0 else 'ready')
            p.update(role=a.role, stage=stage, reload_left=a.reload_left, aim_elapsed=a.aim_elapsed)

    def summary(self):
        row = super().summary()
        row.update(scores={t: {**v, 'total': sum(v.values())} for t, v in self.scores.items()},
                   human_stats=dict(self.human_stats), victory_reason=self.victory_reason,
                   rack_rolls=self.counts['rack_roll'], obstacle_blocks=self.counts['obstacle_block'])
        return row
