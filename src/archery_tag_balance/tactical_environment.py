"""V3 role ownership, explicit bow preparation and nonlethal arrow logistics."""
from collections import Counter
from dataclasses import replace
from math import hypot,cos,sin,atan2,radians

from .suzhou import SuzhouEnvironment as V2Environment
from .entities import Action,Status
from .environment import Environment
from .human_skirmish import HumanSkirmishEnvironment
from .geometry import segment_box,advance_arrow
from .tactical_entities import ROLES,ROLE_NAMES,positions


class SuzhouEnvironment(V2Environment):
    def _setup_opening(self):
        super()._setup_opening()
        self.role_owners={t:{} for t in self.config['teams']}
        self.vacant_since={};self.next_role_change={t:0 for t in self.config['teams']}
        self.queue_since={t:None for t in self.config['teams']}
        self.wait_slots={};self.pending_discards=[];self.jobs={};self.pickup_spots_cache={}
        self.current_actions={};self.supply_scan_at=0;self.next_plan_at=0
        self.arrows.clear();self.opening_bundles={}
        if hasattr(self,'supply_coordinator'):del self.supply_coordinator
        ys=(18,15.45,12,8.2,5,2)
        for a in self.agents.values():
            i=int(a.id.rsplit('_',1)[1]);a.home_role=a.role=ROLES[i]
            a.spawn=a.position=(a.spawn[0],ys[i])
            a.bow_state='empty';a.nocked_arrow=None;a.snap_revive=False
            a.last_command=None;a.throw_ready_at=0.;a.hands_busy_until=0.
            a.role_since=0.;a.hit_pause_until=0.;a.last_collect_at=0.
            a.stall_since=None;a.last_progress_position=a.position
            a.stall_target=None;a.stall_best_distance=float('inf')
            a.human_profile.setdefault('carry_preference',self.profile_rng.choices([1,2,3,4],[.64,.25,.09,.02])[0])
            a.human_profile.setdefault('carry_skill',self.profile_rng.uniform(.65,1))
            self.role_owners[a.team][a.role]=a.id
            hold,_=positions(self,a.team,a.role)
            if 'cover' in a.role:cache=hold
            elif a.role=='high_flank':cache=(hold[0],15.65)
            elif a.role=='revive_lane':cache=(hold[0]-.6*(1 if a.team=='attack' else -1),2.3)
            else:cache=(3.3 if a.team=='attack' else 28.7,hold[1])
            self.cache_positions[a.id]=cache
            self.opening_bundles[a.id]=[self._new_arrow((*self.opening_pile(a),0)).id for _ in range(3)]
        self.total_arrows=len(self.arrows)

    def _allowed_arrow_states(self):
        return super()._allowed_arrow_states()|{'tossed','discard_pending'}

    def _prepare_arrow(self,a):
        # V2's pickup/drop callbacks must not silently load a bow in V3.
        pass

    def _next_pickup_duration(self,a):
        bounds=self.config['v3']['professional_pickup_range_s']
        a.pickup_required_s=self.rng.uniform(*bounds)*max(.85,min(1.15,a.human_profile.get('pickup_tempo',1)))

    def _pickup_duration(self,a):
        return a.pickup_required_s

    def _pickup(self,actions,dt):
        remaining=dict(actions)
        for aid,action in actions.items():
            a=self.agents[aid]
            if a.status!=Status.ACTIVE or a.opening_received or a.opening_stashed or a.inventory or action.interaction!='pickup':continue
            lo,hi=self.config['teams'][a.team]['pickup_x_bounds_m']
            for ids in self.opening_bundles.values():
                bunch=[self.arrows[bid] for bid in ids]
                if any(b.state!='ground' for b in bunch):continue
                anchor=bunch[0].position
                if not lo<=anchor[0]<=hi or hypot(a.position[0]-anchor[0],a.position[1]-anchor[1])>.7:continue
                if any(hypot(b.position[0]-anchor[0],b.position[1]-anchor[1])>.15 or not self._pickup_allowed(a,b) for b in bunch):continue
                for b in bunch:
                    self._carry(b,a);self._picked_up(a,b);self._emit('pickup',agent=aid,arrow=b.id)
                a.pickup_elapsed=0;self._emit('opening_bundle',agent=aid,arrows=list(ids))
                remaining[aid]=replace(action,interaction='none');break
        super()._pickup(remaining,dt)

    def _request_nock(self,a):
        if a.status!=Status.ACTIVE or not a.inventory or a.bow_state!='empty' or self.t<a.hands_busy_until:return
        a.nocked_arrow=a.inventory[0];a.bow_state='nocking'
        duration=self.rng.uniform(*self.config['v3']['professional_nock_range_s'])*max(.85,min(1.15,a.human_profile['tempo']))
        a.reload_left=duration;a.human_aim_s=self._sample_aim_duration(a)
        a.aim_elapsed=0;a.aim_key=None
        self._emit('nock',agent=a.id,duration=duration,aim_required=a.human_aim_s,fumble=False)

    def _picked_up(self,a,b):
        first=not a.opening_received
        a.opening_received=a.center_visited=a.shoot_unlocked=True
        b.opening_arrow,b.opening_owner=False,None
        a.last_collect_at=self.t
        self._next_pickup_duration(a)
        if first:self._emit('opening_arrow_collected',agent=a.id)

    def _aim_duration(self,a):
        return self.config['v3']['snap_aim_s'] if a.snap_revive else a.human_aim_s

    def _accuracy_multiplier(self,a):
        extra=max(0,len(a.inventory)-1)
        return super()._accuracy_multiplier(a)*(1+extra*self.config['v3']['extra_carry_error_cost']*(1.4-.4*a.human_profile['carry_skill']))*(self.config['v3']['snap_error_multiplier'] if a.snap_revive else 1)

    def on_revive_pad(self,a):
        x,y=self.config['suzhou']['revive_pads'][a.team]
        w,h=self.config['suzhou']['revive_pad_size_m']
        # Foot contact: two feet roughly +/-13cm from the tracked body center.
        return abs(a.position[0]-x)<=w/2+.13+1e-9 and abs(a.position[1]-y)<=h/2+.10+1e-9

    def _release(self,a,action):
        if a.bow_state!='ready' or a.nocked_arrow not in a.inventory or self.t<a.hands_busy_until:return
        if str(action.aim_key).startswith('rack:revive') and not self.on_revive_pad(a):return
        a.inventory.remove(a.nocked_arrow);a.inventory.insert(0,a.nocked_arrow)
        before=self.counts['shot'];bid=a.nocked_arrow
        super()._release(a,action)
        if self.counts['shot']!=before:
            a.bow_state='empty';a.nocked_arrow=None
            # The explicit next nock replaces the legacy post-shot reload wait.
            a.reload_left=0
            self.arrows[bid].dead_kind='shot';self.arrows[bid].pass_recipient=None
            self._emit('release_cue',agent=a.id,arrow=bid,position=a.position,aim=action.aim,quick=a.snap_revive)

    def _carry(self,b,a):
        super()._carry(b,a);b.pass_recipient=None

    def _movement_speed(self,a):
        p=self.config['physics'];v=self.config['v3'];factor=1
        if getattr(a,'bow_state','empty')=='ready':factor*=v['loaded_speed_multiplier']
        elif getattr(a,'bow_state','empty')=='nocking':factor*=v['nocking_speed_multiplier']
        factor*=max(.8,1-max(0,len(a.inventory)-1)*v['extra_carry_speed_cost'])
        if self.t<getattr(a,'hands_busy_until',0):factor*=.85
        return p['move_speed_m_s']*(p['crouch_speed_fraction'] if a.crouched else 1)*factor

    def step(self,actions,observe=True):
        self.current_actions=dict(actions)
        processed=dict(actions)
        for aid,action in actions.items():
            a=self.agents[aid];a.snap_revive=bool(getattr(action,'quick_shot',False))
            kind=action.interaction
            if kind not in ('nock','unnock','throw'):continue
            command=(kind,getattr(action,'token',0))
            if command!=a.last_command and a.status==Status.ACTIVE:
                a.last_command=command
                if kind=='nock':self._request_nock(a)
                elif kind=='unnock':
                    if len(a.inventory)==4:self._ground(self.arrows[a.inventory.pop()],(*a.position,0))
                    a.bow_state='empty';a.nocked_arrow=None;a.reload_left=0;a.aim_elapsed=0
                    a.hands_busy_until=self.t+.3
                elif kind=='throw':self._throw_from_agent(a,getattr(action,'throw_to',None))
            processed[aid]=replace(action,interaction='none')
        return super().step(processed,observe)

    def _timers(self,dt):
        super()._timers(dt)
        for a in self.agents.values():
            if a.status==Status.ACTIVE and a.bow_state=='nocking' and a.reload_left<=1e-9:
                a.bow_state='ready';self._emit('bow_ready',agent=a.id)
        for row in list(self.pending_discards):
            if self.t+1e-9>=row['at']:
                b=self.arrows[row['arrow']]
                self._start_toss(b,row['origin'],row['goal'],row['owner'],True)
                self.pending_discards.remove(row)

    def _start_toss(self,b,origin,goal,owner,casual=False):
        dx,dy=goal[0]-origin[0],goal[1]-origin[1];distance=hypot(dx,dy)
        cap=self.config['v3']['death_discard_range_m'] if casual else self.config['v3']['throw_range_m']
        scale=min(1,cap/max(distance,1e-9));dx*=scale;dy*=scale
        # Aim short to allow a dead arrow to bounce/slide towards the recipient.
        trim=min(.7,hypot(dx,dy)*.18);n=max(.01,hypot(dx,dy));dx-=dx/n*trim;dy-=dy/n*trim
        error=.38 if casual else .17
        dx+=self.rng.gauss(0,error);dy+=self.rng.gauss(0,error)
        duration=.48+min(.45,hypot(dx,dy)/12)
        z=.8 if casual else 1.0
        b.state='tossed';b.carrier=None;b.position=(*origin,z);b.shooter=owner
        b.velocity=(dx/duration,dy/duration,(.5*9.81*duration**2-z)/duration)
        b.flight_left=duration+1;b.released_at=self.t;b.dead_kind='discard' if casual else 'pass'
        self._emit('death_discard' if casual else 'arrow_pass',agent=owner,arrow=b.id,origin=origin,goal=goal)

    def _throw_from_agent(self,a,receiver):
        if a.bow_state!='empty' or not a.inventory or self.t<max(a.throw_ready_at,a.hands_busy_until):return
        friend=self.agents.get(receiver)
        if friend is None or friend.team!=a.team or friend.status!=Status.ACTIVE:return
        coordinator=getattr(self,'supply_coordinator',None)
        goal=coordinator.transfer_goal(a,receiver) if coordinator else friend.position
        if hypot(goal[0]-a.position[0],goal[1]-a.position[1])>self.config['v3']['throw_range_m']:return
        if coordinator and not coordinator.clear_throw(a.position,goal):return
        job=self.jobs.get(a.id,{})
        chosen=job.get('arrow_to_throw')
        bid=chosen if chosen in a.inventory else a.inventory[-1]
        a.inventory.remove(bid);self._start_toss(self.arrows[bid],a.position,goal,a.id)
        self.events[-1]['receiver']=receiver
        if coordinator:coordinator.dispatched(a,bid,receiver)
        self.arrows[bid].pass_recipient=receiver
        a.throw_ready_at=self.t+self.config['v3']['throw_cooldown_s'];a.hands_busy_until=self.t+.35

    def _fly(self,dt,old_positions,new_positions,actions,rewards):
        for b in self.arrows.values():
            if b.state!='tossed':continue
            p=b.position;q,v=advance_arrow(p,b.velocity,dt,9.81,0)
            hits=[]
            if q[2]<=0:hits.append((p[2]/max(1e-9,p[2]-q[2]),'ground'))
            for o in self.navigation_obstacles:
                u=segment_box(p,q,*o.bounds(.025))
                if u is not None:hits.append((u,'obstacle'))
            for axis,bound in ((0,0),(0,32),(1,0),(1,20)):
                if q[axis]<0 or q[axis]>(32 if axis==0 else 20):
                    if abs(q[axis]-p[axis])>1e-9:
                        u=(bound-p[axis])/(q[axis]-p[axis])
                        if 0<=u<=1:hits.append((u,'boundary'))
            if hits:
                u,kind=min(hits);point=tuple(x+(y-x)*u for x,y in zip(p,q))
                if kind=='ground':self._toss_settle(b,point,v)
                else:self._ground(b,point)
            else:b.position,b.velocity=q,v
        super()._fly(dt,old_positions,new_positions,actions,rewards)

    def _toss_settle(self,b,point,velocity):
        self._ground(b,point)
        spec=self.config['v3'];limit=radians(spec['toss_max_deviation_degrees'])
        angle=atan2(velocity[1],velocity[0])+max(-limit,min(limit,self.rng.gauss(0,radians(spec['toss_direction_sd_degrees']))))
        b.state='settling';b.carrier=None;b.landing_origin=b.position
        b.settling_heading=(cos(angle),sin(angle));b.settling_distance=self.rng.uniform(.35,1.5)
        b.settling_duration=self.rng.uniform(.45,.9);b.settling_elapsed=0
        b.settling_curve=self.rng.uniform(-.25,.25);b.settling_hops=self.rng.choice([2,3]);b.settling_height=.12
        b.settling_kind='hand_throw';b.velocity=(*velocity[:2],0)

    def _ground(self,b,point):
        super()._ground(b,point)
        if not hasattr(self,'navigation_obstacles'):return
        x,y=b.position[:2];changed=False
        for _ in range(3):
            for o in self.navigation_obstacles:
                lo,hi=o.bounds(.031)
                if lo[0]<x<hi[0] and lo[1]<y<hi[1]:
                    _,axis,value=min((abs(x-lo[0]),0,lo[0]-.003),(abs(x-hi[0]),0,hi[0]+.003),(abs(y-lo[1]),1,lo[1]-.003),(abs(y-hi[1]),1,hi[1]+.003))
                    if axis==0:x=value
                    else:y=value
                    changed=True
        if changed:
            b.position=(max(0,min(32,x)),max(0,min(20,y)),0)
            self.counts['arrow_edge_releases']+=1

    def pickup_points(self,b,team):
        key=(b.id,team,round(b.position[0],3),round(b.position[1],3))
        if key in self.pickup_spots_cache:return self.pickup_spots_cache[key]
        x,y=b.position[:2];lo,hi=self.config['teams'][team]['move_x_bounds_m'];points=[]
        for distance in [0,.35,.54,.64]:
            for i in range(12 if distance else 1):
                angle=i*6.28318530718/12;p=(x+distance*cos(angle),y+distance*sin(angle))
                if not lo<=p[0]<=hi or not .27<=p[1]<=19.73:continue
                if any(segment_box((*p,.4),(*p,.4),*o.bounds(.27)) is not None for o in self.navigation_obstacles):continue
                if not self.line_clear((*p,.32),(x,y,.045)):continue
                points.append(p)
        self.pickup_spots_cache[key]=points
        return points

    def _pickup_allowed(self,a,b):
        if not super()._pickup_allowed(a,b) or self.t<a.hands_busy_until:return False
        if a.bow_state=='empty' and len(a.inventory)>=3:return False
        action=self.current_actions.get(a.id)
        bid=getattr(action,'pickup_id',None)
        if bid is not None and bid!=b.id:return False
        return self.line_clear((*a.position,.32),(b.position[0],b.position[1],.045))

    def _safe_change(self,a):
        if self.t-a.role_since<self.config['v3']['role_min_hold_s'] or a.aim_elapsed>.15 or hypot(*a.velocity)>1.2:return False
        if self.t-a.last_shot_at<.6:return False
        return not self._immediate_threat(a)

    def _immediate_threat(self,a):
        for b in self.arrows.values():
            if b.state!='flying' or self.agents[b.shooter].team==a.team:continue
            if hypot(b.position[0]-a.position[0],b.position[1]-a.position[1])>15:continue
            if not self.line_clear((*a.position,1.3),b.position):continue
            rx,ry=b.position[0]-a.position[0],b.position[1]-a.position[1];vx,vy=b.velocity[:2]
            t=-(rx*vx+ry*vy)/max(1e-9,vx*vx+vy*vy)
            if 0<t<.65 and hypot(rx+vx*t,ry+vy*t)<.8:return True
        return False

    def _set_role(self,a,role):
        owners=self.role_owners[a.team]
        for r,aid in list(owners.items()):
            if aid==a.id:owners.pop(r)
        old=a.role;a.role=role;a.role_since=self.t;owners[role]=a.id
        self._emit('role_change',agent=a.id,previous=old,role=role)

    def _plan_roles(self,team):
        owners=self.role_owners[team];active=[a for a in self.agents.values() if a.team==team and a.status==Status.ACTIVE]
        for role,aid in list(owners.items()):
            if self.agents[aid].status!=Status.ACTIVE:owners.pop(role)
        for a in active:
            if a.id not in owners.values():
                free=[r for r in ROLES if r not in owners]
                role=a.home_role if a.home_role in free else next((r for r in ['center_1','center_2'] if r in free),free[0] if free else 'center_1')
                self._set_role(a,role)
        if self.t<self.next_role_change[team]:return
        for role in self.config['v3']['vacancy_priority']:
            key=(team,role)
            if role in owners:self.vacant_since.pop(key,None);continue
            start=self.vacant_since.setdefault(key,self.t)
            if self.t-start<self.config['v3']['reassign_delay_s'] or role.startswith('center'):continue
            candidates=[a for a in active if a.role.startswith('center') and a.opening_stashed and self._safe_change(a)]
            if not candidates:continue
            goal=positions(self,team,role)[0]
            a=min(candidates,key=lambda a:hypot(a.position[0]-goal[0],a.position[1]-goal[1]))
            self._set_role(a,role);self.next_role_change[team]=self.t+self.config['v3']['reassign_interval_s'];break

    def _refresh_supply(self,team):
        if not hasattr(self,'supply_coordinator'):
            from .supply_coordinator import SupplyCoordinator
            self.supply_coordinator=SupplyCoordinator(self)
        self.supply_coordinator.refresh(team)

    def _update_rule_state(self):
        if self.t>=self.next_plan_at:
            for team in self.config['teams']:self._plan_roles(team)
            self.next_plan_at=self.t+.3
        if self.t>=self.supply_scan_at or self.supply_dirty:
            for team in self.config['teams']:self._refresh_supply(team)
            self.supply_scan_at=self.t+.5;self.supply_dirty=False
        for team in self.config['teams']:
            if self.revive_queue[team] and any(self.skirmish_racks['revive'].standing):
                if self.queue_since[team] is None:self.queue_since[team]=self.t
                available=[]
                if self.t-self.queue_since[team]>=self.config['v3']['revive_decision_delay_s']:
                    for role in ['revive_lane','low_cover']:
                        aid=self.role_owners[team].get(role)
                        if aid and self.agents[aid].inventory and self.agents[aid].opening_stashed:available.append(aid)
                self.revive_runner[team]=available[0] if available else None
            else:self.queue_since[team]=None;self.revive_runner[team]=None
        for a in self.agents.values():
            if a.status!=Status.ACTIVE:continue
            job=self.jobs.get(a.id,{})
            if job.get('arrow') is not None and job.get('approach') is not None:
                bid=job['arrow'];goal=job['approach'];distance=hypot(a.position[0]-goal[0],a.position[1]-goal[1])
                if a.stall_target!=bid or distance<a.stall_best_distance-.025:
                    a.stall_target=bid;a.stall_best_distance=distance;a.stall_since=self.t
                elif a.stall_since is not None and self.t-a.stall_since>self.config['v3']['pickup_stall_timeout_s']:
                    self.supply_avoid[(a.id,bid)]=self.t+3
                    self.supply_claims[a.team].pop(a.id,None);self.jobs.pop(a.id,None)
                    self.counts['stalled_replans']+=1;a.stall_target=None;a.stall_since=None;self.supply_dirty=True
                continue
            a.stall_target=None
            moving=hypot(*self.current_actions.get(a.id,Action()).move)>.1
            progress=hypot(a.position[0]-a.last_progress_position[0],a.position[1]-a.last_progress_position[1])
            if progress>.08:a.last_progress_position=a.position;a.stall_since=None
            elif moving:
                if a.stall_since is None:a.stall_since=self.t
                if self.t-a.stall_since>self.config['v3']['pickup_stall_timeout_s']:
                    bid=self.supply_claims[a.team].pop(a.id,None)
                    if bid is not None:self.supply_avoid[(a.id,bid)]=self.t+3
                    self.jobs.pop(a.id,None);self.counts['stalled_replans']+=1;a.stall_since=None
            else:a.stall_since=None

    @staticmethod
    def _separation(p,q,u,v):
        rx,ry=p[0]-u[0],p[1]-u[1];dx,dy=q[0]-p[0]-v[0]+u[0],q[1]-p[1]-v[1]+u[1]
        t=max(0,min(1,-(rx*dx+ry*dy)/max(1e-12,dx*dx+dy*dy)))
        return hypot(rx+t*dx,ry+t*dy)

    def _resolve_proposals(self,old,proposals,actions,dt):
        active=[a for a in self.agents.values() if a.status==Status.ACTIVE]
        for a in sorted(active,key=lambda a:(a.role=='revive_lane',a.id)):
            p=old[a.id];q=proposals[a.id]
            if p==q:continue
            others=[b for b in active if b.id!=a.id]
            if all(self._separation(p,q,old[b.id],proposals[b.id])>=.505 for b in others):continue
            dx,dy=q[0]-p[0],q[1]-p[1];variants=[]
            sign=1 if int(a.id.rsplit('_',1)[1])%2 else -1
            for degrees in [sign*60,-sign*60,sign*90,-sign*90,sign*135,180]:
                angle=radians(degrees);candidate=(p[0]+dx*cos(angle)-dy*sin(angle),p[1]+dx*sin(angle)+dy*cos(angle))
                if not self.valid_move(a,p,candidate):continue
                clearance=min((self._separation(p,candidate,old[b.id],proposals[b.id]) for b in others),default=10)
                if clearance>=.505:variants.append((clearance+.1*(dx*(candidate[0]-p[0])+dy*(candidate[1]-p[1])),candidate))
            if variants:proposals[a.id]=max(variants)[1];self.counts['local_yields']+=1
        return proposals

    def _eliminate(self,a,shooter,rewards):
        if a.status!=Status.ACTIVE:return
        origin=a.position;held=list(a.inventory);a.inventory.clear()
        Environment._eliminate(self,a,shooter,rewards)
        a.respawn_at=None;a.bow_state='empty';a.nocked_arrow=None
        self.scores[shooter.team]['body']+=1;self.revive_queue[a.team].append(a.id)
        self.outside_positions[a.id]=origin;self.out_stage[a.id]='hit'
        a.hit_pause_until=self.t+self.config['v3']['hit_pause_s']
        taken={slot for aid,slot in self.wait_slots.items() if self.agents[aid].team==a.team}
        slot=next(i for i in range(6) if i not in taken);self.wait_slots[a.id]=slot
        wx,wy=self.config['suzhou']['waiting_positions_m'][a.team]
        wait=(wx+(slot-2.5)*self.config['v3']['waiting_spacing_m'],wy)
        outside_x=-.35 if a.team=='attack' else 32.35
        self.out_routes[a.id]=[(a.spawn[0],origin[1]),(outside_x,origin[1]),(outside_x,wait[1]),wait]
        visible=[p for p in self.agents.values() if p.team==a.team and p.id!=a.id and p.status==Status.ACTIVE and hypot(p.position[0]-origin[0],p.position[1]-origin[1])<2.2 and self.line_clear((*origin,1),(*p.position,1))]
        friend=min(visible,key=lambda p:hypot(p.position[0]-origin[0],p.position[1]-origin[1])) if visible else None
        for bid in held:
            b=self.arrows[bid];b.state='discard_pending';b.carrier=None;b.position=(*origin,.7);b.velocity=(0,0,0)
            goal=friend.position if friend else (origin[0]+self.rng.uniform(-.9,.9),origin[1]+self.rng.uniform(-.9,.9))
            self.pending_discards.append(dict(arrow=bid,at=self.t+self.config['v3']['death_discard_delay_s'],origin=origin,goal=goal,owner=a.id))
        self._emit('queue_join',agent=a.id,position=len(self.revive_queue[a.team]),slot=slot)

    def _advance_out_route(self,a,dt):
        if self.out_stage.get(a.id)=='hit':
            if self.t<a.hit_pause_until:return
            self.out_stage[a.id]='leaving'
        was_out=a.status==Status.ELIMINATED
        super()._advance_out_route(a,dt)
        if was_out and a.status==Status.ACTIVE:
            self.wait_slots.pop(a.id,None);a.bow_state='empty';a.nocked_arrow=None
            a.aim_elapsed=0;a.role_since=self.t
            self._plan_roles(a.team)

    def get_observation(self,agent_id=None):
        obs=super().get_observation(agent_id)
        if agent_id is not None:
            a=self.agents[agent_id]
            obs['self'].update(bow_state=a.bow_state,hand_arrows=len(a.inventory)-(1 if a.nocked_arrow in a.inventory else 0),carry_preference=a.human_profile['carry_preference'],hands_busy_until=a.hands_busy_until,throw_ready_at=a.throw_ready_at)
            obs['job']=dict(self.jobs.get(a.id,{}))
            for p in obs['team_roster']:
                friend=self.agents[p['id']];p.update(role=friend.role,bow_state=friend.bow_state)
        return obs

    def _record_frame(self):
        super()._record_frame();f=self.trace[-1]
        for p in f['players']:
            a=self.agents[p['id']]
            job=self.jobs.get(a.id,{})
            p['job_partner']=job.get('receiver',job.get('donor'))
            p.update(role=a.role,bow_state=a.bow_state,hand_arrows=len(a.inventory)-(1 if a.nocked_arrow in a.inventory else 0),hit_pause=a.status==Status.ELIMINATED and self.out_stage.get(a.id)=='hit')
            if a.status==Status.ACTIVE and a.opening_stashed:
                p['stage']='nocking' if a.bow_state=='nocking' else 'ready' if a.bow_state=='ready' else ('pickup' if a.pickup_elapsed else 'empty_bow')
        for b in f['arrows']:b['dead_kind']=getattr(self.arrows[b['id']],'dead_kind','shot')

    def assert_invariants(self):
        super().assert_invariants()
        coordinator=getattr(self,'supply_coordinator',None)
        if coordinator:
            expected={c['arrow']:c['receiver'] for c in coordinator.contracts.values() if c.get('arrow') is not None}
            assert coordinator.reserved==expected, 'No stale delivery reservations'
            for team in self.config['teams']:
                assert sum(self.agents[aid].team==team and job['kind'] in ('relay','relay_fetch') for aid,job in self.jobs.items())<=1
        for a in self.agents.values():
            assert len(a.inventory)<=4
            assert (a.nocked_arrow in a.inventory) if a.bow_state in ('nocking','ready') else a.nocked_arrow is None
            assert len(a.inventory)-(1 if a.nocked_arrow in a.inventory else 0)<=3
        for team,owners in self.role_owners.items():
            assert len(set(owners.values()))==len(owners)
            roles=[a.role for a in self.agents.values() if a.team==team and a.status==Status.ACTIVE]
            assert len(roles)==len(set(roles)), 'Living players must have distinct roles'
        for team in self.role_owners:
            slots=[slot for aid,slot in self.wait_slots.items() if self.agents[aid].team==team]
            assert len(slots)==len(set(slots))

    def summary(self):
        row=super().summary();row['v3_stats']={k:self.counts[k] for k in ['arrow_pass','death_discard','role_change','bow_ready','local_yields','stalled_replans','arrow_edge_releases']}
        coordinator=getattr(self,'supply_coordinator',None)
        row['v4_supply']={k:self.counts[k] for k in ['supply_contract','supply_complete','supply_cancel']}
        row['v4_supply']['cancel_reasons']=dict(Counter(c['reason'] for c in coordinator.closed if c['reason']!='received')) if coordinator else {}
        return row
