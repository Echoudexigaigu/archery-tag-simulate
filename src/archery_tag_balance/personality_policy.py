"""V5 priors, finite attention and a limited voluntary-peek risk model."""
from dataclasses import replace
from .tactical_policy import SuzhouPolicy as V4Policy
from .responsive_policy import SuzhouPolicy as TargetPolicy
from .entities import Action
from .player_model import Attention,profile


class SuzhouPolicy(V4Policy):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.attention=None;self.model=None;self.mind={};self.risk_until=0.;self.risk_margin=None

    def _act(self,obs):
        if self.model is None:
            self.model=profile(obs['self'].get('player_model'))
            self.attention=Attention(self.model,obs['self']['team'],self.index)
        if obs['self']['status']=='eliminated':
            self.mind=dict(self.mind,reason='out');return super()._act(obs)
        view=self.attention.perceive(obs)
        action=super()._act(view)
        reason=self.intent.get('kind','hold')
        if action.evasion_kind:reason='reactive_evade'
        elif self.attention.last_view['scanning'] and action.aim is not None:
            action=replace(action,aim=None,aim_key=None,interaction='none');reason='glance_scan'
        self.attention.finish(view,action,reason)
        self.mind=dict(self.attention.last_view)
        self.intent['mind']=self.mind
        return action

    def _role_action(self,obs):
        action=super()._role_action(obs);a=obs['self'];kind=self.intent.get('kind')
        if self.model and obs['time']<self.risk_until and self.phase=='hide' and kind=='guard' and a['ammo'] and not obs.get('job'):
            self.intent['kind']='risk_hold';self.attention.last_view['risk_margin']=self.risk_margin
        # Do not interfere with V4's essential arrow recovery or a designated
        # revival run. Risk only gates optional movement out of one's cover.
        if self.model and 'cover' in a['role'] and self.phase=='peek' and a['ammo'] and not obs.get('job') and kind=='guard' and action.move!=(0,0):
            if self.attention.risk(obs)<0:
                self.phase='hide';self.next_peek=obs['time']+.45+1.2*self.model['style']['cover_preference']
                self.risk_until=self.next_peek;self.risk_margin=self.attention.last_view['risk_margin']
                action=self._go(obs,self._positions(obs)[1],'risk_hold',crouch=self._positions(obs)[0].size[2]<1)
        return action

    def _targets(self,obs):
        role=obs['self']['role'];view=dict(obs)
        if role in ('high_cover','high_flank'):
            busy=[p for p in obs['enemies'] if p['position'][1]<5 and p.get('aiming')]
            if busy and self.rng.random()<.65:view['enemies']=busy
            base=.4 if role=='high_cover' else .1
        elif role=='low_cover':view['enemies']=[p for p in obs['enemies'] if p['position'][1]<8];base=.65
        elif role=='revive_lane':view['enemies']=[p for p in obs['enemies'] if p['position'][1]<7];base=.25
        else:base=.35
        self.target_interest=.5*base+.5*self.model['style']['target_preference']
        return TargetPolicy._targets(self,view)
