"""Measured simulation events; rates keep their denominators and missingness."""
from collections import Counter,defaultdict
import csv,json,math
from pathlib import Path


class BehaviorRecords:
    def __init__(self,env):
        self.e=env;self.shots=[];self.by_arrow={};self.players=defaultdict(Counter);self.decisions=[];self.next_sample=0

    def shot(self,a,bid,action,launch):
        key=str(action.aim_key);kind='revive' if key.startswith('rack:revive') else 'scoreboard' if key.startswith('rack:') else 'body'
        row=dict(source='simulation',seed=self.e.seed,shot_id=f'{self.e.seed}:{len(self.shots)+1}',arrow_id=bid,agent=a.id,player_id=a.player_model['player_id'],release_t=self.e.t,target_key=key,target_kind=kind,release_x=a.position[0],release_y=a.position[1],aim_distance=math.hypot(action.aim[0]-a.position[0],action.aim[1]-a.position[1]),aim_required=a.human_aim_s,angle_sigma=launch.get('sigma'),outcome='unresolved',contact_agent='',disk_contact=False,knockdown=False)
        self.shots.append(row);self.by_arrow[bid]=row

    def body(self,a,b,shooter,active):
        row=self.by_arrow.get(b.id)
        if row:row.update(outcome='friendly_block' if a.team==shooter.team else 'body_contact' if active else 'inactive_body_block',contact_agent=a.id)

    def finish(self,b,kind):
        row=self.by_arrow.get(b.id)
        if row and row['outcome']=='unresolved':row['outcome']=kind

    def rack(self,b,key,spot,knocked):
        row=self.by_arrow.get(b.id)
        if row:row.update(outcome='revive_board_contact' if key=='revive' else 'score_board_contact',disk_contact=spot>=0,knockdown=knocked)

    def step(self,old,dt):
        e=self.e
        for aid,a in e.agents.items():
            if old[aid]['active']:
                c=self.players[aid];c['active_s']+=dt;c['crouched_s']+=dt*int(a.crouched);c['empty_bow_s']+=dt*int(a.bow_state=='empty');c['no_arrow_s']+=dt*int(not a.inventory)
                c['distance_m']+=math.dist(old[aid]['position'],a.position)
                own=[o for o in e.obstacles if o.id.startswith(a.team+'_')]
                direction=1 if a.team=='attack' else -1
                protected=any(0<(o.center[0]-a.position[0])*direction<2.0 and abs(o.center[1]-a.position[1])<o.size[1]/2+.15 and (o.size[2]>1 or a.crouched) for o in own)
                c['cover_geometry_s']+=dt*protected
        if e.t+1e-9>=self.next_sample:
            for a in e.agents.values():
                mind=e.policy_intents.get(a.id,{}).get('mind',{})
                if a.status.value=='eliminated':continue
                self.decisions.append(dict(source='simulation',seed=e.seed,t=e.t,agent=a.id,player_id=a.player_model['player_id'],role=a.role,x=a.position[0],y=a.position[1],ammo=len(a.inventory),focus=round(mind.get('focus',0),3),pressure=round(mind.get('pressure',0),3),visible_arrows=mind.get('visible_arrows',0),noticed_arrows=mind.get('noticed_arrows',0),risk_margin=mind.get('risk_margin'),reason=mind.get('reason','opening')))
            self.next_sample=e.t+.25

    def rows(self):
        rows=[]
        for a in self.e.agents.values():
            own=[r for r in self.shots if r['agent']==a.id];body=[r for r in own if r['target_kind']=='body'];resolved=[r for r in body if r['outcome']!='unresolved']
            intended=sum(r['outcome']=='body_contact' and r['contact_agent']==r['target_key'] for r in resolved)
            target=[r for r in own if r['target_kind']=='scoreboard'];resolved_target=[r for r in target if r['outcome']!='unresolved']
            knocks=sum(r['outcome']=='score_board_contact' and r['knockdown'] for r in resolved_target)
            count=lambda kind:sum(e['kind']==kind and e.get('agent')==a.id for e in self.e.events)
            c=self.players[a.id];active=c['active_s']
            rows.append(dict(source='simulation',seed=self.e.seed,agent=a.id,player_id=a.player_model['player_id'],is_demo=a.player_model['is_demo'],home_role=a.home_role,active_s=round(active,3),distance_m=round(c['distance_m'],3),crouched_s=round(c['crouched_s'],3),cover_geometry_s=round(c['cover_geometry_s'],3),cover_fraction=round(c['cover_geometry_s']/active,4) if active else None,no_arrow_s=round(c['no_arrow_s'],3),body_shots=len(body),body_shots_resolved=len(resolved),body_shots_unresolved=len(body)-len(resolved),intended_body_hits=intended,intended_body_hit_rate=round(intended/len(resolved),4) if resolved else None,scoreboard_shots=len(target),scoreboard_shots_resolved=len(resolved_target),scoreboard_knockdowns=knocks,scoreboard_knockdown_rate=round(knocks/len(resolved_target),4) if resolved_target else None,pickups=count('pickup'),passes=count('arrow_pass'),evasion_actions=count('evade_move')))
        return rows

    def export(self,directory):
        path=Path(directory);path.mkdir(parents=True,exist_ok=True)
        for name,rows in [('players.csv',self.rows()),('shots.csv',self.shots),('decisions.csv',self.decisions)]:
            with (path/name).open('w',newline='',encoding='utf-8-sig') as f:
                if rows:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
