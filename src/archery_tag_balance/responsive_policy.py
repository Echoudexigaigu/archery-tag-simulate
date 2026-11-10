"""Suzhou v2: rear centers, portable opening stock, visible threats and low aim."""
from dataclasses import replace
from math import hypot,log,sin
from .entities import Action
from .geometry import advance_arrow
from .suzhou_policy import SuzhouPolicy as BaseSuzhouPolicy


class SuzhouPolicy(BaseSuzhouPolicy):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.intent={}
        self.first_seen={}
        self.body_bands={}

    def _positions(self,obs):
        a=obs['self'];team=a['team'];d=1 if team=='attack' else -1
        own=[o for o in self.nav.obstacles if o.id.startswith(team+'_')]
        left=max(own,key=lambda o:o.center[1]) if d==1 else min(own,key=lambda o:o.center[1])
        right=next(o for o in own if o is not left)
        cover=left if self.index<3 else right
        if 'cover' in self.role:
            hold=(cover.center[0]-d*(cover.size[0]/2+.43),cover.center[1])
            outward=1 if cover.center[1]>10 else -1
            peek=(hold[0],hold[1]+outward*(cover.size[1]/2+.44))
        elif 'flank' in self.role:
            outward=1 if cover.center[1]>10 else -1
            hold=(cover.center[0]-d*(cover.size[0]/2+1.6),cover.center[1]+outward*2.2)
            peek=(hold[0]+d*.5,hold[1]+.20*sin(obs['time']*.8+self.index))
        else:
            depth=self.config['policy']['center_depth_m'][self.index-2]
            x=depth if d==1 else self.config['field']['length_m']-depth
            y=a['spawn'][1]+self.config['policy']['center_motion_amplitude_m']*sin(obs['time']*.9+self.index)
            hold=peek=(x,y)
        return cover,hold,peek

    def _set_intent(self,kind,goal=None,arrow=None):
        self.intent=dict(kind=kind,goal=goal,arrow=arrow)

    def _act(self,obs):
        a=obs['self'];team=a['team'];pos=a['position'];now=obs['time']
        self._set_intent('out' if a['status']=='eliminated' else 'hold')
        if a['status']=='eliminated':return Action()
        if not a['opening_stashed']:
            if a['ammo']<self.config['policy']['opening_gather_quota']:
                goal=obs['opening_pile'];self._set_intent('gather',goal)
                local=[b for b in obs['ground_arrows'] if abs(b['position'][0]-goal[0])<.1 and hypot(b['position'][0]-goal[0],b['position'][1]-goal[1])<.3]
                if local:self.intent['arrow']=local[0]['id']
                if hypot(goal[0]-pos[0],goal[1]-pos[1])<.60:
                    return self._evading_action(obs,Action(interaction='pickup',crouch=True))
                return self._evading_action(obs,Action(move=self.move_to(pos,goal,team,now)))
            goal=a['cache_position'];self._set_intent('cache',goal)
            if hypot(goal[0]-pos[0],goal[1]-pos[1])<.18:
                return Action(interaction='drop')
            return self._evading_action(obs,Action(move=self.move_to(pos,goal,team,now)))
        if a['ammo'] and a['reload_left']<=0 and obs.get('revive_runner')==a['id'] and obs.get('revive_queue'):
            self._set_intent('revive',self.config['suzhou']['revive_pads'][team])
        action=super()._act(obs)
        if action.aim is not None and not self.intent.get('goal'):
            self._set_intent('shoot_low' if action.aim[2]<.55 and not str(action.aim_key).startswith('rack:') else 'shoot')
        if action.evasion_kind:return action
        # Read the visible act of aiming, not an opponent's hidden target choice.
        # A small preparatory weight shift may buy space, with a moving-shot cost.
        if action.aim is not None and a['aim_elapsed']<.16 and a['aim_style']!='deliberate' and 'cover' not in self.role and any(p.get('aiming') for p in obs['enemies']):
            side=1 if sin(now*1.9+self.index)>0 else -1
            delta=(0,side*.22)
            goal=(pos[0],pos[1]+delta[1]*.2*self.config['physics']['move_speed_m_s'])
            if .4<goal[1]<19.6 and self.nav.clear(pos,goal):
                return replace(action,move=delta)
        return action

    def _resupply(self,obs,bunker):
        assignment=obs.get('supply_assignment')
        if assignment is not None:
            self._set_intent('pickup',assignment['position'][:2],assignment['id'])
            return super()._resupply(obs,bunker)
        if 'center' in self.role:
            _,hold,_=self._positions(obs)
            self._set_intent('search',hold)
            return Action(move=self.move_to(obs['self']['position'],hold,obs['self']['team'],obs['time']))
        action=super()._resupply(obs,bunker)
        self._set_intent('search',self.goal)
        return action

    def _targets(self,obs):
        a=obs['self'];now=obs['time'];bodies=[];racks=[]
        weights=self.config['policy']['body_aim_band_weights']
        for enemy in obs['enemies']:
            if enemy['status']!='active':continue
            key=enemy['id'];entry=self.body_bands.get(key)
            if entry is None or (now>entry[1] and self.target_key!=key):
                band=self.rng.choices(list(weights),list(weights.values()))[0]
                self.body_bands[key]=(band,now+self.rng.uniform(3,6))
            band=self.body_bands[key][0];height=enemy['height']
            heights={'low':min(.36,height*.32),'torso':height*.57,'upper':height*.86}
            # Find an exposed real height; a low shot must not pass through cover.
            order=[band]+[b for b in ['torso','upper','low'] if b!=band]
            for chosen in order:
                point=(*enemy['position'],heights[chosen])
                distance=hypot(point[0]-a['position'][0],point[1]-a['position'][1])
                if distance<=self.config['policy']['engage_distance_m'] and self._clear_arc(obs,point,key):
                    bodies.append((key,point,enemy,distance));break
        for rack in obs['racks']:
            if rack['team'] in (a['team'],'revive'):continue
            for k,standing in enumerate(rack['standing']):
                if not standing:continue
                point=rack['spots'][k];key=f"rack:{rack['team']}:{k}"
                distance=hypot(point[0]-a['position'][0],point[1]-a['position'][1])
                if distance<=self.config['policy']['engage_distance_m'] and self._clear_arc(obs,point,key):
                    racks.append((key,point,None,distance))
        all_targets=bodies+racks
        chosen=next((p for p in all_targets if p[0]==self.target_key),None)
        if chosen is None or now>=self.lock_until:
            pool=racks if racks and (not bodies or self.rng.random()<self.target_interest) else bodies
            if not pool:self.target_key,self.aim_cache=None,None;return None
            chosen=min(pool,key=lambda v:v[3]*self.rng.uniform(.9,1.15))
            if chosen[0]!=self.target_key:self.aim_cache,self.next_aim_update=None,0
            self.target_key,self.lock_until=chosen[0],now+self.rng.uniform(2.5,5)
        return chosen

    def _aim(self,obs,target):
        key,point,enemy,distance=target;now=obs['time']
        if self.aim_cache is None or now>=self.next_aim_update:
            if enemy is not None:
                history=self.histories.get(key,[])
                old=[p for t,p in history if t<=now-self.latency]
                snapshot=old[-1] if old else (history[0][1] if history else enemy)
                nominal=obs['self']['muzzle_speed_fps']*.3048
                lead=distance/nominal*self.lead_fraction
                point=(snapshot['position'][0]+snapshot['velocity'][0]*lead,snapshot['position'][1]+snapshot['velocity'][1]*lead,point[2])
            self.aim_cache=point;self.next_aim_update=now+self.rng.uniform(.25,.55)
        return self.aim_cache

    def _compact_evade(self,obs,move,crouch):
        a=obs['self'];now=obs['time'];e=self.config['evasion'];p=self.config['physics']
        self.evade_action=None
        if now+1e-9<getattr(self,'gesture_until',0):
            self.evade_action=self.gesture
            return self.gesture.move,self.gesture.crouch,True
        for b in obs['flying_arrows']:
            if b.get('team')!=a['team']:
                self.first_seen.setdefault((b['id'],b.get('released_at',0)),now)
        if now<max(a['movement_dodge_ready_at'],a['dodge_ready_at']) or a['stamina']<min(e['movement_cost'],e['duck_cost']):return move,crouch,False
        threats=[];x,y=a['position']
        for b in obs['flying_arrows']:
            key=(b['id'],b.get('released_at',0))
            if b.get('team')==a['team'] or now-self.first_seen.get(key,now)+1e-9<a['reaction_s'] or key==getattr(self,'last_reacted',None):continue
            vx,vy,_=b['velocity'];rx,ry=b['position'][0]-x,b['position'][1]-y
            ux=vx-a['velocity'][0];uy=vy-a['velocity'][1]
            t=-(rx*ux+ry*uy)/max(1e-9,ux*ux+uy*uy)
            if not 0<t<e['lookahead_s']:continue
            # Refine closest approach with drag; constant-speed extrapolation
            # otherwise places a slowing arrow metres short of the player.
            for _ in range(3):
                q,v=advance_arrow(b['position'],b['velocity'],t,p['gravity_m_s2'],p['linear_drag_s_inv'])
                rx2,ry2=q[0]-x-a['velocity'][0]*t,q[1]-y-a['velocity'][1]*t
                vx2,vy2=v[0]-a['velocity'][0],v[1]-a['velocity'][1]
                derivative=vx2*vx2+vy2*vy2-p['linear_drag_s_inv']*(rx2*v[0]+ry2*v[1])
                if derivative<=1e-8:break
                t=max(0,min(e['lookahead_s'],t-(rx2*vx2+ry2*vy2)/derivative))
            if not 0<t<e['lookahead_s']:continue
            q,_=advance_arrow(b['position'],b['velocity'],t,p['gravity_m_s2'],p['linear_drag_s_inv'])
            forecast=(x+a['velocity'][0]*t,y+a['velocity'][1]*t)
            height=p['crouched_height_m'] if crouch else p['player_height_m']
            if hypot(q[0]-forecast[0],q[1]-forecast[1])<self.config['motion_refinement']['forecast_tolerance_m'] and 0<q[2]<height+.07:
                threats.append((t,b,q[2],key))
        if not threats:return move,crouch,False
        _,b,z,key=min(threats,key=lambda v:v[0]);vx,vy=b['velocity'][:2];n=max(1e-9,hypot(vx,vy));side=(-vy/n,vx/n)
        fatigue=.65+.35*a['stamina'];duration=e['movement_duration_s'];variants=[]
        signs=[-1,1];self.rng.shuffle(signs)
        if a['stamina']>=e['movement_cost']:
            for sign in signs:
                distance=self.rng.uniform(*self.config['motion_refinement']['sidestep_range_m'])*fatigue
                variants.append(('sidestep',(side[0]*sign*distance,side[1]*sign*distance),crouch))
        if z>p['crouched_height_m']+.1 and a['stamina']>=e['duck_cost']:
            variants.append(('duck',(0,0),True))
            if getattr(self,'preferred_duck',False):variants.insert(0,variants.pop())
        lo,hi=self.config['teams'][a['team']]['move_x_bounds_m']
        for style,delta,duck in variants:
            goal=(x+delta[0],y+delta[1])
            if not lo<=goal[0]<=hi or not .3<goal[1]<19.7 or not self.nav.clear((x,y),goal):continue
            if any(hypot(goal[0]-f['position'][0],goal[1]-f['position'][1])<.62 for f in obs.get('teammates',[])):continue
            speed=p['move_speed_m_s']*(p['crouch_speed_fraction'] if duck else 1)
            action=Action(move=(delta[0]/(speed*duration),delta[1]/(speed*duration)),crouch=duck,evasion_kind=style,evade_key=key)
            self.last_reacted,self.gesture,self.gesture_until=key,action,now+duration
            self.evade_action=action
            return action.move,action.crouch,True
        return move,crouch,False
