"""Audits release cadence, local recovery, contacts and conservation in V6."""
import csv,json,math,re,statistics,sys
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.tactical_entities import positions
from audit_supply import audit


def records(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def main():
    d=json.loads(re.search(r'<script type="application/json" id="replay-data">([\s\S]*?)</script>',(ROOT/'OPEN_SUZHOU.html').read_text())[1])
    c=d['config'];results=[];all_gaps=[];total_shots=0;total_active=0
    for case in d['cases']:
        folder=ROOT/'reports'/f"behavior_seed_{case['seed']}";shots=records(folder/'shots.csv');players=records(folder/'players.csv')
        groups=defaultdict(list)
        for row in shots:groups[row['agent']].append(float(row['release_t']))
        gaps=[b-a for g in groups.values() for a,b in zip(g,g[1:])]
        assert not gaps or min(gaps)>=c['v6']['minimum_release_gap_s']-1e-6
        angles=[e for e in case['events'] if e['kind']=='shot_detail']
        assert len(angles)==len(shots)
        assert all(abs(e['yaw_error_rad'])<=2.6*e['sigma']+1e-8 for e in angles)
        arrows={};bad_lanes=[];maximum_lateral=0;local_frames=0;transition_frames=0
        changes={(e['agent'],round(e['t'],3)) for e in case['events'] if e['kind']=='role_change'}
        for f in case['frames']:
            if f['k']:arrows.clear()
            for bid in f['d']:arrows.pop(bid,None)
            arrows.update({b[0]:b for b in f['a']})
            assert len(arrows)+sum(p[3] for p in f['p'])==36
            for i,p in enumerate(f['p']):
                if p[2] or d['intents'][p[9]]!='pickup' or p[10] is None:continue
                role=d['roles'][p[13]];team='attack' if i<6 else 'defense';home=positions(c,team,role)[0]
                span=abs(p[11]-home[1]);local_frames+=1
                cap=c['v6']['center_lane_reach_m'] if role.startswith('center') else c['v6']['post_lane_reach_m']
                if span>cap+.01:
                    # Role planning runs at the end of a physics tick, after
                    # that tick's policy intent was produced. Report this one
                    # boundary frame separately; only the NEXT policy decision
                    # can replace the old-role intent (decision interval .05s).
                    aid=d['ids'][i]
                    just_changed=any((aid,round(f['t']-offset,3)) in changes for offset in [0,.025,.05])
                    if just_changed:transition_frames+=1;continue
                    bad_lanes.append([f['t'],i,role,span])
                maximum_lateral=max(maximum_lateral,span)
        assert not bad_lanes,bad_lanes[:10]
        active=sum(float(p['active_s']) for p in players)
        evasions=Counter(e['style'] for e in case['events'] if e['kind']=='evade_move')
        outcomes=Counter((s['target_kind'],s['outcome']) for s in shots)
        total_shots+=len(shots);total_active+=active;all_gaps+=gaps
        results.append(dict(seed=case['seed'],duration_s=case['summary']['duration_s'],shots=len(shots),hits=case['summary']['hits'],revivals=case['summary']['revive_grants'],release_gap_median_s=statistics.median(gaps) if gaps else None,release_gap_min_s=min(gaps) if gaps else None,shots_per_active_player_min=len(shots)*60/active,angular_sigma_median_rad=statistics.median(e['sigma'] for e in angles),evades=dict(evasions),pickup_frames=local_frames,max_pickup_lateral_from_role_m=maximum_lateral,pickup_lane_violations=0,role_transition_intent_frames=transition_frames,arrow_conservation_verified=True,outcomes={str(k):v for k,v in outcomes.items()}))
    supply=audit(ROOT/'OPEN_SUZHOU.html')
    assert max(r['longest_unjustified_idle_s'] for r in supply)<=5
    assert all(r['quick_repasses']==0 for r in supply)
    report=dict(episodes=results,supply=supply,all_release_gap_median_s=statistics.median(all_gaps),shots_per_active_player_min=total_shots*60/total_active,all_profiles_synthetic=True,coefficient_status='exploratory_not_measured',notes=['Lane checks concern assigned pickup intent relative to the CURRENT role, not all incidental movement.','No idle near a rear arrow is a symptom metric, not proof that every supply choice is optimal.','All contacts and physical effort remain in the simulation; visual lean alone does not grant evasion.'])
    (ROOT/'reports/v6_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
