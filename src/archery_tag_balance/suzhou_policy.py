"""Observation-based baseline policy for the independent Suzhou ruleset."""
from math import hypot,sin
from .entities import Action
from .varied_policy import VariedRolePolicy


class SuzhouPolicy(VariedRolePolicy):
    def _positions(self,obs):
        a=obs['self'];team=a['team'];d=1 if team=='attack' else -1
        w=self.config['field']['width_m'];length=self.config['field']['length_m']
        own=[o for o in self.nav.obstacles if o.id.startswith(team+'_')]
        high=next(o for o in own if o.id.endswith('high'))
        low=next(o for o in own if o.id.endswith('low'))
        cover=high if self.index<3 else low
        if 'cover' in self.role:
            hold=(cover.center[0]-d*(cover.size[0]/2+.42),cover.center[1])
            side=1 if cover.center[1]>w/2 else -1
            peek=(hold[0],cover.center[1]+side*(cover.size[1]/2+.5))
        elif 'flank' in self.role:
            side=1 if cover.center[1]>w/2 else -1
            hold=(cover.center[0]-d*1.7,cover.center[1]+side*2.8)
            peek=(cover.center[0]-d*.5,hold[1]+.22*sin(obs['time']*.3+self.index))
        else:
            localy=8.0 if self.index==2 else 12.0
            y=w-localy if d==1 else localy
            if self.mirror_y:y=w-y
            x=11.6 if d==1 else length-11.6
            hold=peek=(x,y+.25*sin(obs['time']*.22+self.index))
        return cover,hold,peek

    def _targets(self,obs):
        # The shared revival board is never an ordinary opportunistic target.
        return super()._targets({**obs,'racks':[r for r in obs['racks'] if r['team']!='revive']})

    def _act(self,obs):
        a=obs['self'];team=a['team'];now=obs['time'];pos=a['position']
        if a['status']=='eliminated':return Action()
        self._remember(obs)
        if a['last_shot_at']>self.seen_shot:
            self._shot_finished(obs)
            self.seen_shot=a['last_shot_at']
        cover,hold,peek=self._positions(obs)
        if not a['opening_received']:
            goal=obs['opening_pile']
            if hypot(goal[0]-pos[0],goal[1]-pos[1])<.62:
                return self._evading_action(obs,Action(interaction='pickup',crouch=True))
            return self._evading_action(obs,Action(move=self.move_to(pos,goal,team,now)))
        if not a['ammo']:
            return self._evading_action(obs,self._resupply(obs,cover))
        if a['reload_left']>0:
            return self._evading_action(obs,Action(move=self.move_to(pos,hold,team,now),crouch='cover' in self.role and cover.size[2]<1.5))
        if obs.get('revive_runner')==a['id'] and obs.get('revive_queue'):
            goal=tuple(self.config['suzhou']['revive_pads'][team])
            if self.mirror_y:goal=(goal[0],self.config['field']['width_m']-goal[1])
            if not a['on_revive_pad']:
                return self._evading_action(obs,Action(move=self.move_to(pos,goal,team,now)))
            rack=next(r for r in obs['racks'] if r['team']=='revive')
            for k in [4,0,1,2,3]:
                if rack['standing'][k]:
                    key=f'rack:revive:{k}';point=rack['spots'][k]
                    if self._clear_arc(obs,point,key):
                        return self._evading_action(obs,Action(aim=point,aim_key=key,interaction='shoot'))
            return Action()
        follow=self._follow_through(obs)
        if follow is not None:return self._evading_action(obs,follow)
        if 'cover' in self.role:
            if self.next_peek is None:self.next_peek=now+self.rng.uniform(.5,1.8)
            if self.phase=='hide':
                if now<self.next_peek or hypot(pos[0]-hold[0],pos[1]-hold[1])>.2:
                    return self._evading_action(obs,Action(move=self.move_to(pos,hold,team,now),crouch=cover.size[2]<1.5))
                self.phase='peek';self.peek_until=now+a['aim_required']+self.rng.uniform(1.0,2.0)
            if now>=self.peek_until:
                self.phase='hide';self.next_peek=now+self.rng.uniform(.9,2.2)
                return self._evading_action(obs,Action(move=self.move_to(pos,hold,team,now),crouch=cover.size[2]<1.5))
        if hypot(peek[0]-pos[0],peek[1]-pos[1])>.25:
            return self._evading_action(obs,Action(move=self.move_to(pos,peek,team,now)))
        target=self._targets(obs)
        if target is None:return self._evading_action(obs,Action())
        aim=self._aim(obs,target)
        if not self._clear_arc(obs,aim,target[0]):
            self.target_key,self.aim_cache=None,None
            return self._evading_action(obs,Action())
        # A normal follow-through does not force everyone to jump backwards.
        return self._evading_action(obs,Action(aim=aim,aim_key=target[0],interaction='shoot'))
