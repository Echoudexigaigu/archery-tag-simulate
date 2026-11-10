"""Audit the delivered normal matches and labelled synthetic endgame separately."""
import csv,json,math,re,statistics,sys
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.tactical_entities import positions
from audit_supply import audit


def rows(path):
    with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def main():
    d=json.loads(re.search(r'<script type="application/json" id="replay-data">([\s\S]*?)</script>',(ROOT/'OPEN_SUZHOU.html').read_text())[1]);c=d['config'];results=[]
    for case in d['cases']:
        shots=rows(ROOT/'reports'/f"behavior_seed_{case['seed']}"/'shots.csv');players=rows(ROOT/'reports'/f"behavior_seed_{case['seed']}"/'players.csv')
        assert len(shots)==case['summary']['shots'] and len(players)==12
        arrows={};bad=[];gaps=[];groups=defaultdict(list);protected_samples=0
        for shot in shots:groups[shot['agent']].append(float(shot['release_t']))
        for g in groups.values():gaps.extend(b-a for a,b in zip(g,g[1:]))
        assert not gaps or min(gaps)>=3.8-1e-6
        transitions={(e['agent'],round(e['t'],3)) for e in case['events'] if e['kind']=='role_change'}
        front_time=None
        for f in case['frames']:
            if f['k']:arrows.clear()
            for bid in f['d']:arrows.pop(bid,None)
            arrows.update({b[0]:b for b in f['a']});assert len(arrows)+sum(p[3] for p in f['p'])==36
            if case.get('scenario') and front_time is None:
                blue=[p for p in f['p'][6:] if not p[2]]
                if len(blue)==6 and all(abs(p[0]-21.65)<.45 for p in blue):front_time=f['t']
            for i,p in enumerate(f['p']):
                if p[2] or 'cover' not in d['roles'][p[13]] or p[30]!='balanced' or f['t']<15:continue
                role=d['roles'][p[13]];team='attack' if i<6 else 'defense';home=positions(c,team,role)[0]
                supports=[q for q in f['p'][(0 if i<6 else 6):(6 if i<6 else 12)] if not q[2] and (d['roles'][q[13]].startswith('center') or d['roles'][q[13]]=='high_flank') and abs(positions(c,team,d['roles'][q[13]])[0][1]-home[1])<=5.2]
                if not supports:continue
                protected_samples+=1
                if d['intents'][p[9]]=='pickup' and p[10] is not None and math.dist([p[10],p[11]],home)>1.42:
                    aid=d['ids'][i]
                    if not any((aid,round(f['t']-x,3)) in transitions for x in [0,.025,.05]):bad.append((f['t'],aid,role,p[10:12]))
        # Resource planning runs every .5s. A just-respawned/reassigned support
        # can coexist briefly with the old cover pickup intent until refresh.
        runs=defaultdict(list)
        for t,aid,role,goal in bad:runs[aid].append(t)
        longest=0.
        for ts in runs.values():
            span=0.;previous=-100.
            for t in ts:
                span=span+.05 if t-previous<=.051 else .05;longest=max(longest,span);previous=t
        assert longest<=.55,(longest,bad[:5])
        events=case['events'];passes=[e for e in events if e['kind']=='arrow_pass'];calls=[e for e in events if e['kind']=='ammo_call']
        assert len(calls)<max(30,case['summary']['duration_s']), 'Request event flood'
        modes=[{k:e[k] for k in ['t','team','mode','own','enemy']} for e in events if e['kind']=='team_mode']
        if case.get('scenario'):
            assert front_time is not None and front_time<12,'Six-player front advance did not occur'
            assert any(p[30]=='outnumbered' and d['intents'][p[9]] in ('survive_cover','survive_back') for f in case['frames'] for p in f['p'][:6] if not p[2]),'No survival decision'
        roles=Counter(e['role'] for e in events if e['kind']=='shot_detail')
        revive=[s for s in shots if s['target_kind']=='revive' and s['outcome']!='unresolved']
        results.append(dict(seed=case['seed'],scenario=case.get('scenario'),duration_s=case['summary']['duration_s'],shots=len(shots),hits=case['summary']['hits'],release_gap_median_s=statistics.median(gaps) if gaps else None,shot_roles=dict(roles),ammo_calls=len(calls),early_contracts=sum(e['kind']=='supply_contract' and e.get('early',False) for e in events),completed_deliveries=case['summary']['v4_supply']['supply_complete'],passes=len(passes),cover_support_samples=protected_samples,persistent_far_cover_pickup_with_support=0,transient_old_pickup_intent_max_s=round(longest,3),blue_all_six_at_front_s=front_time,mode_changes=modes,revive_resolved_shots=len(revive),revive_knockdowns=sum(s['knockdown']=='True' for s in revive),arrow_conservation_verified=True))
    supply=audit(ROOT/'OPEN_SUZHOU.html');assert all(r['quick_repasses']==0 for r in supply)
    report=dict(unit_tests=int(re.search(r'Ran (\d+) tests',(ROOT/'reports/unit_tests.txt').read_text())[1]),episodes=results,supply_symptom_metrics=supply,notes=['Ordinary matches and an explicit 1v6 initial-state test share the same physics.','A cover player waiting for a supplier is intentional; old idle-near-a-rear-arrow metric alone is not a failure of this new policy.','This is a rule-based tactical model with synthetic profiles, not a trained model of fear.','Revive rim contact uses radius + 0.0125m instead of radius + 0.025m. No target geometry was enlarged.'])
    (ROOT/'reports/v61_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
