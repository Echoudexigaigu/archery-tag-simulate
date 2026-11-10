"""Public manpower, team reports and persistent endgame responsibilities.

No hidden enemy ammunition or future releases enter this plan.
"""
from math import hypot
from .entities import Status
from .tactical_entities import positions


class MatchPlanner:
    def __init__(self,e):
        self.e=e;self.next_at=0.;self.plans={};self.mode={};self.mode_since={};self.last_seen={};self.revive_retired=False

    def update(self,force=False):
        e=self.e
        if not force and e.t<self.next_at:return
        self.next_at=e.t+.35
        for team in e.config['teams']:
            friends=[a for a in e.agents.values() if a.team==team and a.status==Status.ACTIVE]
            enemies=[a for a in e.agents.values() if a.team!=team and a.status==Status.ACTIVE]
            for enemy in enemies:
                if any(e.line_clear((*f.position,e.player_height(f)*.9),(*enemy.position,e.player_height(enemy)*.9)) for f in friends):
                    self.last_seen[(team,enemy.id)]=(e.t,enemy.position)
            known=[(a.id,self.last_seen[(team,a.id)][1]) for a in enemies if (team,a.id) in self.last_seen and e.t-self.last_seen[(team,a.id)][0]<3.]
            mode='lockdown' if len(enemies)==1 and len(friends)>=3 else 'outnumbered' if len(friends)<=2 and len(enemies)>=len(friends)+2 else 'balanced'
            if mode!=self.mode.get(team):
                self.mode[team]=mode;self.mode_since[team]=e.t
                e._emit('team_mode',team=team,mode=mode,own=len(friends),enemy=len(enemies))
            stock=sum(len(a.inventory) for a in friends);armed=[a for a in friends if a.inventory]
            watchers=sorted(friends,key=lambda a:(a.role not in ('high_cover','high_flank'),a.role!='high_cover',a.id))[:min(2,max(1,len(friends)-1))] if mode=='lockdown' else []
            watch_ids={a.id for a in watchers}
            # Leave at least one armed player covering whenever a finisher fires.
            reserve=next((a.id for a in watchers if a.inventory),armed[0].id if armed else None)
            for a in friends:
                hold,peek=positions(e,team,a.role);d=1 if team=='attack' else -1
                task='post';goal=None
                if mode=='lockdown':
                    task='watch' if a.id in watch_ids else 'finish'
                    # Every live role has a distinct lane at the legal front
                    # line. Advance remains subject to defence and resource jobs.
                    goal=(10.35 if d==1 else 21.65,peek[1])
                self.plans[a.id]=dict(mode=mode,task=task,goal=goal,own_alive=len(friends),enemy_alive=len(enemies),team_arrows=stock,armed_count=len(armed),reserve_agent=reserve,reported_enemy=known[0] if len(enemies)==1 and known else None,since=self.mode_since[team])
        self.plans={aid:p for aid,p in self.plans.items() if e.agents[aid].status==Status.ACTIVE}
        available=any(e.skirmish_racks['revive'].standing)
        if not available and not self.revive_retired:
            self.revive_retired=True;e._emit('objective_shift',objective='score_battle')
        for aid,plan in self.plans.items():
            plan['objective']='revival_live' if available else 'score_battle'
            if not available and e.agents[aid].role=='revive_lane' and plan.get('goal'):
                plan['goal']=(plan['goal'][0],6.7)

