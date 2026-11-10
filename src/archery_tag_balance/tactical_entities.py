from dataclasses import dataclass
from .entities import Action

ROLES=('high_flank','high_cover','center_1','center_2','low_cover','revive_lane')
ROLE_NAMES=dict(zip(ROLES,('高边','高掩体','中一','中二','矮掩体','复活路')))

@dataclass(frozen=True)
class TacticalAction(Action):
    throw_to: str | None = None
    pickup_id: int | None = None
    quick_shot: bool = False
    token: int = 0

def positions(env_or_config,team,role):
    c=env_or_config.config if hasattr(env_or_config,'config') else env_or_config
    d=1 if team=='attack' else -1
    own=[o for o in c['obstacles'] if o['id'].startswith(team+'_')]
    spec=next(o for o in own if o['id'].endswith('high' if role in ('high_flank','high_cover','center_1') else 'low'))
    x,y=spec['center_xy_m'];depth,width,height=spec['size_xyz_m']
    if role in ('high_cover','low_cover'):
        hold=(x-d*(depth/2+.43),y)
        peek=(hold[0],y+(1 if role=='high_cover' else -1)*(width/2+.43))
    elif role=='high_flank':hold=(x-d*(depth/2+1.5),18.0);peek=(hold[0]+d*.4,18.1)
    elif role=='revive_lane':hold=(7.2 if d==1 else 24.8,2.15);peek=(8.0 if d==1 else 24.0,2.15)
    else:
        depth=5.2 if role=='center_1' else 5.8
        hold=peek=(depth if d==1 else 32-depth,12 if role=='center_1' else 8.2)
    return hold,peek
