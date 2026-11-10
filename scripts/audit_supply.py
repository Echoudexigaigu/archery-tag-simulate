"""Compare supply failure symptoms in packed replays; no match is rerun."""
import itertools,json,math,re,sys
from pathlib import Path

def audit(path):
    data=json.loads(re.search(r'<script type="application/json" id="replay-data">([\s\S]*?)</script>',Path(path).read_text(encoding='utf-8'))[1])
    rows=[]
    obstacles=[]
    for o in data['config']['obstacles']:
        x,y=o['center_xy_m'];dx,dy,_=o['size_xyz_m'];obstacles.append((x-dx/2-.03,x+dx/2+.03,y-dy/2-.03,y+dy/2+.03))
    def clear(a,b):
        for x0,x1,y0,y1 in obstacles:
            lo,hi=0.,1.
            for p,d,mn,mx in [(a[0],b[0]-a[0],x0,x1),(a[1],b[1]-a[1],y0,y1)]:
                if abs(d)<1e-9:
                    if not mn<=p<=mx:lo=2;break
                else:
                    t0,t1=sorted(((mn-p)/d,(mx-p)/d));lo=max(lo,t0);hi=min(hi,t1)
            if lo<=hi:return False
        return True
    for case in data['cases']:
        arrows={};idle=[0.]*12;max_idle=0.;idle_s=0.;cluster=[0.,0.];max_cluster=0.;cluster_s=0.;samples=0
        for frame in case['frames']:
            if frame['k']:arrows.clear()
            for bid in frame['d']:arrows.pop(bid,None)
            arrows.update({b[0]:b for b in frame['a']})
            if frame['t']<10 or round(frame['t']*20)%5:continue
            samples+=1
            for i,p in enumerate(frame['p']):
                direction=1 if i<6 else -1;intent=data['intents'][p[9]]
                eligible=not p[2] and not p[3] and intent not in ('pickup','gather','supply','pass','revive','revive_snap','escape','wait_delivery') and not p[17]
                nearby=eligible and any(b[4]==0 and ((b[1]<16)==(i<6)) and (b[1]-p[0])*direction<=.3 and math.hypot(b[1]-p[0],b[2]-p[1])<=3 and clear(p[:2],b[1:3]) for b in arrows.values())
                idle[i]=idle[i]+.25 if nearby else 0.
                if nearby:idle_s+=.25;max_idle=max(max_idle,idle[i])
            for team in range(2):
                people=[p for p in frame['p'][team*6:team*6+6] if not p[2]]
                crowded=any(all(math.dist(a[:2],b[:2])<3.5 for a,b in itertools.combinations(group,2)) for group in itertools.combinations(people,3))
                cluster[team]=cluster[team]+.25 if crowded else 0.
                if crowded:cluster_s+=.25;max_cluster=max(max_cluster,cluster[team])
        last={};returns=0;passes=0
        for event in case['events']:
            if event['kind']=='shot':last.pop(event['arrow'],None)
            if event['kind']!='arrow_pass':continue
            passes+=1;old=last.get(event['arrow'])
            if old and event['agent']!=old['agent'] and event['t']-old['t']<6:returns+=1
            last[event['arrow']]=event
        rows.append(dict(seed=case['seed'],duration_s=case['summary']['duration_s'],passes=passes,quick_repasses=returns,unjustified_empty_near_rear_arrow_player_s=round(idle_s,2),longest_unjustified_idle_s=round(max_idle,2),cluster_pairwise_threshold_m=3.5,three_person_cluster_team_s=round(cluster_s,2),longest_three_person_cluster_s=round(max_cluster,2),shots=case['summary']['shots'],hits=case['summary']['hits']))
    return rows

if __name__=='__main__':
    result=audit(sys.argv[1]);print(json.dumps(result,ensure_ascii=False,indent=2))
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
