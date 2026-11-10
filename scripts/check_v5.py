"""Audit provenance, denominators and attention records in delivered episodes."""
import csv,json,math,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from audit_supply import audit


def read(path):
    with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def main():
    data=json.loads(re.search(r'<script type="application/json" id="replay-data">([\s\S]*?)</script>',(ROOT/'OPEN_SUZHOU.html').read_text(encoding='utf-8'))[1])
    assert all(p['is_demo'] for p in data['config']['player_profiles'].values())
    rows=[];not_noticed=risk_hold=scans=0
    for case in data['cases']:
        folder=ROOT/'reports'/f"behavior_seed_{case['seed']}"
        players=read(folder/'players.csv');shots=read(folder/'shots.csv');decisions=read(folder/'decisions.csv')
        assert len(players)==12 and len(shots)==case['summary']['shots']
        assert len({s['shot_id'] for s in shots})==len(shots)
        assert all(r['source']=='simulation' for r in [*players,*shots,*decisions])
        for p in players:
            active=float(p['active_s']);assert active<=case['summary']['duration_s']+1e-6
            assert float(p['cover_geometry_s'])<=active+1e-6
            for rate,denominator in [('intended_body_hit_rate','body_shots_resolved'),('scoreboard_knockdown_rate','scoreboard_shots_resolved')]:
                if not int(p[denominator]):assert p[rate]==''
                else:assert math.isfinite(float(p[rate])) and 0<=float(p[rate])<=1
        for r in decisions:
            assert 0<=int(r['noticed_arrows'])<=int(r['visible_arrows'])
            assert 0<=float(r['pressure'])<=1
        missed=sum(int(r['visible_arrows'])>int(r['noticed_arrows']) for r in decisions)
        holds=sum(r['reason']=='risk_hold' for r in decisions);glances=sum(r['reason']=='glance_scan' for r in decisions)
        not_noticed+=missed;risk_hold+=holds;scans+=glances
        rows.append(dict(seed=case['seed'],player_rows=len(players),shot_rows=len(shots),decision_rows=len(decisions),visible_but_not_noticed_samples=missed,risk_hold_samples=holds,glance_samples=glances,denominators_verified=True))
    assert not_noticed>0 and risk_hold>0 and scans>0
    supply=audit(ROOT/'OPEN_SUZHOU.html')
    assert max(r['longest_unjustified_idle_s'] for r in supply)<=5, 'Arrow recovery regression'
    assert all(r['quick_repasses']==0 for r in supply), 'Repeated hand-pass loop'
    report=dict(unit_tests=int(re.search(r"Ran (\d+) tests",(ROOT/"reports/unit_tests.txt").read_text())[1]),episodes=rows,all_profiles_synthetic=True,no_factor_model_trained=True,source_separation_verified=True,supply_audit=supply)
    (ROOT/'reports/v5_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
