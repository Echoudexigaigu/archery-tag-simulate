import json,math,sys,unittest,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.batch_environment import SuzhouEnvironment
from archery_tag_balance.batch_policy import SuzhouPolicy
from archery_tag_balance.batch_supply import BatchSupplyCoordinator
from archery_tag_balance.entities import Action,Status
from archery_tag_balance.tactical_entities import TacticalAction,positions
from archery_tag_balance.policies import Navigator
from archery_tag_balance.geometry import advance_arrow


class BatchV62(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'configs/suzhou_2026.json').read_text());self.c['player_profiles']=json.loads((ROOT/'configs/player_profiles_demo.json').read_text())
        self.e=SuzhouEnvironment(self.c);self.e.reset(1000,record=True);self.co=self.e.supply_coordinator=BatchSupplyCoordinator(self.e)

    def ready(self,aid,p=None):
        a=self.e.agents[aid];a.position=p or positions(self.e,a.team,a.role)[0]
        a.opening_stashed=a.opening_received=a.shoot_unlocked=True;return a

    def carry(self,a,n):
        for _ in range(n):
            b=next(b for b in self.e.arrows.values() if b.state=='ground');self.e._carry(b,a);self.e._picked_up(a,b)

    def isolate(self,ids):
        for a in self.e.agents.values():
            if a.id not in ids:a.status=Status.ELIMINATED;a.lives=0
        for b in self.e.arrows.values():self.e._ground(b,(31,19,0))

    def stock(self,n,p=(.3,1.5)):
        for i,b in enumerate([b for b in self.e.arrows.values() if b.state=='ground'][:n]):self.e._ground(b,(p[0]+.1*(i%2),p[1]+.1*(i//2),0))

    def policy(self,a):return SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),a.id,123)

    def test_middle_can_recover_lower_rear_stock_despite_upper_home_lane(self):
        self.isolate(['attack_1','attack_2']);a=self.ready('attack_2',(5.2,12));self.ready('attack_1')
        self.stock(5);self.co.remember('attack');options=self.co.options(a,transport=True)
        self.assertTrue(options);self.assertLess(options[0]['approach'][1],3)

    def test_combat_preference_one_does_not_limit_transport_quota(self):
        self.isolate(['attack_1','attack_2']);a=self.ready('attack_2');self.ready('attack_1');self.stock(6)
        self.assertEqual(a.human_profile['carry_preference'],1)
        self.co.refresh('attack');c=self.co.contracts['attack']
        self.assertEqual(c['donor'],a.id);self.assertEqual(c['quota'],4);self.assertEqual(self.e.jobs[a.id]['kind'],'batch_collect')

    def test_carrier_with_own_arrow_can_start_distant_recovery(self):
        self.isolate(['attack_1','attack_2']);a=self.ready('attack_2');self.ready('attack_1');self.carry(a,1);self.stock(5)
        self.co.refresh('attack');self.assertIn('attack',self.co.contracts);self.assertEqual(self.e.jobs[a.id]['kind'],'batch_collect')

    def test_cover_with_support_only_has_protected_pickup_options(self):
        self.isolate(['attack_1','attack_2']);a=self.ready('attack_1');self.ready('attack_2');self.stock(5)
        self.co.remember('attack');self.assertFalse(self.co.options(a))

    def test_transport_does_not_strip_a_cover_cache(self):
        self.isolate(['attack_1','attack_2']);a=self.ready('attack_2');cover=self.ready('attack_1');self.stock(2,cover.position)
        self.co.remember('attack');self.assertFalse(self.co.options(a,transport=True))

    def test_four_total_can_pass_three_loose_arrows_without_dropping_nocked_one(self):
        self.isolate(['attack_1','attack_2']);a=self.ready('attack_2',(5.8,14));receiver=self.ready('attack_1')
        self.carry(a,4);a.bow_state='ready';a.nocked_arrow=a.inventory[0];kept=a.nocked_arrow
        for _ in range(3):
            bid=next(b for b in a.inventory if b!=kept)
            c=dict(id=1,donor=a.id,receiver=receiver.id,arrow=bid,team='attack',drop=(7.3,15.45),stage='deliver')
            self.co.contracts['attack']=c;self.co.reserved={bid:receiver.id}
            self.e.jobs[a.id]=dict(kind='batch_deliver',receiver=receiver.id,arrow_to_throw=bid)
            self.e._throw_from_agent(a,receiver.id);self.e.t+=.7
        self.assertEqual(a.inventory,[kept]);self.assertEqual(a.nocked_arrow,kept);self.assertEqual(self.e.counts['arrow_pass'],3)

    def test_a_carrier_never_passes_its_last_arrow(self):
        self.isolate(['attack_1','attack_2']);a=self.ready('attack_2',(5.8,14));r=self.ready('attack_1');self.carry(a,1)
        self.e.jobs[a.id]=dict(kind='batch_deliver',receiver=r.id,arrow_to_throw=a.inventory[0])
        self.e._throw_from_agent(a,r.id);self.assertEqual(self.e.counts['arrow_pass'],0)

    def test_three_empty_bow_arrows_request_nock_before_fourth_pickup(self):
        a=self.ready('attack_2');self.carry(a,3);self.e.jobs[a.id]=dict(kind='batch_collect',quota=4,arrow=10,approach=(4,2))
        p=self.policy(a);act=p(self.e.get_observation(a.id));self.assertEqual(act.interaction,'nock')

    def test_empty_receiver_has_priority_over_armed_recipient(self):
        self.isolate(['attack_1','attack_2','attack_4']);donor=self.ready('attack_2',(4,4));high=self.ready('attack_1');low=self.ready('attack_4');self.carry(donor,4);self.carry(low,1)
        self.co.request_since={high.id:0,low.id:0};c=dict(id=1,team='attack',donor=donor.id,receiver=None,arrow=None,stage='distribute',served=[],deadline=40)
        self.co.contracts['attack']=c;self.co._delivery(c,[donor,high,low]);self.assertEqual(c['receiver'],high.id)

    def test_next_leg_does_not_keep_feeding_the_same_person(self):
        self.isolate(['attack_0','attack_1','attack_2']);donor=self.ready('attack_2',(5,14));high=self.ready('attack_1');flank=self.ready('attack_0');self.carry(donor,3)
        self.co.request_since={high.id:0,flank.id:0};c=dict(id=1,team='attack',donor=donor.id,receiver=None,arrow=None,stage='distribute',served=[high.id],deadline=40)
        self.co.contracts['attack']=c;self.co._delivery(c,[donor,high,flank]);self.assertEqual(c['receiver'],flank.id)

    def test_ordinary_movement_accelerates_and_does_not_teleport_after_pickup(self):
        a=self.ready('attack_2',(4,12));self.e.t=.2
        self.e.step({a.id:Action(move=(1,0))},observe=False)
        self.assertLessEqual(math.hypot(*a.velocity),self.c['v62']['ordinary_acceleration_m_s2']*.025+.01)
        before=a.position;a.pickup_recover_until=self.e.t+.12
        self.e.step({a.id:Action(move=(-1,0))},observe=False)
        self.assertLess(math.dist(a.position,before),.04)

    def test_preference_one_stashes_surplus_before_combat(self):
        a=self.ready('attack_2',(3.5,12));self.carry(a,3);p=self.policy(a)
        act=p(self.e.get_observation(a.id));self.assertEqual(act.interaction,'drop');self.assertEqual(p.intent['kind'],'batch_stash')

    def test_legal_position_inside_nav_safety_buffer_can_escape(self):
        a=self.ready('defense_4',(24.06,4.3));p=self.policy(a)
        self.assertFalse(p.nav.clear(a.position,a.position))
        move=p.move_to(a.position,(21.65,3.97),a.team,10)
        self.assertGreater(move[0],0)
        target=(a.position[0]+move[0]*.1,a.position[1]+move[1]*.1)
        self.assertTrue(self.e.valid_move(a,a.position,target))

    def test_frontline_request_uses_current_front_station(self):
        a=self.ready('attack_2',(10.35,12));self.ready('attack_1')
        self.e.match_planner.plans[a.id]=dict(mode='lockdown',goal=(10.35,12))
        self.assertEqual(self.co.station(a),(10.35,12))

    def test_carrier_does_not_loop_on_its_own_cache_without_a_recipient(self):
        self.isolate(['attack_2']);a=self.ready('attack_2');self.carry(a,2);self.stock(4)
        self.co.refresh('attack');self.assertFalse(self.co.contracts)

    def test_revival_exhaustion_moves_old_lane_towards_score_area(self):
        a=self.ready('attack_5');self.e.skirmish_racks['revive'].standing=[False]*5;self.e.match_planner.update(force=True)
        p=self.policy(a);obs=self.e.get_observation(a.id);_,hold,peek=p._positions(obs)
        self.assertGreater(hold[1],6);self.assertEqual(obs['team_plan']['objective'],'score_battle')

    def test_revival_exhaustion_is_reported_once(self):
        self.e.skirmish_racks['revive'].standing=[False]*5
        self.e.match_planner.update(force=True);self.e.match_planner.update(force=True)
        self.assertEqual(self.e.counts['objective_shift'],1)

    def test_typical_board_spread_is_larger_than_body_spread(self):
        a=self.ready('attack_2');a.steady_aim_s=2;a.aim_key='defense_2';self.e._launch_velocity(a,(5,12,1.25),(17,12,1))
        body=self.e.last_launch[a.id]['sigma'];a.aim_key='rack:revive:4';self.e._launch_velocity(a,(10,2,1.25),(16,2,.75))
        self.assertGreater(self.e.last_launch[a.id]['sigma'],body*1.4)

    def test_same_shot_cloud_hits_more_live_disks_with_five_than_one(self):
        a=self.ready('attack_5');a.aim_key='rack:revive:4';a.snap_revive=True;a.steady_aim_s=0
        rack=self.e.skirmish_racks['revive'];origin=(10,2,1.25);target=rack.spot(4);drag=self.c['physics']['linear_drag_s_inv'];hits=[]
        for _ in range(500):
            v=self.e._launch_velocity(a,origin,target);t=-math.log(1-drag*6/v[0])/drag;q,_=advance_arrow(origin,v,t,9.81,drag)
            hits.append([k for k in range(5) if math.hypot(q[1]-rack.spot(k)[1],q[2]-rack.spot(k)[2])<=self.e.rack_specs['revive']['spot_radii_m'][k]+.0125])
        full=sum(bool(h) for h in hits);one=sum(4 in h for h in hits)
        self.assertGreater(full,one);self.assertLess(one,400);self.assertGreater(one,70)

    def test_elite_steady_target_skill_remains_better_than_typical(self):
        a=self.ready('attack_5');a.aim_key='rack:revive:4';a.steady_aim_s=2
        a.player_model['skills']['target_accuracy']=.6;self.e._launch_velocity(a,(10,2,1.25),(16,2,.75));typical=self.e.last_launch[a.id]['sigma']
        a.player_model['skills']['target_accuracy']=.98;self.e._launch_velocity(a,(10,2,1.25),(16,2,.75));self.assertLess(self.e.last_launch[a.id]['sigma'],typical*.6)

if __name__=='__main__':unittest.main()
