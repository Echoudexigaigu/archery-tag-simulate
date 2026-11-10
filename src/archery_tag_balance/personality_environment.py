from .tactical_environment import SuzhouEnvironment as V4Environment
from .entities import Status
from .player_model import profile
from .behavior_records import BehaviorRecords


class SuzhouEnvironment(V4Environment):
    def _setup_opening(self):
        super()._setup_opening()
        specs=self.config.get('player_profiles',{})
        for a in self.agents.values():
            a.player_model=profile(specs.get(a.id,dict(player_id='UNSET_'+a.id,is_demo=True,source='neutral_missing')));skills=a.player_model['skills'];style=a.player_model['style']
            a.eta=sum(skills.values())/len(skills)
            a.human_profile.update(accuracy=1.,range_bias=0.,yaw_bias=0.,pitch_bias=0.,draw_power=1.)
            a.human_profile['reaction_s']=.29-.14*skills['reaction']
            a.human_profile['carry_skill']=skills['carry_control']
            a.human_profile['carry_preference']=a.player_model['preferred_carry']
            a.human_profile['personal_aim_s']=.3+2.2*style['aim_patience']
            a.human_profile['pickup_tempo']=1.15-.3*skills['pickup']
            a.human_profile['tempo']=1.15-.3*skills['nocking']
            fps=a.player_model['equipment'].get('muzzle_speed_fps')
            if fps is not None:
                from math import isfinite
                if not isinstance(fps,(int,float)) or not isfinite(fps) or not 0<fps<=300:raise ValueError('Invalid muzzle speed')
                a.human_profile['muzzle_speed_fps']=fps
            self._next_pickup_duration(a)
        self.behavior=BehaviorRecords(self)

    def _movement_speed(self,a):
        base=super()._movement_speed(a)
        return base*(.90+.15*a.player_model['skills']['agility']) if hasattr(a,'player_model') else base

    def _timers(self,dt):
        before={aid:a.stamina for aid,a in self.agents.items()}
        super()._timers(dt)
        for aid,a in self.agents.items():
            if hasattr(a,'player_model') and a.stamina>before[aid]:
                a.stamina=min(1,before[aid]+(a.stamina-before[aid])*(.8+.4*a.player_model['skills']['endurance']))

    def _launch_velocity(self,a,origin,target):
        original=a.eta
        a.eta=a.player_model['skills']['target_accuracy' if str(a.aim_key).startswith('rack:') else 'body_accuracy']
        try:return super()._launch_velocity(a,origin,target)
        finally:a.eta=original

    def _release(self,a,action):
        before=self.counts['shot'];bid=a.nocked_arrow
        super()._release(a,action)
        if self.counts['shot']>before:self.behavior.shot(a,bid,action,self.last_launch[a.id])

    def _on_body_contact(self,a,b,shooter,active):self.behavior.body(a,b,shooter,active)

    def _finish_flight(self,b,point,kind,velocity,remaining_tick_s):
        self.behavior.finish(b,kind);return super()._finish_flight(b,point,kind,velocity,remaining_tick_s)

    def _contact_skirmish_rack(self,b,target,point,rewards):
        key,spot=target;standing=spot>=0 and self.skirmish_racks[key].standing[spot]
        super()._contact_skirmish_rack(b,target,point,rewards)
        self.behavior.rack(b,key,spot,bool(standing and not self.skirmish_racks[key].standing[spot]))

    def step(self,actions,observe=True):
        old={aid:dict(active=a.status==Status.ACTIVE,position=a.position) for aid,a in self.agents.items()}
        before=self.t;result=super().step(actions,observe);self.behavior.step(old,self.t-before);return result

    def get_observation(self,agent_id=None):
        obs=super().get_observation(agent_id)
        if agent_id is not None and hasattr(self.agents[agent_id],'player_model'):
            obs['self']['player_model']=self.agents[agent_id].player_model;obs['round_s']=self.config['time']['round_s']
            for enemy in obs['enemies']:enemy['player_id']=self.agents[enemy['id']].player_model['player_id']
        return obs
