"""Explicit, editable priors. These parameters are not learned player identities."""
from copy import deepcopy
from math import isfinite,atan2,cos,sin,pi,hypot

SKILLS=dict(body_accuracy=.7,target_accuracy=.7,reaction=.7,agility=.7,pickup=.8,nocking=.8,carry_control=.75,endurance=.7)
STYLE=dict(risk_tolerance=.5,aim_patience=.5,cover_preference=.5,target_preference=.5,attention_breadth=.5,scan_frequency=.5)


def profile(spec=None):
    spec=deepcopy(spec or {})
    result=dict(player_id=spec.get('player_id','DEMO'),alias=spec.get('alias',''),is_demo=spec.get('is_demo',True),source=spec.get('source','synthetic'),skills=dict(SKILLS),style=dict(STYLE),opponent_beliefs={},missing_fields=list(spec.get('missing_fields',[])),equipment=deepcopy(spec.get('equipment',{})))
    for section,defaults in [('skills',SKILLS),('style',STYLE)]:
        for name,value in spec.get(section,{}).items():
            if name not in defaults:raise ValueError(f'Unknown {section} field: {name}')
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value) or not 0<=value<=1:raise ValueError(f'{section}.{name} must be finite and between 0 and 1')
            result[section][name]=float(value)
    for key,value in spec.get('opponent_beliefs',{}).items():
        if not isinstance(value,(float,int)) or not isfinite(value) or not 0<=value<=1:raise ValueError('Opponent concern must be between 0 and 1')
        result['opponent_beliefs'][str(key)]=float(value)
    carry=spec.get('preferred_carry',1)
    if isinstance(carry,bool) or not isinstance(carry,int) or not 1<=carry<=4:raise ValueError('preferred_carry must be an integer from 1 to 4')
    result['preferred_carry']=carry
    return result


def angle_difference(a,b):return abs((a-b+pi)%(2*pi)-pi)


class Attention:
    def __init__(self,p,team,index):
        self.p=p;self.forward=0. if team=='attack' else pi
        self.focus=self.forward;self.noticed=set();self.next_scan=1.5+index*.13
        self.scan_until=0.;self.scan_side=1;self.last_view={}
        self.return_focus=self.forward

    def perceive(self,obs):
        now=obs['time'];a=obs['self'];style=self.p['style'];origin=a['position']
        if self.scan_until and now>=self.scan_until:
            self.focus=self.return_focus;self.scan_until=0.
        scanning=now<self.scan_until
        if not scanning and now>=self.next_scan and a['aim_elapsed']<.15:
            self.return_focus=self.focus
            self.scan_side*=-1;self.focus=self.forward+self.scan_side*.95
            self.scan_until=now+.22;self.next_scan=now+1.2+2.4*(1-style['scan_frequency']);scanning=True
        half=.7+.7*style['attention_breadth']
        in_cone=lambda point:angle_difference(atan2(point[1]-origin[1],point[0]-origin[0]),self.focus)<=half
        visible_keys={(b['id'],b.get('released_at',0)) for b in obs['flying_arrows'] if b.get('team')!=a['team']}
        self.noticed.intersection_update(visible_keys)
        for b in obs['flying_arrows']:
            if b.get('team')!=a['team'] and in_cone(b['position']):self.noticed.add((b['id'],b.get('released_at',0)))
        arrows=[b for b in obs['flying_arrows'] if b.get('team')==a['team'] or (b['id'],b.get('released_at',0)) in self.noticed]
        enemies=[e for e in obs['enemies'] if in_cone(e['position'])]
        concern=lambda enemy:self.p['opponent_beliefs'].get(enemy.get('player_id',enemy['id']),.5)
        def directed_pressure(enemy):
            if not enemy.get('aiming'):return 0.
            bearing=atan2(origin[1]-enemy['position'][1],origin[0]-enemy['position'][0])
            watching='bow_bearing' not in enemy or angle_difference(bearing,enemy['bow_bearing'])<.18
            return (.13+.14*concern(enemy)) if watching else .025
        pressure=min(1.,sum(directed_pressure(e) for e in enemies)+.18*len(self.noticed))
        self.last_view=dict(focus=self.focus,half_angle=half,pressure=pressure,visible_arrows=len(visible_keys),noticed_arrows=len(self.noticed),scanning=scanning,risk_margin=None,reason='observing')
        return dict(obs,enemies=enemies,flying_arrows=arrows)

    def risk(self,obs):
        p=self.p;style=p['style'];a=obs['self']
        visible_pressure=self.last_view.get('pressure',0)
        estimated_risk=min(1.,.12+.7*visible_pressure+.18*(1-a['stamina']))
        urgency=max(0,min(1,(obs['time']-(obs.get('round_s',240)-30))/30))
        gain=.44+.2*bool(obs.get('revive_queue'))+.28*urgency+.12*style['target_preference']
        risk_weight=2.1-1.5*style['risk_tolerance']+.35*style['cover_preference']
        margin=gain-risk_weight*estimated_risk-.04
        self.last_view['risk_margin']=margin
        return margin

    def finish(self,obs,action,reason):
        if action.aim is not None and not self.last_view.get('scanning'):
            a=obs['self']['position'];self.focus=atan2(action.aim[1]-a[1],action.aim[0]-a[0])
        self.last_view['reason']=reason
