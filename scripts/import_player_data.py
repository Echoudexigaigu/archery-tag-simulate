"""Import explicit self/peer scores; retain blanks and raw evidence separately."""
import argparse,csv,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.player_model import SKILLS,STYLE


def workbook_rows(path,sheet):
    from openpyxl import load_workbook
    ws=load_workbook(path,data_only=False,read_only=True)[sheet];rows=iter(ws.values)
    headers=[str(h or '').split('|')[0] for h in next(rows)]
    return [dict(zip(headers,row)) for row in rows if any(v is not None for v in row)]


def csv_rows(path):
    with Path(path).open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def number(value,label):
    if value in ('',None):return None
    try:n=float(value)
    except (TypeError,ValueError):raise ValueError(f'{label}: use a number, not a formula or text')
    if not math.isfinite(n) or not 0<=n<=100:raise ValueError(f'{label}: expected 0 to 100')
    return n/100


def source_name(value):
    value=str(value or '').strip()
    return {'自评':'self','他评':'peer','测量':'measurement','录像':'video','现场观察':'observation'}.get(value,value)


def import_rows(tables,lineup,source=None,aggregate=None):
    info={str(r['player_id']):r for r in tables['players'] if r.get('player_id')}
    pool={pid:dict(player_id=pid,alias=str(r.get('alias') or pid),is_demo=False,source='reported_unvalidated',skills={},style={},opponent_beliefs={},missing_fields=[]) for pid,r in info.items()}
    for pid,p in pool.items():
        value=info[pid].get('carry_count')
        if value not in ('',None):
            carry=float(value)
            if not math.isfinite(carry) or not carry.is_integer() or not 1<=carry<=4:raise ValueError('carry_count must be 1, 2, 3 or 4')
            p['preferred_carry']=int(carry)
        else:p['missing_fields'].append('preferred_carry')
    for tab,section,fields in [('skills','skills',SKILLS),('styles','style',STYLE)]:
        for pid,p in pool.items():
            reports=[r for r in tables[tab] if str(r.get('player_id'))==pid and (source is None or source_name(r.get('source'))==source_name(source))]
            for field in fields:
                values=[number(r.get(field),f'{pid}.{field}') for r in reports]
                values=[v for v in values if v is not None]
                if len(values)>1 and aggregate!='median':raise ValueError(f'{pid}.{field}: multiple reports; choose --source or --aggregate median')
                if values:p[section][field]=statistics.median(values)
                else:p['missing_fields'].append(section+'.'+field)
    for row in tables.get('beliefs',[]):
        pid=str(row.get('player_id') or '');op=str(row.get('opponent_id') or '')
        if pid in pool and op:
            v=number(row.get('concern'),pid+'.concern')
            if v is not None:pool[pid]['opponent_beliefs'][op]=v
    for row in tables.get('equipment',[]):
        pid=str(row.get('player_id') or '')
        if pid not in pool:continue
        fps=row.get('muzzle_speed_fps')
        if fps not in (None,''):
            value=float(fps)
            if not math.isfinite(value) or not 0<value<=300:raise ValueError('muzzle_speed_fps must be positive, finite and no more than 300')
            pool[pid]['equipment']={**row,'muzzle_speed_fps':value}
    selected={}
    for aid,pid in lineup.items():
        if pid not in pool:raise ValueError(f'Lineup player is absent: {pid}')
        selected[aid]=pool[pid]
    if len(set(lineup.values()))!=len(lineup):raise ValueError('A player cannot occupy two lineup slots')
    return selected,pool


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workbook',type=Path);ap.add_argument('--csv-directory',type=Path);ap.add_argument('--source');ap.add_argument('--aggregate',choices=['median']);ap.add_argument('--lineup',type=Path,default=ROOT/'configs/lineup.json');ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if bool(args.workbook)==bool(args.csv_directory):ap.error('Choose --workbook OR --csv-directory')
    sheets={'players':'选手信息','skills':'技术能力','styles':'打法风格','beliefs':'对手认知','equipment':'器材记录','situations':'局面选择','states':'状态自述'}
    files={'players':'players','skills':'skills','styles':'styles','beliefs':'opponent_beliefs','equipment':'equipment','situations':'situations','states':'states'}
    tables={k:workbook_rows(args.workbook,s) if args.workbook else csv_rows(args.csv_directory/(files[k]+'.csv')) for k,s in sheets.items()}
    lineup=json.loads(args.lineup.read_text(encoding='utf-8'));selected,pool=import_rows(tables,lineup,args.source,args.aggregate)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    args.output.with_suffix('.pool.json').write_text(json.dumps(dict(players=pool,raw_reports=tables,source_filter=args.source,aggregation=args.aggregate,warnings=['Blank values remain missing; the simulator uses labelled neutral priors for missing fields.','Scenario answers are evidence for review, not automatically fitted psychological traits.']),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Imported {len(pool)} player records; selected {len(selected)}; missing scores retained as missing.')

if __name__=='__main__':main()
