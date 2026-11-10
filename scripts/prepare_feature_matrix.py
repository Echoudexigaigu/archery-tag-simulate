"""Make context-tagged candidate features, without fitting a factor model."""
import csv,json,math,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    payload=json.loads(re.search(r'<script type="application/json" id="replay-data">([\s\S]*?)</script>',(ROOT/'OPEN_SUZHOU.html').read_text())[1])
    scenarios={str(c['seed']):c.get('scenario') or 'ordinary_match' for c in payload['cases']}
    rows=[]
    for path in sorted((ROOT/'reports').glob('behavior_seed_*/players.csv')):
        with path.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                active=float(r['active_s']);safe=lambda value:float(value) if value not in ('',None) else None
                rows.append(dict(source='simulation',seed=r['seed'],scenario=scenarios.get(r['seed'],'unknown'),player_id=r['player_id'],initial_role=r['home_role'],active_s=active,body_shots_resolved=int(r['body_shots_resolved']),scoreboard_shots_resolved=int(r['scoreboard_shots_resolved']),body_hit_rate=safe(r['intended_body_hit_rate']),scoreboard_knockdown_rate=safe(r['scoreboard_knockdown_rate']),cover_fraction=safe(r['cover_fraction']),mean_movement_m_s=float(r['distance_m'])/active if active else None,no_arrow_fraction=float(r['no_arrow_s'])/active if active else None,evasions_per_active_min=float(r['evasion_actions'])*60/active if active else None,passes_per_active_min=float(r['passes'])*60/active if active else None))
    p=ROOT/'reports/features_for_factorization.csv'
    with p.open('w',newline='',encoding='utf-8-sig') as f:
        if rows:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (ROOT/'reports/features_notes.json').write_text(json.dumps(dict(source='simulation_only',fitted_model=False,rows=len(rows),notes=['Keep scenario, role, opponents, active time and trial counts as context. Do not pool an artificial initial state with normal matches without accounting for it.','The initial_role column does not control subsequent position changes. Split decisions.csv by actual role intervals before estimating style.','Missing rates are missing, never zero.','Do not mix synthetic simulation rows with real video observations.','No matrix factorization has been fit; candidate features do not automatically identify skill and style.']),indent=2)+'\n',encoding='utf-8')
    print(f'Prepared {len(rows)} context-tagged simulation feature rows; no model fitted.')

if __name__=='__main__':main()
