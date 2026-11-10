"""Situational roles: advantage containment and survival/revival under pressure."""
from dataclasses import replace
from math import atan2,hypot,pi
from .deliberate_policy import SuzhouPolicy as V6Policy
from .tactical_entities import TacticalAction,positions
from .entities import Action


def aimed_at(enemy,position):
    if not enemy.get('aiming'):return False
    direction=atan2(position[1]-enemy['position'][1],position[0]-enemy['position'][0])
    difference=abs((direction-enemy.get('bow_bearing',direction)+pi)%(2*pi)-pi)
    return difference<.18


class SuzhouPolicy(V6Policy):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.lone_choice='hide_cover';self.lone_until=0.;self.lone_last_release=-100.;self.lone_escape=0.;self.lone_retry=0.
        self.last_watch_shot=-100.;self.team_plan={}

    def _act(self,obs):
        self.team_plan=obs.get('team_plan',{})
        # Team reports can cue a glance; only the personal visible observation
        # can later justify shooting. Reports do not reveal hidden ammunition.
        if self.attention and self.team_plan.get('mode')=='lockdown' and self.team_plan.get('reported_enemy'):
            _,point=self.team_plan['reported_enemy'];a=obs['self']['position']
            self.attention.focus=atan2(point[1]-a[1],point[0]-a[0])
        return super()._act(obs)

    def _role_action(self,obs):
        a=obs['self'];plan=obs.get('team_plan',{});self.team_plan=plan
        if a['status']=='eliminated' or not a['opening_stashed']:return super()._role_action(obs)
        if plan.get('mode')=='lockdown':return self._lockdown(obs)
        if plan.get('mode')=='outnumbered' and plan.get('own_alive')==1:return self._lone(obs)
        return super()._role_action(obs)

    def _ready(self,obs,goal):
        a=obs['self']
        if a['bow_state']=='empty':
            self._set_intent('nock',goal)
            return TacticalAction(interaction='nock',move=self.move_to(a['position'],goal,a['team'],obs['time']))
        if a['bow_state']=='nocking':return self._go(obs,goal,'nock')
        return None

    def _lockdown(self,obs):
        a=obs['self'];plan=obs['team_plan'];now=obs['time'];self._remember(obs)
        logistics=self._logistics(obs)
        if logistics is not None:return logistics
        goal=tuple(plan['goal'])
        if not a['ammo']:return self._go(obs,goal,'recover_front')
        ready=self._ready(obs,goal)
        if ready is not None:return ready
        distance=hypot(a['position'][0]-goal[0],a['position'][1]-goal[1])
        if distance>.25:
            # Travel towards the front while watching the last known threat;
            # defensive sidesteps in _act can always interrupt this move.
            action=self._go(obs,goal,'press_front')
            if plan.get('reported_enemy'):
                _,point=plan['reported_enemy'];action=replace(action,aim=(*point,1.),aim_key='watch:report')
            return action
        enemies=[e for e in obs['enemies'] if e['status']=='active']
        if plan['task']=='watch':
            enemy=min(enemies,key=lambda e:hypot(e['position'][0]-a['position'][0],e['position'][1]-a['position'][1])) if enemies else None
            point=(*enemy['position'],enemy['height']*.57) if enemy else (*plan['reported_enemy'][1],1.) if plan.get('reported_enemy') else None
            self._set_intent('pin_hold')
            if point is None:return Action()
            key=enemy['id'] if enemy else 'watch:report'
            # One watch archer can punish a runner; the other still holds.
            opportunity=enemy and (hypot(*enemy['velocity'])>1.5 or enemy['position'][1]<3.2)
            conserve=plan.get('reserve_agent')==a['id'] or plan.get('armed_count',0)<2
            fire=bool(opportunity and not conserve and now-a['last_shot_at']>7 and self._clear_arc(obs,point,key))
            return Action(aim=point,aim_key=key,interaction='shoot' if fire else 'none')
        if now-a['last_shot_at']<4.8:
            self._set_intent('conserve');return Action()
        target=self._targets(obs)
        if target is None:self._set_intent('conserve');return Action()
        aim=self._aim(obs,target)
        if not self._clear_arc(obs,aim,target[0]):return Action()
        self._set_intent('finish_target' if str(target[0]).startswith('rack:') else 'shoot')
        return Action(aim=aim,aim_key=target[0],interaction='shoot')

    def _lone_hide(self,obs,baseline=False):
        a=obs['self'];d=1 if a['team']=='attack' else -1
        covers=[o for o in self.nav.obstacles if o.id.startswith(a['team']+'_')]
        bunker=min(covers,key=lambda o:hypot(o.center[0]-a['position'][0],o.center[1]-a['position'][1]))
        protected=(bunker.center[0]-d*(bunker.size[0]/2+.45),bunker.center[1])
        goal=(.85 if d==1 else 31.15,max(.6,min(19.4,a['position'][1]))) if baseline else protected
        return self._go(obs,goal,'survive_back' if baseline else 'survive_cover',crouch=not baseline and bunker.size[2]<1.)

    def _lone(self,obs):
        a=obs['self'];now=obs['time'];self._remember(obs)
        if a['last_shot_at']>self.lone_last_release:
            self.lone_last_release=a['last_shot_at'];self.lone_escape=now+1.2;self.lone_retry=now+4.
        if now<self.lone_escape:return self._lone_hide(obs)
        logistics=self._logistics(obs)
        if logistics is not None:return logistics
        if not a['ammo']:return self._lone_hide(obs)
        pins=sum(aimed_at(e,a['position']) for e in obs['enemies'])
        if self.attention:self.attention.last_view['pressure']=min(1,self.attention.last_view.get('pressure',0)+.08*max(0,obs['team_plan'].get('enemy_alive',0)-1))
        if now>=self.lone_until:
            enemy_rack=next(r for r in obs['racks'] if r['team'] not in (a['team'],'revive'))
            revive=next(r for r in obs['racks'] if r['team']=='revive')
            if sum(enemy_rack['standing'])<=2:self.lone_choice='finish'
            elif obs['revive_queue'] and any(revive['standing']) and now>=self.lone_retry and (pins<3 or self.model['style']['risk_tolerance']>.7):self.lone_choice='revive'
            elif any(hypot(e['position'][0]-a['position'][0],e['position'][1]-a['position'][1])<13 and not aimed_at(e,a['position']) for e in obs['enemies']):self.lone_choice='body'
            else:self.lone_choice='hide_cover' if pins<4 else 'hide_back'
            self.lone_until=now+2.2
        if pins>=3 and self.lone_choice in ('revive','body') and not a['on_revive_pad']:
            self.lone_choice='hide_cover';self.lone_until=now+2.;self.lone_retry=now+2.
        if self.lone_choice.startswith('hide'):return self._lone_hide(obs,self.lone_choice=='hide_back')
        if self.lone_choice=='revive':
            pad=tuple(self.config['suzhou']['revive_pads'][a['team']]);ready=self._ready(obs,pad)
            if ready is not None:return ready
            rack=next(r for r in obs['racks'] if r['team']=='revive')
            k=next((k for k,s in enumerate(rack['standing']) if s),None)
            if k is None:return self._lone_hide(obs)
            self._set_intent('revive_snap' if pins else 'revive',pad)
            return TacticalAction(move=self.move_to(a['position'],pad,a['team'],now) if not a['on_revive_pad'] else (0,0),aim=rack['spots'][k],aim_key=f'rack:revive:{k}',interaction='shoot',quick_shot=pins>0)
        goal=(a['position'][0],a['position'][1]);ready=self._ready(obs,goal)
        if ready is not None:return ready
        if now<a.get('shot_gate_until',0):return self._lone_hide(obs)
        target=self._targets(obs)
        if target is None:return self._lone_hide(obs)
        aim=self._aim(obs,target);self._set_intent('finish_target' if self.lone_choice=='finish' else 'shoot')
        return Action(aim=aim,aim_key=target[0],interaction='shoot') if self._clear_arc(obs,aim,target[0]) else self._lone_hide(obs)

    def _targets(self,obs):
        plan=obs.get('team_plan',{});view=obs
        if plan.get('mode')=='lockdown' and plan.get('task')=='finish':view=dict(obs,enemies=[])
        if plan.get('own_alive')==1 and self.lone_choice=='finish':view=dict(obs,enemies=[])
        if plan.get('own_alive')==1 and self.lone_choice=='body':view=dict(obs,racks=[r for r in obs['racks'] if r['team'] in (obs['self']['team'],'revive')])
        target=super()._targets(view)
        if plan.get('mode')=='balanced' and obs['self']['role'] in ('high_cover','high_flank'):
            # Crossfire on exposed revival runners is the high side's normal
            # job too, rather than leaving all pressure to the revival lane.
            runners=[e for e in obs['enemies'] if e['position'][1]<4. and e.get('aiming')]
            for e in sorted(runners,key=lambda e:e['position'][1]):
                point=(*e['position'],e['height']*.57)
                if self._clear_arc(obs,point,e['id']):
                    self.target_key=e['id'];return (e['id'],point,e,hypot(point[0]-obs['self']['position'][0],point[1]-obs['self']['position'][1]))
        return target

    def _aim(self,obs,target):
        key,point,enemy,distance=target
        if enemy is None or distance>13:return super()._aim(obs,target)
        now=obs['time']
        if self.aim_cache is None or now>=self.next_aim_update:
            history=self.histories.get(key,[])
            old=[(t,p) for t,p in history if t<=now-self.latency]
            stamp,snapshot=old[-1] if old else (history[0] if history else (now,enemy))
            from math import log
            speed=obs['self']['muzzle_speed_fps']*.3048;drag=self.config['physics']['linear_drag_s_inv']
            flight=-log(max(.1,1-drag*distance/speed))/drag if drag else distance/speed
            # Professionals can track ordinary motion over twelve metres.
            # Compensate the actual age of the observed sample; unpredictable
            # post-release sidesteps still defeat this extrapolation.
            lead=flight*.98+now-stamp
            self.aim_cache=(snapshot['position'][0]+snapshot['velocity'][0]*lead,snapshot['position'][1]+snapshot['velocity'][1]*lead,point[2])
            self.next_aim_update=now+self.rng.uniform(.10,.18)
        return self.aim_cache
