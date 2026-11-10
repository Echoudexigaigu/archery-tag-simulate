"""V6.1 team phases, visible bow bearing, rim contact and ordered queues."""
from math import atan2,hypot,pi
from .deliberate_environment import SuzhouEnvironment as V6Environment
from .entities import Status


def signed_angle(a,b):return (a-b+pi)%(2*pi)-pi


class SuzhouEnvironment(V6Environment):
    def _setup_opening(self):
        super()._setup_opening()
        from .match_plan import MatchPlanner
        self.match_planner=MatchPlanner(self)
        for a in self.agents.values():
            a.bow_bearing=0. if a.team=='attack' else pi
            a.turn_effort=0.;a.last_aim_point=None

    def _refresh_supply(self,team):
        from .posted_supply import PostedSupplyCoordinator
        if not isinstance(getattr(self,'supply_coordinator',None),PostedSupplyCoordinator):self.supply_coordinator=PostedSupplyCoordinator(self)
        self.supply_coordinator.refresh(team)

    def _update_rule_state(self):
        super()._update_rule_state()
        if hasattr(self,'match_planner'):self.match_planner.update()

    def _safe_change(self,a):
        if self.jobs.get(a.id,{}).get('kind') in ('relay','relay_fetch'):return False
        return super()._safe_change(a)

    def _on_aim_progress(self,a,action,dt):
        super()._on_aim_progress(a,action,dt)
        a.turn_effort=max(0,a.turn_effort-dt*1.6)
        if action.aim is None:return
        heading=atan2(action.aim[1]-a.position[1],action.aim[0]-a.position[0])
        delta=signed_angle(heading,a.bow_bearing)
        rate=self.config['v61']['bow_turn_rate_rad_s']
        step=max(-rate*dt,min(rate*dt,delta));a.bow_bearing+=step
        a.turn_effort=min(1.5,a.turn_effort+abs(step)*.7)
        a.last_aim_point=action.aim

    def _release(self,a,action):
        if action.aim is None:return
        heading=atan2(action.aim[1]-a.position[1],action.aim[0]-a.position[0])
        if abs(signed_angle(heading,a.bow_bearing))>.10:return
        plan=self.match_planner.plans.get(a.id,{})
        if plan.get('mode')=='lockdown':
            friends=[f for f in self.agents.values() if f.team==a.team and f.status==Status.ACTIVE]
            others=[f for f in friends if f.id!=a.id and f.inventory]
            if not others:return
            # A team cannot dump its cover arrows in the same volley.
            recent=max((f.last_shot_at for f in friends if f.id!=a.id),default=-100)
            if self.t-recent<.75:return
            if plan.get('reserve_agent')==a.id and len(a.inventory)<=1 and len(others)<2:return
        super()._release(a,action)

    def _accuracy_multiplier(self,a):
        # A rushed turn still points in the right direction, with a modest
        # precision cost. There is no visual turn after an unrelated release.
        return super()._accuracy_multiplier(a)*(1+.22*getattr(a,'turn_effort',0))

    def _contacts(self,b,p,q,old_positions,new_positions):
        hits=super()._contacts(b,p,q,old_positions,new_positions)
        result=[]
        for t,priority,kind,target in hits:
            if kind=='skirmish_rack' and target[0]=='revive' and target[1]>=0:
                key,k=target;rack=self.skirmish_racks[key]
                y=p[1]+(q[1]-p[1])*t;z=p[2]+(q[2]-p[2])*t
                effective=self.rack_specs[key]['spot_radii_m'][k]+self.config['v61']['revive_contact_padding_m']
                if hypot(y-rack.spot(k)[1],z-rack.spot(k)[2])>effective:target=(key,-1)
            result.append((t,priority,kind,target))
        return result

    def _layout_queue(self,team):
        wx,wy=self.config['suzhou']['waiting_positions_m'][team]
        queued=list(self.revive_queue[team])
        other=[aid for aid in self.wait_slots if self.agents[aid].team==team and aid not in queued]
        order=queued+other;direction=1 if team=='attack' else -1
        for rank,aid in enumerate(order):
            self.wait_slots[aid]=rank
            goal=(wx+direction*(rank-2.5)*self.config['v3']['waiting_spacing_m'],wy)
            route=self.out_routes.get(aid,[])
            if route and self.out_stage.get(aid) in ('hit','leaving'):route[-1]=goal
            elif self.out_stage.get(aid)=='waiting':self.out_routes[aid]=[goal]

    def _eliminate(self,a,shooter,rewards):
        super()._eliminate(a,shooter,rewards);self._layout_queue(a.team)

    def _contact_skirmish_rack(self,b,target,point,rewards):
        super()._contact_skirmish_rack(b,target,point,rewards)
        if target[0]=='revive':
            for team in self.config['teams']:self._layout_queue(team)

    def get_observation(self,agent_id=None):
        obs=super().get_observation(agent_id)
        if agent_id is not None and hasattr(self,'match_planner'):
            obs['team_plan']=dict(self.match_planner.plans.get(agent_id,{}))
            obs['self']['bow_bearing']=self.agents[agent_id].bow_bearing
            for enemy in obs['enemies']:enemy['bow_bearing']=self.agents[enemy['id']].bow_bearing
            obs['ammo_requested']=agent_id in getattr(self.supply_coordinator,'request_since',{}) if hasattr(self,'supply_coordinator') else False
        return obs

    def _record_frame(self):
        super()._record_frame()
        for p in self.trace[-1]['players']:
            a=self.agents[p['id']]
            p['bow_bearing']=getattr(a,'bow_bearing',0 if a.team=='attack' else pi)
            p['aim_point']=getattr(a,'last_aim_point',None)
            p['team_plan']=dict(self.match_planner.plans.get(a.id,{})) if hasattr(self,'match_planner') else {}
            p['ammo_requested']=a.id in getattr(getattr(self,'supply_coordinator',None),'request_since',{})
