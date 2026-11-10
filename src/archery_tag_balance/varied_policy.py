"""Natural follow-through and coordinated recovery within the team's half."""
from math import hypot

from .entities import Action
from .six_role_policy import SixRolePolicy


class VariedRolePolicy(SixRolePolicy):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.follow_until = 0.0
        self.follow_move = (0.0,0.0)
        self.supply_goal_id = None
        self.search_goal, self.next_search = None, 0.0

    def __call__(self,obs):
        # Teammates communicate their positions as well as arrow sightings.
        # This avoids walking into a friend hidden just behind the panel.
        if 'team_roster' in obs:
            obs = {**obs,'teammates':obs['team_roster']}
        return super().__call__(obs)

    def move_to(self,position,goal,team,now):
        """Follow visible waypoints; do not cut a corner just by being near it."""
        def steer(point):
            dx,dy=point[0]-position[0],point[1]-position[1]
            norm=hypot(dx,dy)
            if norm<0.025:return (0.0,0.0)
            denominator=max(norm,self.config['physics']['move_speed_m_s']*self.config['policy']['decision_interval_s'])
            return dx/denominator,dy/denominator
        if self.nav.clear(position,goal):
            self.goal,self.route=goal,[goal]
            return steer(goal)
        if self.goal is None or hypot(goal[0]-self.goal[0],goal[1]-self.goal[1])>0.25 or not self.route or now>=self.next_replan or not self.nav.clear(position,self.route[0]):
            self.route=self.nav.path(position,goal,team)
            self.goal,self.next_replan=goal,now+1.0
            if self.route and not self.nav.clear(position,self.route[0]):
                # A* starts at a nearby grid center. Reach a visible grid center
                # first when our actual off-grid point cannot see its next edge.
                anchors=sorted(self.nav.free[team],key=lambda node:hypot(self.nav.point(node)[0]-position[0],self.nav.point(node)[1]-position[1]))
                for node in anchors:
                    point=self.nav.point(node)
                    if self.nav.clear(position,point):
                        self.route=[point]+self.nav.path(point,goal,team)
                        break
        while len(self.route)>1 and hypot(self.route[0][0]-position[0],self.route[0][1]-position[1])<0.25 and self.nav.clear(position,self.route[1]):
            self.route.pop(0)
        if self.route and self.nav.clear(position,self.route[0]):
            return steer(self.route[0])
        return (0.0,0.0)

    def _shot_finished(self,obs):
        super()._shot_finished(obs)
        a,now=obs['self'],obs['time']
        duration=self.rng.uniform(0.65,1.05)
        self.follow_until=now+duration
        direction=1 if a['team']=='attack' else -1
        habit=a['follow_through']
        if habit=='sidestep':
            delta=(self.rng.uniform(-0.05,0.05),self.rng.choice((-1,1))*self.rng.uniform(0.25,0.45))
        elif habit=='withdraw':
            delta=(-direction*self.rng.uniform(0.25,0.42),self.rng.uniform(-0.15,0.15))
        elif a['aim_style']=='deliberate' and self.rng.random()<0.55:
            delta=(0.0,0.0)  # Some people watch the result before moving on.
        else:
            delta=(direction*self.rng.uniform(-0.06,0.16),self.rng.uniform(-0.22,0.22))
        scale=self.config['physics']['move_speed_m_s']*duration
        self.follow_move=delta[0]/scale,delta[1]/scale
        self.diagnostics['follow_'+habit]+=1

    def _follow_through(self,obs):
        if obs['time']+1e-9>=self.follow_until:
            return None
        x,y=obs['self']['position']
        dx,dy=self.follow_move
        step=self.config['physics']['move_speed_m_s']*self.config['policy']['decision_interval_s']
        goal=x+dx*step,y+dy*step
        lo,hi=self.config['teams'][obs['self']['team']]['move_x_bounds_m']
        if not lo<=goal[0]<=hi or not 0.3<=goal[1]<=self.config['field']['width_m']-0.3 or not self.nav.clear((x,y),goal):
            return Action()
        return Action(move=self.follow_move)

    def _resupply(self,obs,bunker):
        a,now,c=obs['self'],obs['time'],self.config
        assignment=obs.get('supply_assignment')
        if assignment is not None:
            bid=assignment['id']
            if bid!=self.supply_goal_id:
                self.supply_goal_id=bid
                self.goal=None
                self.next_replan=0
                self.diagnostics['reported_arrow_routes']+=1
            goal=tuple(assignment['position'][:2])
            if hypot(goal[0]-a['position'][0],goal[1]-a['position'][1])<c['physics']['pickup_radius_m']-0.05:
                return Action(interaction='pickup',crouch=True)
            lo,hi=c['teams'][a['team']]['move_x_bounds_m']
            goal=max(lo,min(hi,goal[0])),max(0.3,min(c['field']['width_m']-0.3,goal[1]))
            return Action(move=self.move_to(a['position'],goal,a['team'],now))
        self.supply_goal_id=None
        _,hold,peek=self._positions(obs)
        if 'cover' in self.role:
            # Survey around the panel rather than running repeatedly to an
            # empty depot. A teammate can now report arrows on another lane.
            if now>=self.resupply_scan_next:
                self.resupply_scan_until=now+1.5
                self.resupply_scan_next=now+self.rng.uniform(3.0,5.0)
            scanning=now<self.resupply_scan_until
            return Action(move=self.move_to(a['position'],peek if scanning else hold,a['team'],now),crouch=not scanning)
        if now>=self.next_search or self.search_goal is None:
            if obs.get('team_ground_arrows'):
                # Known arrows already have collectors. Maintain space while
                # waiting instead of sending the whole team to the same arrow.
                self.search_goal=(peek[0]+self.rng.uniform(-0.3,0.3),peek[1]+self.rng.uniform(-0.35,0.35))
            else:
                # Search different viewing angles; no hidden ground coordinates.
                depth=self.rng.choice((4.0,6.5,9.3)) if 'center' in self.role else self.rng.choice((3.5,5.5,7.5))
                x=depth if a['team']=='attack' else c['field']['length_m']-depth
                y=max(0.6,min(c['field']['width_m']-0.6,a['spawn'][1]+self.rng.uniform(-1.0,1.0)))
                self.search_goal=(x,y)
                self.diagnostics['search_sweeps']+=1
            self.next_search=now+self.rng.uniform(3.5,5.5)
        lo,hi=c['teams'][a['team']]['move_x_bounds_m']
        goal=max(lo,min(hi,self.search_goal[0])),max(0.3,min(c['field']['width_m']-0.3,self.search_goal[1]))
        return Action(move=self.move_to(a['position'],goal,a['team'],now))
