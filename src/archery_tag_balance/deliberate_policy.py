"""Stable target opportunities and independent reassessment, V6."""
from dataclasses import replace
from math import hypot,log
from .entities import Action
from .personality_policy import SuzhouPolicy as V5Policy


class SuzhouPolicy(V5Policy):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.reassess_until=0.;self.observed_release=-100.;self.opportunity=None;self.opportunity_since=0.
        self.latency=self.rng.uniform(.10,.20);self.lead_fraction=self.rng.uniform(.82,.98)
        self.preferred_duck=self.rng.random()<.35

    def _role_action(self,obs):
        a=obs['self'];now=obs['time']
        if a['last_shot_at']>self.observed_release:
            self.observed_release=a['last_shot_at']
            patience=a.get('player_model',{}).get('style',{}).get('aim_patience',.5)
            self.reassess_until=a['last_shot_at']+2.4+2.5*patience+self.rng.uniform(.4,1.2)
            self.opportunity=None
        action=super()._role_action(obs)
        if action.evasion_kind or action.aim is None or action.interaction!='shoot':
            self.opportunity=None;return action
        quick=bool(getattr(action,'quick_shot',False))
        if now<max(a.get('shot_gate_until',0),self.reassess_until) and not quick:
            self.intent['kind']='assess';self.opportunity=None
            return replace(action,aim=None,aim_key=None,interaction='none',move=(0,0))
        # A blocked or disappearing target loses the opportunity. Merely seeing
        # a new point for a single decision tick cannot trigger another shot.
        if self.opportunity!=action.aim_key:self.opportunity=action.aim_key;self.opportunity_since=now
        dwell=.32+.45*self.model['style']['aim_patience']
        target=next((p for p in obs['enemies'] if p['id']==action.aim_key),None)
        if target and hypot(*target['velocity'])>2.8:dwell+=.35
        if not quick and now-self.opportunity_since<dwell:
            self.intent['kind']='track'
            return replace(action,interaction='none',move=(0,0))
        if not quick and self.threat(obs)>1.4:
            self.intent['kind']='assess';return replace(action,aim=None,aim_key=None,interaction='none')
        self.intent['target']=action.aim_key
        # Hold a stable shooting stance; sidesteps take precedence in _act.
        return replace(action,move=(0,0)) if not quick else action

    def _aim(self,obs,target):
        key,point,enemy,distance=target;now=obs['time']
        if self.aim_cache is None or now>=self.next_aim_update:
            if enemy is not None:
                history=self.histories.get(key,[])
                old=[p for t,p in history if t<=now-self.latency]
                snapshot=old[-1] if old else (history[0][1] if history else enemy)
                speed=obs['self']['muzzle_speed_fps']*.3048;drag=self.config['physics']['linear_drag_s_inv']
                flight=-log(max(.1,1-drag*distance/speed))/drag if drag else distance/speed
                # Observed motion only; changes after release remain dodgeable.
                lead=min(1.7,flight)*self.lead_fraction+self.latency*.5
                point=(snapshot['position'][0]+snapshot['velocity'][0]*lead,snapshot['position'][1]+snapshot['velocity'][1]*lead,point[2])
            self.aim_cache=point;self.next_aim_update=now+self.rng.uniform(.12,.23)
        return self.aim_cache

    def _targets(self,obs):
        a=obs['self'];now=obs['time'];candidates=[]
        preference=self.model['style']['target_preference']
        role=a['role']
        for enemy in obs['enemies']:
            if enemy['status']!='active':continue
            distance=hypot(enemy['position'][0]-a['position'][0],enemy['position'][1]-a['position'][1])
            if distance>self.config['policy']['engage_distance_m']:continue
            entry=self.body_bands.get(enemy['id'])
            if entry is None:
                entry=(self.rng.choices(['torso','low','upper'],[.65,.25,.1])[0],now+5)
                self.body_bands[enemy['id']]=entry
            heights={'torso':enemy['height']*.57,'low':min(.36,enemy['height']*.32),'upper':enemy['height']*.86}
            for band in dict.fromkeys([entry[0],'torso','upper','low']):
                point=(*enemy['position'],heights[band])
                if not self._clear_arc(obs,point,enemy['id']):continue
                # Exposed, slow or aiming opponents are useful opportunities;
                # threatened revival runners draw cross-lane support.
                score=1.30-.018*distance+.32*bool(enemy.get('aiming'))-.10*min(3,hypot(*enemy['velocity']))
                if enemy['position'][1]<3.2:score+=.32 if role in ('high_cover','high_flank','revive_lane') else .12
                if role=='low_cover':score-=.42
                candidates.append((score,(enemy['id'],point,enemy,distance)));break
        for rack in obs['racks']:
            if rack['team'] in (a['team'],'revive'):continue
            for k,standing in enumerate(rack['standing']):
                if not standing:continue
                point=rack['spots'][k];key=f"rack:{rack['team']}:{k}"
                distance=hypot(point[0]-a['position'][0],point[1]-a['position'][1])
                if distance>self.config['policy']['engage_distance_m'] or not self._clear_arc(obs,point,key):continue
                score=.35+.65*preference-.014*distance+(.42 if role=='low_cover' else 0)
                if role=='high_flank':score-=.25
                candidates.append((score,(key,point,None,distance)))
        if not candidates:self.target_key=None;self.aim_cache=None;return None
        chosen=max(candidates,key=lambda item:item[0]+(.24 if item[1][0]==self.target_key else 0))[1]
        if chosen[0]!=self.target_key:self.aim_cache=None;self.next_aim_update=0
        self.target_key=chosen[0]
        return chosen

