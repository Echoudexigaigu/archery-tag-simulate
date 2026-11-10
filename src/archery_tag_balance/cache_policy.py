"""Deposit spare arrows along the return route before collecting the bow."""
from math import hypot
from .entities import Action
from .varied_policy import VariedRolePolicy


class CacheRolePolicy(VariedRolePolicy):
    def _act(self,obs):
        a,now=obs['self'],obs['time']
        if a['status']=='eliminated':return super()._act(obs)
        if not a['shoot_unlocked']:
            if not a['center_visited'] or (not a['opening_stashed'] and a['ammo']<3):
                return super()._act(obs)
            if not a['opening_stashed']:
                goal=a['cache_position']
                if hypot(a['position'][0]-goal[0],a['position'][1]-goal[1])<=.6:return Action(interaction='drop',crouch=True)
            else:goal=a['spawn']
            return Action(move=self.move_to(a['position'],goal,a['team'],now))
        if not a['opening_stashed']:
            goal=a['cache_position']
            if hypot(a['position'][0]-goal[0],a['position'][1]-goal[1])<=.6:return Action(interaction='drop',crouch=True)
            return Action(move=self.move_to(a['position'],goal,a['team'],now))
        return super()._act(obs)
