import argparse,json,sys,hashlib,shutil,statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.batch_environment import SuzhouEnvironment
from archery_tag_balance.batch_policy import SuzhouPolicy
from archery_tag_balance.policies import Navigator

STAGES=['out','opening','gathering','caching','pickup','search','waiting_arrow','nocking','aiming','ready','empty_bow']
INTENTS=['out','hold','gather','cache','pickup','search','revive','shoot','shoot_low','supply','pass','nock','escape','request','guard','follow','revive_snap','wait_delivery','risk_hold','assess','track','press_front','pin_hold','conserve','finish_target','survive_cover','survive_back','recover_front','batch_collect','batch_deliver','batch_pause','batch_stash']
ROLES=['high_flank','high_cover','center_1','center_2','low_cover','revive_lane']


def config(profile_path=None):
    c=json.loads((ROOT/'configs/suzhou_2026.json').read_text(encoding='utf-8'))
    c['roster']=json.loads((ROOT/'configs/roster.json').read_text(encoding='utf-8'))
    c['player_profiles']=json.loads(Path(profile_path or ROOT/'configs/player_profiles_demo.json').read_text(encoding='utf-8'))
    for aid,p in c['player_profiles'].items():
        c['roster'][aid]['name']=('例'+p['player_id']) if p.get('is_demo') else p.get('alias') or p['player_id']
        if p.get('is_demo'):c['roster'][aid]['muzzle_speed_fps']=122.5
        if p.get('equipment',{}).get('muzzle_speed_fps') is not None:c['roster'][aid]['muzzle_speed_fps']=p['equipment']['muzzle_speed_fps']
    return c


def episode(seed,record=True,check=True,profile_path=None,scenario=None):
    c=config(profile_path);e=SuzhouEnvironment(c);e.reset(seed,record=record,record_interval_s=.05)
    if scenario=='six_vs_one':
        from archery_tag_balance.scenarios import six_vs_one
        six_vs_one(e)
    if scenario=='rear_stock':
        from archery_tag_balance.scenarios import rear_stock
        rear_stock(e)
    nav=Navigator(c,e.navigation_obstacles)
    policies={aid:SuzhouPolicy(c,nav,aid,20261107*101+i+17) for i,aid in enumerate(e.agents)}
    actions={};next_time=-1
    while not e.done and not (scenario=='rear_stock' and e.t>=40.-1e-8):
        if e.t+1e-9>=next_time:
            actions={aid:policies[aid](e.get_observation(aid)) for aid in e.agents}
            e.policy_intents={aid:dict(p.intent) for aid,p in policies.items()}
            next_time=e.t+c['policy']['decision_interval_s']
        e.step(actions,observe=False)
        if check:e.assert_invariants()
    row=e.summary();row.pop('resource_curve',None)
    if scenario=='rear_stock' and not e.done:row.update(winner='ongoing',victory_reason='demonstration_window')
    launches=[x['speed_fps'] for x in e.events if x['kind']=='shot_detail']
    row['observed_speed_fps']={'mean':statistics.mean(launches) if launches else None,'min':min(launches) if launches else None,'max':max(launches) if launches else None}
    return e,row


