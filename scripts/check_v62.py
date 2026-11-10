"""Resource distribution, actual travel, target outcomes and post-revival audit."""
import csv,json,math,re,statistics,sys
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.tactical_entities import positions
from audit_supply import audit


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def main():
    d=json.loads(re.search(r'<script type="application/json" id="replay-data">([\s\S]*?)</script>',(ROOT/'OPEN_SUZHOU.html').read_text())[1]);results=[]
    for case in d['cases']:
        arrows={};starving=[0.,0.];max_starve=[0.,0.];max_starve_after120=[0.,0.];first_high={};far_cover=[];clear_at=None;ordinary_max=0.;after_opening_max=0.
        frames=case['frames'];changes={(e['agent'],round(e['t'],3)) for e in case['events'] if e['kind']=='role_change'}
        for f in frames:
            if f['k']:arrows.clear()
            for bid in f['d']:arrows.pop(bid,None)
            arrows.update({b[0]:b for b in f['a']});assert len(arrows)+sum(p[3] for p in f['p'])==36
            if not f['r'][2] and clear_at is None:clear_at=f['t']
            for team in range(2):
                people=f['p'][team*6:team*6+6]
                upper=[p for p in people if not p[2] and p[1]>10]
                # This catches the old blind spot: stock can be far below the
                # unarmed posts rather than within an arbitrary 3m bubble.
                rear=[b for b in arrows.values() if b[4]==0 and ((b[1]<16)==(team==0)) and (b[1]<=6 if team==0 else b[1]>=26)]
                hungry=len([p for p in upper if p[3]==0])>=2 and len(rear)>=4 and len([p for p in people if not p[2]])>=3
                starving[team]=starving[team]+.05 if hungry else 0.
                max_starve[team]=max(max_starve[team],starving[team])
                if f['t']>=120:max_starve_after120[team]=max(max_starve_after120[team],starving[team])
                for offset,p in enumerate(people):
                    if p[2]:continue
                    aid=d['ids'][team*6+offset];role=d['roles'][p[13]];intent=d['intents'][p[9]]
                    if role=='high_cover' and p[3] and team not in first_high:first_high[team]=f['t']
                    if len(p)>26 and not p[17]:
                        ordinary_max=max(ordinary_max,math.hypot(p[25],p[26]))
                        if f['t']>=12:after_opening_max=max(after_opening_max,math.hypot(p[25],p[26]))
                    if role in ('high_cover','low_cover') and intent=='pickup' and p[10] is not None and f['t']>12 and p[30]!='lockdown':
                        supports=[q for q in people if not q[2] and 'cover' not in d['roles'][q[13]]]
                        home=positions(d['config'],'attack' if team==0 else 'defense',role)[0]
                        if supports and math.dist([p[10],p[11]],home)>1.8:
                            if not any((aid,round(f['t']-x,3)) in changes for x in [0,.025,.05]):far_cover.append((f['t'],aid,p[10:12]))
        # One planning refresh may retain an old intent when support respawns;
        # sustained far retrieval is a failure, not ordinary defensive peeking.
        runs=defaultdict(list)
        for t,aid,goal in far_cover:runs[aid].append(t)
        longest_far=0
        for ts in runs.values():
            span=0;prev=-100
            for t in ts:span=span+.05 if t-prev<=.051 else .05;longest_far=max(longest_far,span);prev=t
        assert longest_far<=.55,(case['seed'],far_cover[:5])
        if case.get('scenario')=='rear_stock':
            assert set(first_high)=={0,1} and max(first_high.values())<=25,first_high
            assert all(p[34]=='score_battle' for f in frames for p in f['p'] if not p[2])
        if case['seed']==1000:
            assert max(max_starve_after120)<=30, 'Upper posts remain unarmed despite rear stock'
        folder=ROOT/'reports'/f"behavior_seed_{case['seed']}";shots=read(folder/'shots.csv');events=case['events']
        assert len(shots)==case['summary']['shots']
        loaded=[e['ammo'] for e in events if e['kind']=='batch_loaded'];revive=[s for s in shots if s['target_kind']=='revive' and s['outcome']!='unresolved']
        attempts_by_live={}
        for s in revive:
            f=next(f for f in reversed(frames) if f['t']<=float(s['release_t'])+.001)
            n=f['r'][2].bit_count();entry=attempts_by_live.setdefault(n,dict(attempts=0,knocks=0));entry['attempts']+=1;entry['knocks']+=s['knockdown']=='True'
        assert ordinary_max<=4.27 # 4.2 * (.9+.15*.75), plus packed rounding
        assert after_opening_max<=3.01
        results.append(dict(seed=case['seed'],scenario=case.get('scenario'),duration_s=case['summary']['duration_s'],shots=len(shots),hits=case['summary']['hits'],passes=sum(e['kind']=='arrow_pass' for e in events),batch_loads=loaded,completed_deliveries=sum(e['kind']=='supply_complete' for e in events),max_upper_starvation_with_rear_stock_s=[round(x,2) for x in max_starve],max_upper_starvation_after120_s=[round(x,2) for x in max_starve_after120],first_high_cover_armed_s=first_high,old_far_pickup_intent_max_s=round(longest_far,3),max_ordinary_speed_after12_m_s=round(after_opening_max,3),revive_clear_s=clear_at,revive_attempts_by_live_points=attempts_by_live,objective_shift=sum(e['kind']=='objective_shift' for e in events),arrow_conservation_verified=True))
    supply=audit(ROOT/'OPEN_SUZHOU.html');assert all(x['quick_repasses']==0 for x in supply)
    report=dict(unit_tests=int(re.search(r'Ran (\d+) tests',(ROOT/'reports/unit_tests.txt').read_text())[1]),episodes=results,supply_symptom_metrics=supply,notes=['Transport quota up to 4 is separate from combat carry preference.','No remaining-disk probability multiplier is used; actual scatter may hit any still-standing disk.','Ordinary movement accelerates and is capped at 3m/s; opening runs and reactive evasion remain faster.','A source-distribution test is a labelled 40-second segment, not an adjudicated full game.'])
    (ROOT/'reports/v62_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
