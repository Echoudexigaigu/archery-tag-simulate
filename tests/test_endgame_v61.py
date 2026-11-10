import json,sys,unittest,math
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.endgame_environment import SuzhouEnvironment
from archery_tag_balance.endgame_policy import SuzhouPolicy
from archery_tag_balance.entities import Action,Status
from archery_tag_balance.policies import Navigator
from archery_tag_balance.tactical_entities import positions


class EndgameV61(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'configs/suzhou_2026.json').read_text());self.c['player_profiles']=json.loads((ROOT/'configs/player_profiles_demo.json').read_text())
        self.e=SuzhouEnvironment(self.c);self.e.reset(1000,record=True);self.reward=defaultdict(float)
        from archery_tag_balance.posted_supply import PostedSupplyCoordinator
        self.e.supply_coordinator=PostedSupplyCoordinator(self.e)

    def carry(self,a,n):
        for _ in range(n):
            b=next(b for b in self.e.arrows.values() if b.state=='ground');self.e._carry(b,a);self.e._picked_up(a,b)

    def ready(self,a,n=1):
        a.opening_stashed=a.opening_received=a.shoot_unlocked=True;a.position=positions(self.e,a.team,a.role)[0]
        if n:self.carry(a,n);a.bow_state='ready';a.nocked_arrow=a.inventory[0]
        return a

    def kill(self,aid):self.e._eliminate(self.e.agents[aid],self.e.agents['defense_0' if aid.startswith('attack') else 'attack_0'],self.reward)

    def lone(self):
        for a in self.e.agents.values():self.ready(a)
        for i in range(5):self.kill(f'attack_{i}')
        self.e.match_planner.update(force=True)

    def policy(self,a):return SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),a.id,123)

    def test_six_vs_one_assigns_distinct_front_positions_and_two_watchers(self):
        self.lone();plans=[self.e.match_planner.plans[f'defense_{i}'] for i in range(6)]
        self.assertTrue(all(p['mode']=='lockdown' for p in plans));self.assertEqual(sum(p['task']=='watch' for p in plans),2)
        self.assertEqual(len({tuple(p['goal']) for p in plans}),6)
        self.assertTrue(all(21.26<p['goal'][0]<31.74 for p in plans))

    def test_held_last_team_arrow_cannot_be_fired_away(self):
        self.lone()
        for i in range(1,6):
            a=self.e.agents[f'defense_{i}']
            for bid in list(a.inventory):self.e._ground(self.e.arrows[bid],(*a.position,0))
            a.inventory.clear();a.bow_state='empty';a.nocked_arrow=None
        a=self.e.agents['defense_0'];a.position=(21.65,18);a.aim_elapsed=10;a.bow_bearing=math.pi
        self.e.match_planner.update(force=True)
        self.e._release(a,Action(aim=(7,18,1),aim_key='attack_5',interaction='shoot'))
        self.assertEqual(self.e.counts['shot'],0);self.assertEqual(len(a.inventory),1)

    def test_advantage_side_does_not_release_simultaneous_volley(self):
        self.lone();self.e.t=10
        a=self.e.agents['defense_2'];a.position=(21.65,12);a.aim_elapsed=10;a.bow_bearing=math.pi
        self.e.agents['defense_3'].last_shot_at=9.7
        self.e._release(a,Action(aim=(7,12,1),aim_key='attack_5',interaction='shoot'))
        self.assertEqual(self.e.counts['shot'],0)

    def test_advantage_watcher_holds_bow_without_mandatory_shot(self):
        self.lone();a=self.e.agents['defense_0'];a.position=(21.65,18.1)
        self.e.agents['attack_5'].position=(7.5,8);self.e.match_planner.update(force=True)
        p=self.policy(a);obs=self.e.get_observation(a.id);obs['job']={}
        act=p(obs);self.assertIsNotNone(act.aim);self.assertEqual(act.interaction,'none');self.assertEqual(p.intent['kind'],'pin_hold')

    def test_lone_player_prefers_revival_with_five_enemy_points_left(self):
        self.lone();a=self.e.agents['attack_5'];a.position=(7.5,2)
        p=self.policy(a);obs=self.e.get_observation(a.id);obs['job']={};obs['enemies']=[]
        p(obs);self.assertEqual(p.lone_choice,'revive');self.assertIn(p.intent['kind'],('revive','revive_snap'))

    def test_lone_player_considers_finishing_only_few_points(self):
        self.lone();self.e.skirmish_racks['defense'].standing=[True,False,False,False,False]
        a=self.e.agents['attack_5'];p=self.policy(a);obs=self.e.get_observation(a.id);obs['job']={}
        p(obs);self.assertEqual(p.lone_choice,'finish')

    def test_pressure_sends_lone_player_to_shelter(self):
        self.lone();a=self.e.agents['attack_5'];a.position=(7,3)
        for i in range(4):
            b=self.e.agents[f'defense_{i}'];b.position=(22,2+i*.4);b.aim_elapsed=1;b.bow_bearing=math.atan2(a.position[1]-b.position[1],a.position[0]-b.position[0])
        p=self.policy(a);obs=self.e.get_observation(a.id);obs['job']={};p(obs)
        self.assertIn(p.intent['kind'],('survive_cover','survive_back'))

    def test_cover_does_not_recover_far_rear_stock_while_local_support_lives(self):
        a=self.ready(self.e.agents['attack_1'],0);support=self.ready(self.e.agents['attack_2'],0)
        for b in self.e.arrows.values():self.e._ground(b,(31,19,0))
        bid=next(iter(self.e.arrows));self.e._ground(self.e.arrows[bid],(2.5,15.45,0))
        self.e.supply_coordinator.remember('attack')
        self.assertFalse(self.e.supply_coordinator.options(a));self.assertTrue(self.e.supply_coordinator.supports(a))

    def test_cover_can_recover_rear_stock_when_no_local_support_survives(self):
        a=self.ready(self.e.agents['attack_1'],0)
        for i in (0,2,3):self.kill(f'attack_{i}')
        for b in self.e.arrows.values():self.e._ground(b,(31,19,0))
        bid=next(iter(self.e.arrows));self.e._ground(self.e.arrows[bid],(2.5,15.45,0));self.e.supply_coordinator.remember('attack')
        self.assertTrue(self.e.supply_coordinator.options(a))

    def test_low_ammo_request_starts_before_cover_is_empty(self):
        a=self.ready(self.e.agents['attack_1']);d=self.ready(self.e.agents['attack_2'],2)
        a.position=(7.47,15.45);d.position=(5.8,14)
        for b in self.e.arrows.values():
            if b.state=='ground':self.e._ground(b,(31,19,0))
        self.e.supply_coordinator.refresh('attack')
        self.assertIn(a.id,self.e.supply_coordinator.request_since)
        c=self.e.supply_coordinator.contracts['attack'];self.assertTrue(c['proactive']);self.assertEqual(c['receiver'],a.id)
        self.e.supply_coordinator.update_contract('attack');self.assertIn('attack',self.e.supply_coordinator.contracts)

    def test_other_teams_refresh_does_not_clear_my_ammo_call(self):
        a=self.ready(self.e.agents['attack_1']);self.ready(self.e.agents['attack_2'])
        for b in self.e.arrows.values():
            if b.state=='ground':self.e._ground(b,(31,19,0))
        co=self.e.supply_coordinator;co.refresh('attack');stamp=co.request_since[a.id]
        co.refresh('defense');co.refresh('attack')
        self.assertEqual(co.request_since[a.id],stamp)
        self.assertEqual(sum(e['kind']=='ammo_call' and e.get('agent')==a.id for e in self.e.events),1)

    def test_only_two_arrows_can_keep_one_watcher_and_one_finisher(self):
        self.lone()
        for i in (0,3,4,5):
            a=self.e.agents[f'defense_{i}']
            for bid in list(a.inventory):self.e._ground(self.e.arrows[bid],(*a.position,0))
            a.inventory.clear();a.bow_state='empty';a.nocked_arrow=None
        self.e.match_planner.update(force=True)
        a=self.e.agents['defense_2'];a.position=(21.65,12);a.bow_bearing=math.pi;a.aim_elapsed=10
        p=self.policy(a);obs=self.e.get_observation(a.id);obs['job']={};obs['enemies']=[]
        action=p(obs);self.assertEqual(action.interaction,'shoot');self.assertEqual(p.intent['kind'],'finish_target')

    def test_bow_turns_continuously_and_cannot_release_behind_its_pose(self):
        a=self.ready(self.e.agents['attack_2']);a.bow_bearing=0.;a.aim_elapsed=10
        action=Action(aim=(a.position[0],18,1),aim_key='defense_0',interaction='shoot')
        self.e._on_aim_progress(a,action,.025);self.assertLessEqual(a.bow_bearing,3.8*.025+1e-8)
        self.e._release(a,action);self.assertEqual(self.e.counts['shot'],0)

    def test_twelve_metre_ordinary_motion_is_trackable_without_a_dodge(self):
        from archery_tag_balance.geometry import advance_arrow
        a=self.ready(self.e.agents['attack_2']);a.position=(10,8);a.aim_key='defense_2';a.steady_aim_s=2
        p=self.policy(a);p.latency=.17
        enemy=dict(id='defense_2',position=(22,8),velocity=(0,2),height=1.7,status='active')
        p.histories['defense_2']=[(.8,dict(enemy,position=(22,7.6)))]
        obs=self.e.get_observation(a.id);obs['time']=1
        aim=p._aim(obs,('defense_2',(22,8,1.),enemy,12))
        self.assertGreater(aim[1],8.6)
        inside=0;drag=self.c['physics']['linear_drag_s_inv']
        for _ in range(50):
            v=self.e._launch_velocity(a,(10,8,1.25),aim)
            t=-math.log(1-drag*12/v[0])/drag;q,_=advance_arrow((10,8,1.25),v,t,9.81,drag)
            inside+=abs(q[1]-(8+2*t))<.275 and 0<q[2]<1.7
        self.assertGreaterEqual(inside,48)

    def test_supplier_with_one_arrow_fetches_a_second_for_low_ammo_cover(self):
        a=self.ready(self.e.agents['attack_1']);d=self.ready(self.e.agents['attack_2'])
        a.position=(7.47,15.45);d.position=(5.8,14);d.aim_elapsed=0
        for b in self.e.arrows.values():
            if b.state=='ground':self.e._ground(b,(31,19,0))
        source=next(b for b in self.e.arrows.values() if b.state=='ground');self.e._ground(source,(4.8,13.8,0))
        self.e.supply_coordinator.refresh('attack');c=self.e.supply_coordinator.contracts['attack']
        self.assertEqual(self.e.jobs[d.id]['kind'],'relay_fetch');self.assertEqual(self.e.jobs[d.id]['quota'],2)
        self.e._carry(source,d);self.e._picked_up(d,source);self.e.supply_coordinator.update_contract('attack')
        self.assertEqual(self.e.jobs[d.id]['kind'],'relay');self.assertEqual(len(d.inventory),2)

    def test_early_delivery_is_not_completed_merely_because_receiver_has_one(self):
        a=self.ready(self.e.agents['attack_1']);d=self.ready(self.e.agents['attack_2'],2)
        a.position=(7.47,15.45);d.position=(5.8,14)
        for b in self.e.arrows.values():
            if b.state=='ground':self.e._ground(b,(31,19,0))
        co=self.e.supply_coordinator;co.refresh('attack');c=co.contracts['attack'];bid=c['arrow']
        d.inventory.remove(bid);self.e._ground(self.e.arrows[bid],(7.3,15.45,0));c['stage']='flight';co.remember('attack');co.update_contract('attack')
        self.assertEqual(self.e.jobs[a.id]['kind'],'delivered_collect');self.assertEqual(self.e.jobs[a.id]['quota'],2)
        self.e._carry(self.e.arrows[bid],a);co.update_contract('attack');self.assertNotIn('attack',co.contracts)

    def test_revive_rim_graze_bounces_but_center_contact_remains(self):
        b=next(iter(self.e.arrows.values()));rack=self.e.skirmish_racks['revive'];x,y,z=rack.spot(0)
        old={a.id:a.position for a in self.e.agents.values()};b.shooter='attack_5'
        for offset,expected in [(.09,-1),(.0,0)]:
            hits=self.e._contacts(b,(x-1,y+offset,z),(x+1,y+offset,z),old,old)
            target=next(t for _,_,k,t in hits if k=='skirmish_rack' and t[0]=='revive')
            self.assertEqual(target[1],expected)

    def test_queue_fifo_runs_from_each_teams_outer_edge(self):
        for team in ('attack','defense'):
            self.kill(team+'_2');self.kill(team+'_0')
            first=self.e.out_routes[team+'_2'][-1][0];second=self.e.out_routes[team+'_0'][-1][0]
            self.assertTrue(first<second if team=='attack' else first>second)

    def test_queue_reflows_after_first_qualifies_without_duplicate_slots(self):
        self.kill('defense_2');self.kill('defense_0')
        first=self.e.revive_queue['defense'].pop(0);self.e.revive_approved.add(first);self.e._layout_queue('defense')
        self.assertEqual(self.e.wait_slots['defense_0'],0)
        self.assertEqual(len(set(self.e.wait_slots.values())),len(self.e.wait_slots))

if __name__=='__main__':unittest.main()
