"""V6: deliberate opportunities, tight releases, physical (not dice) evasion.

All constants are exploratory tuning, not measured professional performance.
The equipment's real muzzle speed and existing 3D contact rules are retained.
"""
from math import atan2,cos,sin,hypot,radians
from .personality_environment import SuzhouEnvironment as V5Environment
from .geometry import ballistic_velocity
from .varied_environment import landing_time


class SuzhouEnvironment(V5Environment):
    def _setup_opening(self):
        super()._setup_opening()
        for a in self.agents.values():
            patience=a.player_model['style']['aim_patience']
            a.human_profile['personal_aim_s']=1.25+2.1*patience
            a.human_profile['aim_style']='deliberate' if patience>.65 else 'snap' if patience<.25 else 'balanced'
            a.human_aim_s=self._sample_aim_duration(a)
            a.shot_gate_until=0.

    def _refresh_supply(self,team):
        from .local_supply import LocalSupplyCoordinator
        if not isinstance(getattr(self,'supply_coordinator',None),LocalSupplyCoordinator):
            self.supply_coordinator=LocalSupplyCoordinator(self)
        self.supply_coordinator.refresh(team)

    def _release(self,a,action):
        # Defence and professional pickup/nock remain fast. This is a separate
        # decision/reassessment interval, not a fictional slow loading bar.
        if self.t+1e-9<a.shot_gate_until:return
        before=self.counts['shot']
        super()._release(a,action)
        if self.counts['shot']>before:
            a.shot_gate_until=self.t+self.config['v6']['minimum_release_gap_s']

    def _launch_velocity(self,a,origin,target):
        p=self.config['physics'];h=a.human_profile
        skill=a.player_model['skills']['target_accuracy' if str(a.aim_key).startswith('rack:') else 'body_accuracy']
        # Slight draw variation changes speed; the release solution is based
        # on that draw, with a small residual execution error, not 2.5% pure
        # speed noise applied after solving a different trajectory.
        nominal=h['muzzle_speed_fps']*.3048
        draw=nominal*max(.965,min(1.035,self.rng.gauss(1,.014)))
        estimate=1+max(-.025,min(.025,self.rng.gauss(0,.004+.006*(1-skill))))
        perceived=(origin[0]+(target[0]-origin[0])*estimate,origin[1]+(target[1]-origin[1])*estimate,target[2])
        v=ballistic_velocity(origin,perceived,draw,p['gravity_m_s2'],p['linear_drag_s_inv'],p['arrow_max_flight_s'])
        if v is None:return None
        sigma=(.012-.0085*skill)*self._accuracy_multiplier(a)
        sigma*=1+.22*min(1,hypot(*a.velocity)/p['move_speed_m_s'])+.25*(1-a.stamina)
        poor=self.rng.random()<.018*(1-.5*skill)
        if poor:sigma*=1.4
        yaw_error=max(-2.6*sigma,min(2.6*sigma,self.rng.gauss(0,sigma)))
        pitch_error=max(-2.6*sigma,min(2.6*sigma,self.rng.gauss(0,.8*sigma)))
        yaw=atan2(v[1],v[0])+yaw_error
        pitch=max(radians(-35),min(radians(self.config['flight_variation']['max_elevation_degrees']),atan2(v[2],hypot(*v[:2]))+pitch_error))
        speed=draw*max(.986,min(1.014,self.rng.gauss(1,.004+.003*(1-skill))))
        result=(speed*cos(pitch)*cos(yaw),speed*cos(pitch)*sin(yaw),speed*sin(pitch))
        self.last_launch[a.id]=dict(sigma=sigma,speed=speed,speed_fps=speed/.3048,range_estimate=estimate,poor_release=poor,aim_required=a.human_aim_s,planned_flight_s=landing_time(origin,result,p['gravity_m_s2'],p['linear_drag_s_inv'],p['arrow_max_flight_s']),aim_style=h['aim_style'],steady_aim_s=a.steady_aim_s,aim_height_m=target[2],target_band='target' if str(a.aim_key).startswith('rack:') else 'low' if target[2]<.55 else 'torso',yaw_error_rad=yaw_error,pitch_error_rad=pitch_error)
        return result

    def get_observation(self,agent_id=None):
        obs=super().get_observation(agent_id)
        if agent_id is not None:obs['self']['shot_gate_until']=self.agents[agent_id].shot_gate_until
        return obs

    def _record_frame(self):
        super()._record_frame()
        for p in self.trace[-1]['players']:
            a=self.agents[p['id']]
            p['aim_key']=a.aim_key;p['aim_elapsed']=a.aim_elapsed
            p['dodge_velocity']=a.velocity

