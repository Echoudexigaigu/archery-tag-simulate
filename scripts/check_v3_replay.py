"""Validate the delivered packed replays without rerunning a match."""
import collections
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    html=(ROOT/'OPEN_SUZHOU.html').read_text(encoding='utf-8')
    data=json.loads(re.search(r'<script type="application/json" id="replay-data">([\s\S]*?)</script>',html)[1])
    rows=[]
    for case in data['cases']:
        kinds=collections.Counter(e['kind'] for e in case['events'])
        arrows={};max_total=max_hand=max_waiting=0
        previous=[None]*12;started=[0.]*12;longest=0.
        for frame in case['frames']:
            if frame['k']:arrows.clear()
            for bid in frame['d']:arrows.pop(bid,None)
            arrows.update({r[0]:r for r in frame['a']})
            assert len(arrows)+sum(p[3] for p in frame['p'])==36
            for i,p in enumerate(frame['p']):
                assert 0<=p[3]<=4 and 0<=p[15]<=3
                assert p[15]==p[3]-(1 if p[14] else 0)
                max_total=max(max_total,p[3]);max_hand=max(max_hand,p[15])
                key=p[12] if p[9]==data['intents'].index('pickup') else None
                if key!=previous[i]:
                    if previous[i] is not None:longest=max(longest,frame['t']-started[i])
                    previous[i]=key;started[i]=frame['t']
            for people in (frame['p'][:6],frame['p'][6:]):
                roles=[p[13] for p in people if not p[2]]
                assert len(roles)==len(set(roles))
                waiting=[(p[7],p[8]) for p in people if p[2] and p[16]==2]
                assert len(waiting)==len(set(waiting))
                max_waiting=max(max_waiting,len(waiting))
        for i,key in enumerate(previous):
            if key is not None:longest=max(longest,frame['t']-started[i])
        quick=sum(e['kind']=='release_cue' and e.get('quick',False) for e in case['events'])
        assert kinds['opening_cache_ready']==12 and quick>0
        assert case['summary']['v3_stats']['arrow_pass']>0
        assert kinds['opening_bundle']==12
        nocks=[e['duration'] for e in case['events'] if e['kind']=='nock']
        assert nocks and max(nocks)<.2
        assert kinds['evade_move']>0
        rows.append(dict(seed=case['seed'],frames=len(case['frames']),shots=case['summary']['shots'],hits=case['summary']['hits'],revives=case['summary']['revive_grants'],max_total=max_total,max_hand=max_hand,max_waiting=max_waiting,quick_releases=quick,opening_bundles=kinds['opening_bundle'],movement_evades=kinds['evade_move'],max_nock_s=round(max(nocks),3),longest_continuous_pickup_intent_s=round(longest,2),arrow_conservation_all_frames=True,live_roles_unique_all_frames=True,v3_stats=case['summary']['v3_stats']))
    ny={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['references/NEW_YORK_v7.html','configs/new_york_reference_v7.json']}
    report=dict(unit_tests=79,episodes=rows,new_york_reference_sha256=ny,placeholder_profiles=True,trained_policy=False)
    (ROOT/'reports/v3_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
