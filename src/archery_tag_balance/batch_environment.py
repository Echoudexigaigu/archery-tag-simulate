"""V6.2: bounded transport, ordinary acceleration, and board-specific precision."""
from dataclasses import replace
from math import hypot,atan2,sqrt,cos,sin,radians
from .endgame_environment import SuzhouEnvironment as V61Environment
from .entities import Status
from .geometry import ballistic_velocity
from .varied_environment import landing_time


class SuzhouEnvironment(V61Environment):
    def _setup_opening(self):
        super()._setup_opening()
        self.motion_blocks={};self.blocked_since={}
        for a in self.agents.values():a.pickup_recover_until=0.

    def _refresh_supply(self,team):
        from .batch_supply import BatchSupplyCoordinator
        if not isinstance(getattr(self,'supply_coordinator',None),BatchSupplyCoordinator):self.supply_coordinator=BatchSupplyCoordinator(self)
        self.supply_coordinator.refresh(team)

    def _safe_change(self,a):
        if self.jobs.get(a.id,{}).get('kind','').startswith('batch_'):return False
        return super()._safe_change(a)

    def _picked_up(self,a,b):
        super()._picked_up(a,b)
        if a.opening_stashed:a.pickup_recover_until=self.t+.12

    def _pickup_progress_allowed(self,a):
        if not a.opening_stashed:return super()._pickup_progress_allowed(a)
        return hypot(*a.velocity)<=.8 and any(b.state=='ground' and self._pickup_allowed(a,b) and hypot(b.position[0]-a.position[0],b.position[1]-a.position[1])<=self.config['physics']['pickup_radius_m'] for b in self.arrows.values())

    def _movement_speed(self,a):
        speed=super()._movement_speed(a)
        action=self.current_actions.get(a.id) if hasattr(self,'current_actions') else None
        evading=bool(action and action.evasion_kind) or self.t<a.evasion_until
        if a.opening_stashed and not evading:speed=min(speed,self.config['v62']['ordinary_move_speed_m_s'])
        return speed

    def step(self,actions,observe=True):
        adjusted={};dt=self.config['time']['dt_s']
        for aid,action in actions.items():
            a=self.agents[aid]
            if not a.opening_stashed or a.status!=Status.ACTIVE or action.evasion_kind:
                adjusted[aid]=action;continue
            # Pickup itself is instant; rising and reversing direction are not.
            if self.t<getattr(a,'pickup_recover_until',0) and action.interaction!='pickup':
                adjusted[aid]=replace(action,move=(0,0));continue
            speed=max(.1,self._movement_speed(a));n=max(1.,hypot(*action.move));target=tuple(v/n*speed for v in action.move)
            delta=tuple(target[i]-a.velocity[i] for i in range(2));change=hypot(*delta)
            cap=self.config['v62']['ordinary_acceleration_m_s2']*dt;factor=min(1,cap/max(change,1e-9))
            velocity=tuple(a.velocity[i]+delta[i]*factor for i in range(2))
            point=tuple(a.position[i]+velocity[i]*dt for i in range(2))
            if not self.valid_move(a,a.position,point):velocity=target if self.valid_move(a,a.position,tuple(a.position[i]+target[i]*dt for i in range(2))) else (0,0)
            adjusted[aid]=replace(action,move=tuple(v/speed for v in velocity))
        return super().step(adjusted,observe)

    def _resolve_proposals(self,old,proposals,actions,dt):
        active=[a for a in self.agents.values() if a.status==Status.ACTIVE]
        result=dict(old);accepted=set()
        def priority(a):
            act=actions.get(a.id);job=self.jobs.get(a.id,{}).get('kind','')
            return (not bool(act and act.evasion_kind),not job.startswith('batch_'),a.id)
        for a in sorted(active,key=priority):
            p=old[a.id];q=proposals[a.id];dx,dy=q[0]-p[0],q[1]-p[1]
            if hypot(dx,dy)<1e-9:accepted.add(a.id);continue
            others=[b for b in active if b.id!=a.id]
            clear=lambda candidate:all(self._separation(p,candidate,old[b.id],result[b.id])>=.505 for b in others)
            if clear(q):result[a.id]=q
            else:
                candidates=[];sign=1 if int(a.id.rsplit('_',1)[1])%2 else -1
                for degrees in (sign*35,-sign*35,sign*65,-sign*65,sign*90,-sign*90):
                    angle=radians(degrees);candidate=(p[0]+dx*cos(angle)-dy*sin(angle),p[1]+dx*sin(angle)+dy*cos(angle))
                    if self.valid_move(a,p,candidate) and clear(candidate):candidates.append((dx*(candidate[0]-p[0])+dy*(candidate[1]-p[1]),candidate))
                if candidates:result[a.id]=max(candidates,key=lambda row:row[0])[1];self.counts['local_yields']+=1
            accepted.add(a.id)
        # The core still performs continuous swept separation for every pair.
        return result

    def _throw_from_agent(self,a,receiver):
        job=self.jobs.get(a.id,{})
        if job.get('kind')!='batch_deliver':return super()._throw_from_agent(a,receiver)
        if len(a.inventory)<=1 or self.t<max(a.throw_ready_at,a.hands_busy_until):return
        bid=job.get('arrow_to_throw');friend=self.agents.get(receiver)
        if bid not in a.inventory or bid==a.nocked_arrow or friend is None or friend.status!=Status.ACTIVE:return
        goal=self.supply_coordinator.transfer_goal(a,receiver)
        if hypot(goal[0]-a.position[0],goal[1]-a.position[1])>self.config['v3']['throw_range_m'] or not self.supply_coordinator.clear_throw(a.position,goal):return
        a.inventory.remove(bid);self._start_toss(self.arrows[bid],a.position,goal,a.id)
        if self.record:self.events[-1]['receiver']=receiver
        self.supply_coordinator.dispatched(a,bid,receiver);self.arrows[bid].pass_recipient=receiver
        a.throw_ready_at=self.t+.65;a.hands_busy_until=self.t+.25

    def _launch_velocity(self,a,origin,target):
        if not str(a.aim_key).startswith('rack:'):return super()._launch_velocity(a,origin,target)
        p=self.config['physics'];skill=a.player_model['skills']['target_accuracy'];h=a.human_profile
        nominal=h['muzzle_speed_fps']*.3048;draw=nominal*max(.965,min(1.035,self.rng.gauss(1,.014)))
        estimate=1+max(-.025,min(.025,self.rng.gauss(0,.004+.006*(1-skill))))
        perceived=(origin[0]+(target[0]-origin[0])*estimate,origin[1]+(target[1]-origin[1])*estimate,target[2])
        v=ballistic_velocity(origin,perceived,draw,p['gravity_m_s2'],p['linear_drag_s_inv'],p['arrow_max_flight_s'])
        if v is None:return None
        # Typical demo rating .75 no longer means laser-precise tiny disks.
        # Elite ratings remain substantially tighter. Actual geometry counts
        # ANY live disk struck, so an adjacent accidental hit is still valid.
        sigma=(.0055+.014*(1-skill))*self._accuracy_multiplier(a)*(1+.2*(1-a.stamina))
        yaw_error=max(-2.8*sigma,min(2.8*sigma,self.rng.gauss(0,sigma)))
        pitch_error=max(-2.8*sigma,min(2.8*sigma,self.rng.gauss(0,.9*sigma)))
        yaw=atan2(v[1],v[0])+yaw_error;pitch=atan2(v[2],hypot(*v[:2]))+pitch_error
        speed=draw*max(.986,min(1.014,self.rng.gauss(1,.004+.003*(1-skill))))
        result=(speed*cos(pitch)*cos(yaw),speed*cos(pitch)*sin(yaw),speed*sin(pitch))
        self.last_launch[a.id]=dict(sigma=sigma,speed=speed,speed_fps=speed/.3048,range_estimate=estimate,poor_release=False,aim_required=a.human_aim_s,planned_flight_s=landing_time(origin,result,p['gravity_m_s2'],p['linear_drag_s_inv'],p['arrow_max_flight_s']),aim_style=h['aim_style'],steady_aim_s=a.steady_aim_s,aim_height_m=target[2],target_band='target',yaw_error_rad=yaw_error,pitch_error_rad=pitch_error)
        return result

    def _record_frame(self):
        super()._record_frame()
        for p in self.trace[-1]['players']:
            job=self.jobs.get(p['id'],{})
            p['transport_quota']=job.get('quota',0) if job.get('kind')=='batch_collect' else 0
