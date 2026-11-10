"""Longer ground runout, short dead panel rebounds and tactical opening caches."""
from math import atan2,cos,hypot,radians,sin

from .runout_environment import RunoutSkirmishEnvironment
from .varied_policy import VariedRolePolicy
from .policies import Navigator


class ReboundSkirmishEnvironment(RunoutSkirmishEnvironment):
    def _emit(self,kind,**data):
        if kind=='arrow_settled':data['motion_kind']=getattr(self.arrows[data['arrow']],'settling_kind','ground')
        super()._emit(kind,**data)

    def _setup_opening(self):
        super()._setup_opening()
        nav=Navigator(self.config,self.navigation_obstacles)
        self.cache_positions={}
        for i,a in enumerate(self.agents.values()):
            policy=VariedRolePolicy(self.config,nav,a.id,self.seed*101+i+17,self.mirror_y)
            bunker,hold,_=policy._positions({'self':{'team':a.team}})
            direction=1 if a.team=='attack' else -1
            if 'cover' in a.role:
                point=hold
            elif 'flank' in a.role:
                point=(bunker.center[0]-direction*1.45,bunker.center[1]+(-.12 if bunker.center[1]<6 else .12))
            else:
                point=(hold[0]-direction*2.1,hold[1])
            # Small personal placement differences; never inside a panel.
            point=(point[0],point[1]+self.rng.uniform(-.08,.08))
            self.cache_positions[a.id]=point
            a.opening_stashed=False
            a.has_bow=False

    def _drop(self,a):
        goal=self.cache_positions[a.id]
        if not a.center_visited or hypot(a.position[0]-goal[0],a.position[1]-goal[1])>.65 or len(a.inventory)<=1:
            return
        while len(a.inventory)>1:
            bid=a.inventory.pop()
            self._ground(self.arrows[bid],(*goal,0))
            self._emit('stash',agent=a.id,arrow=bid,position=goal)
        a.opening_stashed=True
        if a.has_bow:self._prepare_arrow(a)

    def _release(self,a,action):
        if not a.has_bow or not a.opening_stashed:return
        super()._release(a,action)

    def _update_rule_state(self):
        locked={a.id:not a.shoot_unlocked for a in self.agents.values()}
        super()._update_rule_state()
        for a in self.agents.values():
            if locked[a.id] and a.shoot_unlocked:
                a.has_bow=True
                self._emit('bow_collected',agent=a.id)
                if a.opening_stashed and len(a.inventory)==1:self._prepare_arrow(a)

    def get_observation(self,agent_id=None):
        obs=super().get_observation(agent_id)
        if agent_id is not None:
            a=self.agents[agent_id]
            obs['self'].update(opening_stashed=a.opening_stashed,cache_position=self.cache_positions[a.id])
        return obs

    def _record_frame(self):
        super()._record_frame()
        for p in self.trace[-1]['players']:
            a=self.agents[p['id']]
            p.update(has_bow=a.has_bow,opening_stashed=a.opening_stashed,cache_position=self.cache_positions[a.id])
            if not a.shoot_unlocked and a.center_visited:
                p['stage']='return_bow' if a.opening_stashed else 'caching'
        for b in self.trace[-1]['arrows']:
            if b['state']=='settling':b['settling_kind']=getattr(self.arrows[b['id']],'settling_kind','ground')

    def _start_rebound(self,b,point,velocity,normal,kind,remaining=0):
        # Capture the live flight end once. Everything after this contact is dead.
        super()._ground(b,point)
        vx,vy=velocity[:2];nx,ny=normal
        dot=vx*nx+vy*ny
        rx,ry=vx-2*dot*nx,vy-2*dot*ny
        tangent_x,tangent_y=rx-(rx*nx+ry*ny)*nx,ry-(rx*nx+ry*ny)*ny
        rx,ry=rx-.55*tangent_x,ry-.55*tangent_y
        speed=hypot(rx,ry)
        if speed<.2:return
        c=self.config['panel_rebound']
        retained=speed*self.rng.uniform(*c['retention_range'])
        distance=min(c['max_distance_m'],max(c['min_distance_m'],retained**2/(2*self.rng.uniform(5,7))))
        angle=atan2(ry,rx)+self.rng.uniform(-radians(12),radians(12))
        ux,uy=cos(angle),sin(angle)
        if ux*nx+uy*ny<=0:ux,uy=nx,ny
        # Move just clear of the contacted surface, preventing a t=0 recollision.
        clearance=.12 if kind=='rack' else .045
        origin=(point[0]+nx*clearance,point[1]+ny*clearance,max(0,point[2]))
        b.state='settling';b.position=origin;b.landing_origin=origin
        b.settling_heading=(ux,uy);b.settling_distance=distance
        b.settling_duration=max(.5,min(1.9,2*distance/max(retained,.2)))
        b.settling_elapsed=0;b.settling_curve=self.rng.uniform(-.06,.06)*distance
        b.settling_hops=2;b.settling_height=.07
        b.settling_kind='rebound'
        b.velocity=(retained*ux,retained*uy,0)
        self._emit('panel_rebound',arrow=b.id,surface=kind,position=point,distance=distance,duration=b.settling_duration)
        if remaining>0:self._advance_settling(b,remaining)

    def _finish_flight(self,b,point,kind,velocity,remaining_tick_s):
        if kind=='obstacle':
            candidates=[]
            for o in self.obstacles:
                lo,hi=o.bounds(self.config['physics']['arrow_radius_m'])
                for axis in (0,1):
                    for side,n in ((lo[axis],-1),(hi[axis],1)):
                        normal=(n,0) if axis==0 else (0,n)
                        if velocity[axis]*n<0:candidates.append((abs(point[axis]-side),normal))
            normal=min(candidates,key=lambda x:x[0])[1]
            self._start_rebound(b,point,velocity,normal,'cover',remaining_tick_s)
        else:
            b.settling_kind='ground'
            super()._finish_flight(b,point,kind,velocity,remaining_tick_s)

    def _contact_skirmish_rack(self,b,target,point,rewards):
        team,spot=target
        was_standing=spot>=0 and self.skirmish_racks[team].standing[spot]
        velocity=b.velocity
        # Contact on a target disk uses the existing scoring/absorption rule.
        if was_standing:
            super()._contact_skirmish_rack(b,target,point,rewards)
        else:
            normal=(-1 if velocity[0]>0 else 1,0)
            self._start_rebound(b,point,velocity,normal,'rack')

    def _settling_position(self,b,elapsed):
        x,y,z=super()._settling_position(b,elapsed)
        if getattr(b,'settling_kind','ground')=='rebound':
            fraction=min(1,elapsed/max(b.settling_duration,1e-9))
            z+=b.landing_origin[2]*max(0,1-fraction/.38)**2
        return x,y,z

    def summary(self):
        row=super().summary();row['panel_rebounds']=self.counts['panel_rebound'];row['bows_collected']=self.counts['bow_collected']
        return row
