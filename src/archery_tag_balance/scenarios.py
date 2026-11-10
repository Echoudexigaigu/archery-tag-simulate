"""Explicit synthetic initial states, separate from ordinary match seeds."""
from collections import defaultdict
from .tactical_entities import positions


def six_vs_one(e):
    for a in e.agents.values():
        a.opening_stashed=a.opening_received=a.shoot_unlocked=True
        a.position=positions(e,a.team,a.role)[0]
        if a.team=='defense' or a.id=='attack_5':
            for _ in range(2):
                b=next(b for b in e.arrows.values() if b.state=='ground');e._carry(b,a);e._picked_up(a,b)
            a.bow_state='ready';a.nocked_arrow=a.inventory[0];a.reload_left=0
    e.agents['attack_5'].position=(7.77,5.)
    for i in range(5):e._eliminate(e.agents[f'attack_{i}'],e.agents['defense_0'],defaultdict(float))
    # These five exits define the starting state, not successful attacks in
    # this simulated segment. Keep the queue, but separate event statistics.
    e.events=[x for x in e.events if x['kind'] not in ('hit','queue_join')]
    e.counts['hit']=0;e.scores['defense']['body']=0
    e._emit('scenario_initial_out',team='attack',count=5)
    # Keep genuine physical arrow conservation. Remaining ground arrows are
    # split among each half's rear stock; this is not the historical V5 replay.
    ground=[b for b in e.arrows.values() if b.state=='ground']
    for i,b in enumerate(ground):
        team='attack' if i%2==0 else 'defense';idx=i%6
        e._ground(b,((3.2 if team=='attack' else 28.8),[18.,15.45,12.,8.2,5.,2.15][idx],0))
    e.match_planner.update(force=True);e._refresh_supply('attack');e._refresh_supply('defense')
    e.trace.clear();e._record_frame();e.assert_invariants()


def rear_stock(e):
    """Regression: upper posts empty, all stock at the lower rear boundary."""
    for a in e.agents.values():
        a.opening_stashed=a.opening_received=a.shoot_unlocked=True
        a.position=positions(e,a.team,a.role)[0]
    for i,b in enumerate(e.arrows.values()):
        e._ground(b,((.15+(i%4)*.45) if i<18 else (31.85-(i%4)*.45),.2+(i%9)*.22,0))
    e.skirmish_racks['revive'].standing=[False]*5
    e.match_planner.update(force=True);e._refresh_supply('attack');e._refresh_supply('defense')
    e.trace.clear();e._record_frame();e.assert_invariants()
