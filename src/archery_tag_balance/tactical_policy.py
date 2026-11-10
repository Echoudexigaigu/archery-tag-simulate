"""Role-specific decisions; transport, nocking and exposed revival are choices."""
from math import hypot,sin
from dataclasses import replace
from .responsive_policy import SuzhouPolicy as V2Policy
from .entities import Action
from .tactical_entities import TacticalAction,positions


class SuzhouPolicy(V2Policy):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.command=0;self.last_release=-100;self.follow_until=0
        self.escape_until=0;self.revive_retry=0;self.revive_key=None
        self.previous_role=None

    def __call__(self,obs):
        self.command+=1;self.role=obs['self']['role']
        if self.role!=self.previous_role:
            self.goal=None;self.route=[];self.target_key=None;self.aim_cache=None;self.next_peek=None;self.phase='hide';self.previous_role=self.role
        action=super().__call__(obs)
        if not isinstance(action,TacticalAction):
            action=TacticalAction(**action.__dict__)
        return replace(action,token=self.command)

    def _positions(self,obs):
        a=obs['self'];hold,peek=positions(self.config,a['team'],a['role'])
        own=[o for o in self.nav.obstacles if o.id.startswith(a['team']+'_')]
        name='high' if a['role'] in ('high_flank','high_cover','center_1') else 'low'
        bunker=next(o for o in own if o.id.endswith(name))
        # Small personal footwork stays around the assigned station. Cover
        # holds stay fixed; carriers' actual collection/relay routes are separate.
        if a['opening_stashed'] and a['ammo'] and 'cover' not in a['role'] and obs.get('job',{}).get('kind') not in ('relay','relay_fetch','wait_delivery','delivered_collect'):
            phase=obs['time']*(.75+.07*self.index)+self.index*1.7+(0 if a['team']=='attack' else 2.1)
            spread=.27 if a['role'].startswith('center') else .18
            offset=(.07*sin(phase*.73),spread*sin(phase))
            hold=tuple(v+d for v,d in zip(hold,offset));peek=tuple(v+d for v,d in zip(peek,offset))
        return bunker,hold,peek

    def threat(self,obs):
        a=obs['self'];x,y=a['position'];score=0
        for b in obs['flying_arrows']:
            if b.get('team')==a['team']:continue
            rx,ry=b['position'][0]-x,b['position'][1]-y;vx,vy=b['velocity'][:2]
            t=-(rx*vx+ry*vy)/max(1e-9,vx*vx+vy*vy)
            if 0<t<.7 and hypot(rx+vx*t,ry+vy*t)<.8:score+=1.4
        score+=.55*sum(p.get('aiming',False) and hypot(p['position'][0]-x,p['position'][1]-y)<24 for p in obs['enemies'])
        return score

    def _go(self,obs,goal,kind,crouch=False):
        self._set_intent(kind,goal)
        a=obs['self'];return self._evading_action(obs,Action(move=self.move_to(a['position'],goal,a['team'],obs['time']),crouch=crouch))

    def _collect(self,obs,job):
        a=obs['self'];goal=job.get('approach');bid=job.get('arrow')
        if goal is None:return None
        self._set_intent('pickup',goal,bid)
        if a['bow_state']!='empty' and job.get('kind')=='relay':
            if self.threat(obs)>.8:return self._go(obs,self._positions(obs)[1],'hold')
            return TacticalAction(interaction='unnock')
        if hypot(a['position'][0]-goal[0],a['position'][1]-goal[1])<.03:
            return self._evading_action(obs,TacticalAction(interaction='pickup',pickup_id=bid,crouch=True))
        dx,dy=goal[0]-a['position'][0],goal[1]-a['position'][1]
        if hypot(dx,dy)<.35 and self.nav.clear(a['position'],goal):
            # Use explicit fine steering for the reachable hand-approach point;
            # scale speed over the decision interval to avoid overshoot.
            span=self.config['physics']['move_speed_m_s']*self.config['policy']['decision_interval_s']
            return self._evading_action(obs,Action(move=(dx/span,dy/span)))
        return self._evading_action(obs,Action(move=self.move_to(a['position'],goal,a['team'],obs['time'])))

    def _logistics(self,obs):
        a=obs['self'];job=obs.get('job',{});now=obs['time'];kind=job.get('kind')
        if kind=='wait_delivery' and not a['ammo']:
            anchor=job['goal']
            if now>job['deadline']:return None
            self._set_intent('wait_delivery',anchor)
            if hypot(a['position'][0]-anchor[0],a['position'][1]-anchor[1])>.2:
                return self._go(obs,anchor,'wait_delivery',crouch='cover' in a['role'] and self._positions(obs)[0].size[2]<1)
            return Action(crouch='cover' in a['role'] and self._positions(obs)[0].size[2]<1)
        if kind=='relay':
            if 'goal' not in job or 'throw_from' not in job:return None
            receiver=next((p for p in obs['team_roster'] if p['id']==job['receiver']),None)
            if receiver is None or receiver.get('ammo',0)>0 or not a['ammo']:return None
            # The contract fixes a landing location; do not chase a moving
            # teammate or repeatedly pass every newly acquired arrow away.
            if a['bow_state']!='empty':
                if a['ammo']<=1 or self.threat(obs)>.8:return None
                self._set_intent('supply',job['goal']);return TacticalAction(interaction='unnock')
            where=job['throw_from']
            if hypot(a['position'][0]-where[0],a['position'][1]-where[1])>.1:
                return self._go(obs,where,'supply')
            self._set_intent('pass',job['goal'])
            if now>=max(a['throw_ready_at'],a['hands_busy_until']):
                return TacticalAction(interaction='throw',throw_to=receiver['id'])
            return Action()
        if kind in ('collect','relay_fetch','delivered_collect') and job.get('arrow') is not None:
            if a['ammo']>=job.get('quota',1):return None
            if a['ammo']==3 and a['bow_state']=='empty' and job.get('quota')==4:return TacticalAction(interaction='nock')
            return self._collect(obs,job)
        return None

    def _revive(self,obs):
        a=obs['self'];now=obs['time'];d=1 if a['team']=='attack' else -1
        pad=tuple(self.config['suzhou']['revive_pads'][a['team']]);staging=(pad[0]-d*1.2,pad[1])
        if now<self.revive_retry:return None
        if a['bow_state']=='empty':
            self._set_intent('nock',staging)
            return TacticalAction(interaction='nock',move=self.move_to(a['position'],staging,a['team'],now))
        if a['bow_state']=='nocking':return self._go(obs,staging,'nock')
        danger=self.threat(obs)
        if danger>1.3 and hypot(a['position'][0]-staging[0],a['position'][1]-staging[1])>.35 and not a['on_revive_pad']:
            return self._go(obs,staging,'hold')
        rack=next(r for r in obs['racks'] if r['team']=='revive')
        spots=[k for k in [0,1,2,3,4] if rack['standing'][k]]
        if not spots:return None
        if self.revive_key not in spots:self.revive_key=spots[0]
        k=self.revive_key;point=rack['spots'][k];quick=danger>=.55
        self._set_intent('revive_snap' if quick else 'revive',pad)
        move=self.move_to(a['position'],pad,a['team'],now) if not a['on_revive_pad'] else (0,0)
        # Pre-aim while approaching; physical release remains gated by foot contact.
        return self._evading_action(obs,TacticalAction(move=move,aim=point,aim_key=f'rack:revive:{k}',interaction='shoot',quick_shot=quick))

    def _targets(self,obs):
        role=obs['self']['role'];view=dict(obs)
        if role in ('high_cover','high_flank'):
            busy=[p for p in obs['enemies'] if p['position'][1]<5 and (p.get('aiming') or abs(p['position'][0]-(22 if obs['self']['team']=='attack' else 10))<1)]
            if busy and self.rng.random()<.65:view['enemies']=busy
            self.target_interest=.40 if role=='high_cover' else .10
        elif role=='low_cover':
            view['enemies']=[p for p in obs['enemies'] if p['position'][1]<8]
            self.target_interest=.65
        elif role=='revive_lane':
            view['enemies']=[p for p in obs['enemies'] if p['position'][1]<7]
            self.target_interest=.25
        else:self.target_interest=.35
        return super()._targets(view)

    def _act(self,obs):
        action=self._role_action(obs)
        if obs['self']['status']=='eliminated' or action.evasion_kind:return action
        # Reactive defence applies to every branch, including empty bows,
        # transfer commands, failed target acquisition and stationary waiting.
        defended=self._evading_action(obs,action)
        if defended.evasion_kind:return defended
        a=obs['self']
        if action.aim is not None and a['aim_elapsed']<.18 and 'cover' not in a['role'] and a['aim_style']!='deliberate' and any(p.get('aiming') for p in obs['enemies']):
            side=1 if sin(obs['time']*1.7+self.index)>0 else -1
            goal=(a['position'][0],a['position'][1]+side*.08)
            if self.nav.clear(a['position'],goal):return replace(action,move=(0,side*.18))
        return defended

    def _role_action(self,obs):
        a=obs['self'];now=obs['time'];self.role=a['role'];self._set_intent('hold')
        if a['status']=='eliminated':self._set_intent('out');return Action()
        self._remember(obs);bunker,hold,peek=self._positions(obs)
        if a['last_shot_at']>self.last_release:
            self.last_release=a['last_shot_at'];self.follow_until=now+self.rng.uniform(.18,.32)
            if self.intent.get('kind') in ('revive','revive_snap') or (a['position'][1]<2.6 and abs(a['position'][0]-self.config['suzhou']['revive_pads'][a['team']][0])<.7):
                self.escape_until=now+1.;self.revive_retry=now+1.6
        if now<self.escape_until:return self._go(obs,hold,'escape')
        if now<self.follow_until:
            self._set_intent('follow');return self._evading_action(obs,Action())
        if not a['opening_stashed']:
            return super()._act(obs)
        logistics=self._logistics(obs)
        if logistics is not None:return logistics
        if obs.get('revive_runner')==a['id'] and obs['revive_queue'] and a['ammo']:
            action=self._revive(obs)
            if action is not None:return action
        if not a['ammo']:
            return self._go(obs,hold,'request' if 'cover' in a['role'] else 'search',crouch='cover' in a['role'])
        if a['bow_state']=='empty':
            self._set_intent('nock',hold)
            return TacticalAction(interaction='nock',move=self.move_to(a['position'],hold,a['team'],now),crouch='cover' in a['role'] and bunker.size[2]<1)
        if a['bow_state']=='nocking':return self._go(obs,hold,'nock',crouch='cover' in a['role'] and bunker.size[2]<1)
        if 'cover' in a['role']:
            if self.next_peek is None:self.next_peek=now+self.rng.uniform(.5,1.3)
            if self.phase=='hide':
                if now<self.next_peek or hypot(a['position'][0]-hold[0],a['position'][1]-hold[1])>.2:
                    return self._go(obs,hold,'guard',crouch=bunker.size[2]<1)
                self.phase='peek';self.peek_until=now+a['aim_required']+self.rng.uniform(.7,1.4)
            if now>self.peek_until:
                self.phase='hide';self.next_peek=now+self.rng.uniform(.6,1.5)
                return self._go(obs,hold,'guard',crouch=bunker.size[2]<1)
        distance=hypot(a['position'][0]-peek[0],a['position'][1]-peek[1]);station_move=(0,0)
        if distance>(.18 if 'cover' in a['role'] else .08):
            if 'cover' not in a['role'] and distance<.65:
                # Local stance adjustments may coexist with aiming; routing
                # back to a far-away station still interrupts the shot.
                station_move=self.move_to(a['position'],peek,a['team'],now)
            else:return self._go(obs,peek,'guard')
        target=self._targets(obs)
        if target is None:return self._evading_action(obs,Action(move=station_move))
        aim=self._aim(obs,target)
        if not self._clear_arc(obs,aim,target[0]):self.target_key=None;self.aim_cache=None;return Action(move=station_move)
        self._set_intent('shoot_low' if aim[2]<.55 and not str(target[0]).startswith('rack:') else 'shoot')
        return self._evading_action(obs,Action(move=station_move,aim=aim,aim_key=target[0],interaction='shoot'))
