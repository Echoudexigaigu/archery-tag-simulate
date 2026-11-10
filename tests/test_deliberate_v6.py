import copy,json,math,statistics,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.deliberate_environment import SuzhouEnvironment
from archery_tag_balance.personality_environment import SuzhouEnvironment as V5Environment
from archery_tag_balance.deliberate_policy import SuzhouPolicy
from archery_tag_balance.local_supply import LocalSupplyCoordinator
from archery_tag_balance.entities import Action,Status
from archery_tag_balance.geometry import advance_arrow
from archery_tag_balance.policies import Navigator
from archery_tag_balance.tactical_entities import positions


class DeliberateV6(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'configs/suzhou_2026.json').read_text())
        self.c['player_profiles']=json.loads((ROOT/'configs/player_profiles_demo.json').read_text())
        self.e=SuzhouEnvironment(self.c);self.e.reset(1000,record=True)
        self.a=self.e.agents['attack_2']

    def carry(self,a,n):
        for _ in range(n):
            b=next(b for b in self.e.arrows.values() if b.state=='ground')
            self.e._carry(b,a);self.e._picked_up(a,b)

    def ready(self,a,n=1):
        a.opening_stashed=a.opening_received=a.shoot_unlocked=True
        self.carry(a,n);a.position=positions(self.c,a.team,a.role)[0]
        a.bow_state='ready';a.nocked_arrow=a.inventory[0];a.aim_elapsed=10
        return a

    def supply_setup(self,people):
        for a in self.e.agents.values():a.status=Status.ELIMINATED
        for a,p in people:
            a.status=Status.ACTIVE;a.position=p;a.opening_stashed=a.opening_received=a.shoot_unlocked=True
        for b in self.e.arrows.values():self.e._ground(b,(31,19,0))
        self.co=self.e.supply_coordinator=LocalSupplyCoordinator(self.e)

    def arrow(self,p):
        b=next(b for b in self.e.arrows.values() if b.state=='ground' and b.position[0]>30)
        self.e._ground(b,(*p,0));return b

    def test_professional_pickup_and_nock_not_slowed(self):
        self.carry(self.a,1);self.e._request_nock(self.a)
        self.assertLess(self.a.reload_left,.2);self.assertLess(self.a.pickup_required_s,.15)

    def test_minimum_gap_enforced_at_release_not_only_policy(self):
        a=self.ready(self.a,2);act=Action(aim=(27,12,1),aim_key='defense_2',interaction='shoot')
        self.e._release(a,act);self.assertEqual(self.e.counts['shot'],1)
        a.bow_state='ready';a.nocked_arrow=a.inventory[0];a.aim_elapsed=10
        self.e.t=3.79;self.e._release(a,act);self.assertEqual(self.e.counts['shot'],1)
        self.e.t=3.81;self.e._release(a,act);self.assertEqual(self.e.counts['shot'],2)

    def test_style_controls_deliberate_aim_without_lowering_skill(self):
        pairs=[(a.player_model['style']['aim_patience'],a.human_profile['personal_aim_s']) for a in self.e.agents.values()]
        self.assertGreater(max(v for _,v in pairs),2.8)
        for (p,v),(q,w) in zip(sorted(pairs),sorted(pairs)[1:]):self.assertLessEqual(v,w)

    def test_far_shots_have_tight_but_nonzero_scatter(self):
        a=self.ready(self.a);a.aim_key='defense_2';a.steady_aim_s=2
        origin=(5,12,1.25);target=(27,12,.9);misses=[];speeds=[]
        for _ in range(150):
            v=self.e._launch_velocity(a,origin,target);drag=self.c['physics']['linear_drag_s_inv']
            t=-math.log(1-drag*(target[0]-origin[0])/v[0])/drag
            q,_=advance_arrow(origin,v,t,9.81,drag);misses.append(abs(q[1]-12));speeds.append(math.sqrt(sum(x*x for x in v))/.3048)
        self.assertLess(sorted(misses)[142],.4)
        self.assertGreater(statistics.stdev(misses),.02)
        self.assertTrue(all(115<v<130 for v in speeds))

    def test_equipment_speed_still_changes_flight(self):
        a=self.ready(self.a);a.human_profile['muzzle_speed_fps']=139.6
        v=self.e._launch_velocity(a,(5,12,1.25),(27,12,.9))
        self.assertGreater(math.sqrt(sum(x*x for x in v))/.3048,132)

    def test_no_probability_save_for_direct_contact(self):
        self.assertFalse(self.e._try_dodge(self.a,None,Action()))

    def test_reassessment_stops_immediate_next_aim(self):
        a=self.ready(self.a);self.e.t=12;a.last_shot_at=11.5
        p=SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),a.id,123)
        act=p(self.e.get_observation(a.id))
        self.assertIsNone(act.aim);self.assertNotEqual(act.interaction,'shoot')

    def test_cover_takes_reachable_arrow_behind_it(self):
        a=self.e.agents['attack_1'];self.supply_setup([(a,(7.4,15.45))])
        b=self.arrow((5.4,15.45));self.co.refresh('attack')
        self.assertEqual(self.e.jobs[a.id]['arrow'],b.id)

    def test_far_low_lane_arrow_does_not_pull_high_flank(self):
        a=self.e.agents['attack_0'];self.supply_setup([(a,(6.8,18))]);self.arrow((4,3))
        self.co.refresh('attack');self.assertNotIn(a.id,self.e.jobs)

    def test_assignment_prefers_local_empty_player_over_id_order(self):
        high=self.e.agents['attack_2'];low=self.e.agents['attack_3']
        self.supply_setup([(high,(5.2,12)),(low,(5.8,8.2))]);b=self.arrow((5.3,7))
        self.co.refresh('attack');self.assertEqual(self.e.jobs[low.id]['arrow'],b.id)
        self.assertNotIn(high.id,self.e.jobs)

    def test_role_change_updates_recovery_lane(self):
        a=self.a;a.role='revive_lane';self.supply_setup([(a,(7.2,2.15))]);b=self.arrow((5.7,2))
        self.co.refresh('attack');self.assertEqual(self.e.jobs[a.id]['arrow'],b.id)

    def test_only_own_arrow_is_never_given_away(self):
        donor=self.a;receiver=self.e.agents['attack_1']
        self.supply_setup([(donor,(5.5,14)),(receiver,(7.4,15.45))]);self.carry(donor,1)
        self.co.refresh('attack');self.assertNotIn('attack',self.co.contracts)

    def test_no_empty_courier_fetches_for_another_empty_player(self):
        donor=self.a;receiver=self.e.agents['attack_1']
        self.supply_setup([(donor,(5.5,14)),(receiver,(7.4,15.45))]);self.arrow((4.5,14))
        self.co.refresh('attack');self.assertNotIn('attack',self.co.contracts)
        self.assertEqual(self.e.jobs[donor.id]['kind'],'collect')

    def test_real_spare_can_be_sent_to_local_cover(self):
        donor=self.a;receiver=self.e.agents['attack_1']
        self.supply_setup([(donor,(5.5,14)),(receiver,(7.4,15.45))]);self.carry(donor,2)
        self.co.refresh('attack');self.assertEqual(self.co.contracts['attack']['donor'],donor.id)
        self.assertFalse(self.co.contracts['attack']['courier'])

    def test_fast_local_pickup_cancels_unthrown_delivery(self):
        donor=self.a;receiver=self.e.agents['attack_1']
        self.supply_setup([(donor,(5.5,14)),(receiver,(7.4,15.45))]);self.carry(donor,2)
        self.co.refresh('attack');b=self.arrow((7.1,15.45));self.co.refresh('attack')
        self.assertNotIn('attack',self.co.contracts);self.assertEqual(self.e.jobs[receiver.id]['arrow'],b.id)

    def test_spare_delivery_does_not_cross_opposite_lanes(self):
        donor=self.a;receiver=self.e.agents['attack_4']
        self.supply_setup([(donor,(5.5,14)),(receiver,(7.4,5))]);self.carry(donor,2)
        self.co.refresh('attack');self.assertNotIn('attack',self.co.contracts)

    def test_first_seen_arrow_still_requires_reaction_and_step_is_bounded(self):
        a=self.ready(self.a);p=SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),a.id,123)
        obs=self.e.get_observation(a.id);obs['time']=1
        obs['flying_arrows']=[dict(id=999,team='defense',released_at=.5,position=(15,12,1.1),velocity=(-25,0,0))]
        self.assertFalse(p._compact_evade(obs,(0,0),False)[2])
        obs['time']+=obs['self']['reaction_s']+.01
        self.assertTrue(p._compact_evade(obs,(0,0),False)[2])
        speed=math.hypot(*p.evade_action.move)*self.c['physics']['move_speed_m_s']
        self.assertLessEqual(speed,4.2);self.assertLessEqual(speed*.32,.69)

if __name__=='__main__':unittest.main()