def compact(e):
    ids=list(e.agents);index={aid:i for i,aid in enumerate(ids)};frames=[];previous={}
    r=lambda x:round(x,3) if x is not None else None
    for i,f in enumerate(e.trace):
        players=[]
        for p in f['players']:
            intent=p.get('intent') or {};goal=intent.get('goal');out=p.get('out_position')
            players.append([r(v) for v in p['position']]+[int(p['status']=='eliminated'),p['ammo'],int(p['crouched']),STAGES.index(p['stage']),int(p['revive_runner']),r(out[0]) if out else None,r(out[1]) if out else None,INTENTS.index(intent.get('kind','hold')),r(goal[0]) if goal else None,r(goal[1]) if goal else None,intent.get('arrow'),ROLES.index(p['role']),['empty','nocking','ready'].index(p['bow_state']),p['hand_arrows'],['hit','leaving','waiting','returning',None].index(p['out_stage']),[None,'sidestep','duck'].index(p.get('evasion_kind')),index.get(p.get('job_partner'),-1),r((intent.get('mind') or {}).get('focus')),r((intent.get('mind') or {}).get('pressure')),r((intent.get('mind') or {}).get('risk_margin')),p.get('aim_key'),r(p.get('aim_elapsed',0)),r(p.get('aim_required',1)),r(p.get('dodge_velocity',(0,0))[0]),r(p.get('dodge_velocity',(0,0))[1]),r(p.get('bow_bearing')),r(p['aim_point'][0]) if p.get('aim_point') else None,r(p['aim_point'][1]) if p.get('aim_point') else None,p.get('team_plan',{}).get('mode','balanced'),p.get('team_plan',{}).get('task','post'),int(p.get('ammo_requested',False)),p.get('transport_quota',0),p.get('team_plan',{}).get('objective','revival_live')])
        arrows={}
        for b in f['arrows']:
            state={'ground':0,'flying':1,'settling':2,'tossed':3,'discard_pending':4}[b['state']]
            row=[b['id'],r(b['position'][0]),r(b['position'][1]),r(b['position'][2]),state,index.get(b['shooter'],-1)]
            if state:row+=[r(b['velocity'][0]),r(b['velocity'][1]),int(b.get('dead_kind') in ('pass','discard'))]
            else:row[5]=-1
            arrows[b['id']]=row
        checkpoint=i%20==0
        updates=list(arrows.values()) if checkpoint else [row for bid,row in arrows.items() if previous.get(bid)!=row]
        removed=[] if checkpoint else sorted(set(previous)-set(arrows))
        previous=arrows
        scores=f['remaining_score']
        frames.append(dict(t=round(f['t'],3),p=players,a=updates,d=removed,k=int(checkpoint),r=[sum(int(v)<<j for j,v in enumerate(f['racks'][team])) for team in ['attack','defense','revive']],q=[[index[aid] for aid in f['revive_queue'][team]] for team in ['attack','defense']],v=[index[aid] for aid in f['revive_approved']],s=[scores['attack']['alive'],scores['attack']['target'],scores['defense']['alive'],scores['defense']['target']]))
    return dict(frames=frames,events=e.events)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seeds',default='1000,1001,1002');parser.add_argument('--cache-dir');parser.add_argument('--profiles');parser.add_argument('--endgame-demo',action='store_true');parser.add_argument('--supply-demo',action='store_true');args=parser.parse_args()
    (ROOT/'reports').mkdir(exist_ok=True)
    cases=[];rows=[]
    specs=[(seed,None) for seed in map(int,args.seeds.split(','))]
    if args.endgame_demo:specs.append((6106,'six_vs_one'))
    if args.supply_demo:specs.append((6200,'rear_stock'))
    for seed,scenario in specs:
        e,row=episode(seed,profile_path=args.profiles,scenario=scenario);e.behavior.export(ROOT/'reports'/f'behavior_seed_{seed}');rows.append(row);case=dict(seed=seed,summary=row,label='补给测试 · 上路空弓 / 后场有箭（前40秒）' if scenario=='rear_stock' else '残局测试 · 红1对蓝6' if scenario else f'示例 · 种子 {seed}',scenario=scenario,**compact(e));cases.append(case)
        if args.cache_dir:
            cache=Path(args.cache_dir);cache.mkdir(parents=True,exist_ok=True)
            (cache/f'case_{seed}.json').write_text(json.dumps(case,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        print(json.dumps({k:row[k] for k in ['seed','winner','duration_s','shots','hits','revive_grants','observed_speed_fps']},ensure_ascii=False),flush=True)
    payload=json.dumps(dict(config=config(args.profiles),cases=cases,packed=True,ids=list(e.agents),stages=STAGES,intents=INTENTS,roles=ROLES),ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
    template=(ROOT/'src/archery_tag_balance/suzhou_replay.html').read_text(encoding='utf-8')
    (ROOT/'OPEN_SUZHOU.html').write_text(template.replace('__SUZHOU_PAYLOAD__',payload).replace('__SUZHOU_RENDERER__',(ROOT/'src/archery_tag_balance/suzhou_renderer.js').read_text(encoding='utf-8')),encoding='utf-8')
    (ROOT/'reports/validation.json').write_text(json.dumps(dict(episodes=len(rows),rows=rows),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*')) if p.is_file() and '__pycache__' not in str(p)}
    (ROOT/'reports/source_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n',encoding='utf-8')
    print('Built OPEN_SUZHOU.html')

if __name__=='__main__':main()
