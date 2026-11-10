"""Visible tasks for a rear collector and a post-revival score battle."""
from dataclasses import replace
from math import hypot
from .endgame_policy import SuzhouPolicy as V61Policy
from .deliberate_policy import SuzhouPolicy as ShotPolicy
from .tactical_entities import TacticalAction,positions
from .entities import Action
from .geometry import segment_box


class SuzhouPolicy(V61Policy):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.friend_positions=[];self.sidestep_goal=None;self.sidestep_until=0.

    def _act(self,obs):
        self.friend_positions=[tuple(f['position']) for f in obs.get('team_roster',[])]
        return super()._act(obs)

    def move_to(self,position,goal,team,now):
        # Collision uses the physical .25m radius, navigation a .27m buffer.
        # A legal dodge/yield can end inside that 2cm buffer. Such a start
        # cannot see ANY waypoint under the stricter test; step out of the
        # buffer with a physically legal short move before normal planning.
        if not self.nav.clear(position,position):
            options=[];lo,hi=self.config['teams'][team]['move_x_bounds_m']
            for obstacle in self.nav.obstacles:
                lower,upper=obstacle.bounds(self.nav.radius)
                if lower[0]<=position[0]<=upper[0] and lower[1]<=position[1]<=upper[1]:
                    for p in [(lower[0]-.04,position[1]),(upper[0]+.04,position[1]),(position[0],lower[1]-.04),(position[0],upper[1]+.04)]:
                        if not lo<=p[0]<=hi or not .25<=p[1]<=19.75:continue
                        if any(segment_box((*position,.5),(*p,.5),*o.bounds(.25)) is not None for o in self.nav.obstacles):continue
                        options.append((hypot(p[0]-position[0],p[1]-position[1]),p))
            if options:
                _,p=min(options);dx,dy=p[0]-position[0],p[1]-position[1];n=max(.08,hypot(dx,dy));return dx/n*.5,dy/n*.5
        desired=super().move_to(position,goal,team,now)
        # Use a persistent side passage around a standing teammate. Flipping
        # left/right every tick was a source of mutual blocking and jitter.
        if self.sidestep_goal and now<self.sidestep_until:
            if hypot(position[0]-self.sidestep_goal[0],position[1]-self.sidestep_goal[1])>.15:
                dx,dy=self.sidestep_goal[0]-position[0],self.sidestep_goal[1]-position[1];n=max(.01,hypot(dx,dy));return dx/n,dy/n
            self.sidestep_goal=None
        norm=hypot(*desired)
        if norm>.1:
            ux,uy=desired[0]/norm,desired[1]/norm
            blocked=any(.0<(p[0]-position[0])*ux+(p[1]-position[1])*uy<1.2 and abs((p[0]-position[0])*uy-(p[1]-position[1])*ux)<.54 for p in self.friend_positions)
            if blocked:
                signs=[1,-1] if self.index%2 else [-1,1]
                for sign in signs:
                    detour=(position[0]-uy*sign*.85+ux*.2,position[1]+ux*sign*.85+uy*.2)
                    lo,hi=self.config['teams'][team]['move_x_bounds_m']
                    if not lo<=detour[0]<=hi or not .3<detour[1]<19.7 or not self.nav.clear(position,detour):continue
                    if any(hypot(detour[0]-p[0],detour[1]-p[1])<.65 for p in self.friend_positions):continue
                    self.sidestep_goal=detour;self.sidestep_until=now+.7
                    dx,dy=detour[0]-position[0],detour[1]-position[1];n=hypot(dx,dy);return dx/n,dy/n
        return desired

    def _positions(self,obs):
        bunker,hold,peek=super()._positions(obs)
        rack=next((r for r in obs.get('racks',[]) if r['team']=='revive'),None)
        if rack and not any(rack['standing']) and obs['self']['role']=='revive_lane':
            hold=peek=(6.8 if obs['self']['team']=='attack' else 25.2,6.7)
        return bunker,hold,peek

    def _collect(self,obs,job):
        a=obs['self'];bid=job.get('arrow');b=next((b for b in obs.get('team_ground_arrows',[]) if b['id']==bid),None)
        if b is None:b=next((b for b in obs.get('ground_arrows',[]) if b['id']==bid),None)
        # Reach with the hand as soon as the actual arrow is in range, rather
        # than spending seconds trying to stand on an exact millimetre goal.
        if b and hypot(b['position'][0]-a['position'][0],b['position'][1]-a['position'][1])<=.66:
            self._set_intent('batch_collect' if job.get('kind')=='batch_collect' else 'pickup',job.get('approach'),bid)
            return self._evading_action(obs,TacticalAction(interaction='pickup',pickup_id=bid,crouch=True))
        action=super()._collect(obs,job)
        if job.get('kind')=='batch_collect':self.intent['kind']='batch_collect'
        return action

    def _logistics(self,obs):
        a=obs['self'];job=obs.get('job',{});kind=job.get('kind');now=obs['time']
        if kind=='batch_collect':
            if a['ammo']==3 and a['bow_state']=='empty':self._set_intent('nock');return TacticalAction(interaction='nock')
            return self._collect(obs,job)
        if kind=='batch_deliver':
            if a['ammo']<=1:return None
            where=job['throw_from'];self._set_intent('batch_deliver',where)
            if hypot(a['position'][0]-where[0],a['position'][1]-where[1])>.16:return self._go(obs,where,'batch_deliver')
            self._set_intent('pass',job['goal'])
            return TacticalAction(interaction='throw',throw_to=job['receiver']) if now>=max(a['throw_ready_at'],a['hands_busy_until']) else Action()
        if kind=='batch_pause':self._set_intent('batch_pause');return self._evading_action(obs,Action())
        if kind=='batch_stash':return self._stash(obs,job['goal'])
        return super()._logistics(obs)

    def _stash(self,obs,goal):
        a=obs['self'];self._set_intent('batch_stash',goal)
        if hypot(a['position'][0]-goal[0],a['position'][1]-goal[1])>.25:return self._go(obs,goal,'batch_stash')
        return TacticalAction(interaction='drop')

    def _role_action(self,obs):
        a=obs['self']
        if a['status']=='active' and a['opening_stashed'] and a['ammo']>a.get('carry_preference',1) and not obs.get('job',{}).get('kind','').startswith('batch_'):
            goal=(3.5 if a['team']=='attack' else 28.5,self._positions(obs)[1][1])
            return self._stash(obs,goal)
        return super()._role_action(obs)

    def _targets(self,obs):
        revive=next((r for r in obs.get('racks',[]) if r['team']=='revive'),None)
        if revive and not any(revive['standing']):
            # No further revival exists: high-side crossfire no longer singles
            # out the old lane, and former lane players work the score area.
            view=obs
            plan=obs.get('team_plan',{})
            if (plan.get('mode')=='lockdown' and plan.get('task')=='finish') or (plan.get('own_alive')==1 and self.lone_choice=='finish'):view=dict(obs,enemies=[])
            return ShotPolicy._targets(self,view)
        return super()._targets(obs)
