import sys,json,unittest,math
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.tactical_environment import SuzhouEnvironment
from archery_tag_balance.tactical_policy import SuzhouPolicy
from archery_tag_balance.tactical_entities import TacticalAction,ROLES
from archery_tag_balance.entities import Action,Status
from archery_tag_balance.policies import Navigator


class TacticalV3(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'configs/suzhou_2026.json').read_text());self.e=SuzhouEnvironment(self.c);self.e.reset(1000,record=True)
        self.rewards=defaultdict(float)

    def carry(self,a,n):
        for _ in range(n):
            b=next(b for b in self.e.arrows.values() if b.state=='ground');self.e._carry(b,a);self.e._picked_up(a,b)
        return a

    def tick(self,n=1):
        for _ in range(n):self.e.step({},observe=False);self.e.assert_invariants()

    def kill(self,aid):self.e._eliminate(self.e.agents[aid],self.e.agents['defense_0' if aid.startswith('attack') else 'attack_0'],self.rewards)

    def test_fixed_roles_have_same_geographic_meaning_for_both_teams(self):
        for team in ['attack','defense']:
            self.assertEqual([self.e.agents[f'{team}_{i}'].role for i in range(6)],list(ROLES))
            self.assertEqual(self.e.agents[team+'_0'].position[1],18)
            self.assertEqual(self.e.agents[team+'_5'].position[1],2)

    def test_pickup_does_not_automatically_nock(self):
        a=self.carry(self.e.agents['attack_2'],1)
        self.assertEqual(a.bow_state,'empty');self.assertEqual(a.reload_left,0);self.assertIsNone(a.nocked_arrow)

    def test_nocking_has_duration_then_becomes_ready(self):
        a=self.carry(self.e.agents['attack_2'],1);self.e._request_nock(a)
        self.assertEqual(a.bow_state,'nocking');self.assertGreater(a.reload_left,0)
        self.tick(500)
        self.assertEqual(a.bow_state,'ready');self.assertEqual(a.nocked_arrow,a.inventory[0])

    def test_cannot_shoot_with_empty_bow(self):
        a=self.carry(self.e.agents['attack_2'],1);a.position=(5,12);a.aim_elapsed=10
        self.e._release(a,Action(aim=(27,12,1),aim_key='defense_2',interaction='shoot'))
        self.assertEqual(self.e.counts['shot'],0)

    def test_ready_bow_shoots_once_then_needs_nocking_again(self):
        a=self.carry(self.e.agents['attack_2'],2);a.position=(5,12);a.bow_state='ready';a.nocked_arrow=a.inventory[0];a.aim_elapsed=10
        action=Action(aim=(27,12,1),aim_key='defense_2',interaction='shoot')
        self.e._release(a,action);a.reload_left=0;a.aim_elapsed=10;self.e._release(a,action)
        self.assertEqual(self.e.counts['shot'],1);self.assertEqual(a.bow_state,'empty');self.assertEqual(len(a.inventory),1)

    def test_four_total_requires_bow_arrow_and_three_hand_arrows(self):
        a=self.carry(self.e.agents['attack_2'],3);b=next(b for b in self.e.arrows.values() if b.state=='ground')
        a.position=b.position[:2];self.assertFalse(self.e._pickup_allowed(a,b))
        self.e._request_nock(a);self.assertTrue(self.e._pickup_allowed(a,b))
        self.e._carry(b,a);self.assertEqual(len(a.inventory),4)
        other=next(b for b in self.e.arrows.values() if b.state=='ground');self.assertFalse(self.e._pickup_allowed(a,other))
        self.e.assert_invariants()

    def test_loaded_movement_and_extra_arrow_burden(self):
        a=self.carry(self.e.agents['attack_2'],1);bare=self.e._movement_speed(a)
        a.bow_state='ready';a.nocked_arrow=a.inventory[0];loaded=self.e._movement_speed(a)
        self.carry(a,2);heavy=self.e._movement_speed(a)
        self.assertGreater(bare,loaded);self.assertGreater(loaded,heavy)

    def test_hand_throw_has_cooldown_and_held_action_does_not_repeat(self):
        a=self.carry(self.e.agents['attack_2'],3);a.position=(5,12);friend=self.e.agents['attack_1'];friend.position=(8,12)
        act=TacticalAction(interaction='throw',throw_to=friend.id,token=77)
        for _ in range(6):self.e.step({a.id:act},observe=False)
        self.assertEqual(self.e.counts['arrow_pass'],1);self.assertEqual(len(a.inventory),2)

    def test_loaded_bow_cannot_throw(self):
        a=self.carry(self.e.agents['attack_2'],2);a.bow_state='ready';a.nocked_arrow=a.inventory[0]
        self.e.agents['attack_1'].position=(1,12);a.position=(2,12)
        self.e._throw_from_agent(a,'attack_1');self.assertEqual(self.e.counts['arrow_pass'],0)

    def test_thrown_arrow_is_nonlethal_even_through_body(self):
        a=self.carry(self.e.agents['attack_2'],1);a.position=(5,12);self.e.agents['attack_1'].position=(8,12)
        self.e.agents['attack_3'].position=(6.4,12)
        self.e._throw_from_agent(a,'attack_1');self.tick(100)
        self.assertEqual(self.e.counts['hit'],0);self.assertEqual(self.e.agents['attack_3'].status,Status.ACTIVE)

    def test_death_pause_and_snapshot_discard_no_search_after_hit(self):
        a=self.carry(self.e.agents['attack_2'],2);a.position=(5,12);self.e.agents['attack_1'].position=(6.3,12)
        self.kill(a.id);initial=self.e.outside_positions[a.id];goals=[r['goal'] for r in self.e.pending_discards]
        self.e.agents['attack_1'].position=(13,18)
        self.assertEqual(goals,[r['goal'] for r in self.e.pending_discards]);self.assertEqual(len(a.inventory),0)
        self.tick(24)
        self.assertEqual(self.e.outside_positions[a.id],initial);self.assertEqual(self.e.out_stage[a.id],'hit')
        self.assertEqual(self.e.counts['death_discard'],2)
        self.tick(20);self.assertNotEqual(self.e.out_stage[a.id],'hit')

    def test_waiting_players_have_stable_separate_slots(self):
        for aid in ['attack_0','attack_1','attack_2']:self.kill(aid)
        for _ in range(1200):self.e.t+=.025;self.e._timers(.025)
        points=[self.e.outside_positions[aid] for aid in ['attack_0','attack_1','attack_2']]
        self.assertEqual(len(set(points)),3)
        self.assertTrue(all(math.dist(p,q)>.7 for i,p in enumerate(points) for q in points[:i]))

    def test_no_instant_global_revive_runner(self):
        for a in self.e.agents.values():a.opening_stashed=True
        self.carry(self.e.agents['attack_0'],1);self.carry(self.e.agents['attack_5'],1)
        self.kill('attack_2');self.e._update_rule_state();self.assertIsNone(self.e.revive_runner['attack'])
        self.e.t=1.2;self.e._update_rule_state();self.assertEqual(self.e.revive_runner['attack'],'attack_5')
        self.kill('attack_5');self.e.t=3;self.e._update_rule_state();self.assertNotEqual(self.e.revive_runner['attack'],'attack_0')

    def test_vacant_revive_lane_filled_by_center_after_delay(self):
        for a in self.e.agents.values():a.opening_stashed=True
        self.kill('attack_5');self.e._plan_roles('attack')
        self.assertNotIn('revive_lane',self.e.role_owners['attack'])
        self.e.t=5;self.e._plan_roles('attack')
        aid=self.e.role_owners['attack']['revive_lane'];self.assertIn(aid,['attack_2','attack_3'])
        self.assertEqual(self.e.agents['attack_0'].role,'high_flank')

    def test_busy_aiming_player_is_not_immediately_reassigned(self):
        for a in self.e.agents.values():a.opening_stashed=True
        self.kill('attack_5');self.e._plan_roles('attack')
        self.e.agents['attack_2'].aim_elapsed=1;self.e.agents['attack_3'].aim_elapsed=1
        self.e.t=5;self.e._plan_roles('attack');self.assertNotIn('revive_lane',self.e.role_owners['attack'])

    def test_returning_player_does_not_duplicate_replacement_role(self):
        for a in self.e.agents.values():a.opening_stashed=True
        self.kill('attack_5');self.e._plan_roles('attack')
        self.e.t=5;self.e._plan_roles('attack')
        replacement=self.e.role_owners['attack']['revive_lane']
        a=self.e.agents['attack_5'];self.e.out_stage[a.id]='returning'
        self.e.out_routes[a.id]=[];self.e.outside_positions[a.id]=a.spawn
        self.e.revive_queue['attack'].remove(a.id);self.e.revive_approved.add(a.id)
        self.e._advance_out_route(a,.025)
        self.assertEqual(a.status,Status.ACTIVE)
        self.assertEqual(self.e.agents[replacement].role,'revive_lane')
        self.assertTrue(a.role.startswith('center'))
        self.e.assert_invariants()

    def test_cover_edge_arrow_has_reachable_hand_approach(self):
        b=next(iter(self.e.arrows.values()));self.e._ground(b,(7.91,15.45,0))
        points=self.e.pickup_points(b,'attack');self.assertTrue(points)
        a=self.e.agents['attack_2'];a.position=min(points,key=lambda p:math.dist(p,(6,15.45)))
        a.opening_stashed=a.shoot_unlocked=a.opening_received=True
        act=TacticalAction(interaction='pickup',pickup_id=b.id,crouch=True,token=1)
        for _ in range(100):self.e.step({a.id:act},observe=False)
        self.assertIn(b.id,a.inventory)

    def test_head_on_players_can_yield_without_overlap(self):
        a,b=self.e.agents['attack_2'],self.e.agents['attack_3'];a.position=(5,12);b.position=(5.8,12)
        start=(a.position,b.position)
        for _ in range(80):
            self.e.step({a.id:Action(move=(1,0)),b.id:Action(move=(-1,0))},observe=False)
            self.assertGreaterEqual(math.dist(a.position,b.position),.5-1e-8)
        self.assertGreater(math.dist(a.position,start[0])+math.dist(b.position,start[1]),1)

    def test_pickup_completes_inside_navigation_arrival_tolerance(self):
        a=self.e.agents['attack_2'];a.position=(5.96,12);a.opening_stashed=True
        b=next(iter(self.e.arrows.values()));self.e._ground(b,(6.64,12,0))
        job={'kind':'collect','arrow':b.id,'approach':(6,12),'quota':1}
        p=SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),a.id,33)
        for _ in range(25):
            action=p._collect(self.e.get_observation(a.id),job)
            for _ in range(round(self.c['policy']['decision_interval_s']/self.c['time']['dt_s'])):self.e.step({a.id:action},observe=False)
            if b.id in a.inventory:break
        self.assertIn(b.id,a.inventory)

    def test_pickup_approach_keeps_teammate_steering_margin(self):
        a=self.e.agents['attack_2'];a.position=(5,12);a.opening_stashed=True
        friend=self.e.agents['attack_3'];friend.position=(6.2,12)
        b=next(iter(self.e.arrows.values()));self.e._ground(b,(6.5,12,0))
        self.e._refresh_supply('attack');goal=self.e.jobs[a.id]['approach']
        self.assertGreater(math.dist(goal,friend.position),.72)

    def test_pickup_without_progress_replans_even_when_stationary(self):
        a=self.e.agents['attack_2'];a.position=(5,12);a.opening_stashed=True
        bid=next(iter(self.e.arrows));self.e.jobs[a.id]={'kind':'collect','arrow':bid,'approach':(6,12)}
        self.e.supply_claims[a.team][a.id]=bid
        self.e.next_plan_at=self.e.supply_scan_at=100;self.e.supply_dirty=False
        for _ in range(27):self.e.t+=.1;self.e._update_rule_state()
        self.assertGreater(self.e.supply_avoid.get((a.id,bid),0),self.e.t)
        self.assertGreaterEqual(self.e.counts['stalled_replans'],1)

    def test_toe_contact_allows_quick_release_but_outside_does_not(self):
        a=self.carry(self.e.agents['attack_5'],1);a.bow_state='ready';a.nocked_arrow=a.inventory[0]
        a.position=(9.74,2);self.assertTrue(self.e.on_revive_pad(a));a.snap_revive=True;a.aim_elapsed=.15
        self.kill('attack_2')
        self.e._release(a,TacticalAction(aim=(16,1.855,.605),aim_key='rack:revive:0',interaction='shoot',quick_shot=True))
        self.assertEqual(self.e.counts['shot'],1)
        self.assertEqual(self.e.events[-1]['kind'],'release_cue')

    def test_shot_runout_deviation_is_smaller_than_hand_throw(self):
        self.assertLess(self.c['ground_runout']['direction_sd_degrees'],self.c['v3']['toss_direction_sd_degrees'])

    def test_personal_carry_preference_generates_extra_collection(self):
        a=self.carry(self.e.agents['attack_2'],1);a.opening_stashed=True;a.human_profile['carry_preference']=2
        a.position=(5,12);b=next(b for b in self.e.arrows.values() if b.state=='ground');self.e._ground(b,(5.6,12,0))
        self.e._refresh_supply('attack')
        self.assertEqual(self.e.jobs[a.id]['quota'],2);self.assertIn('arrow',self.e.jobs[a.id])

    def test_relay_does_not_disarm_for_already_armed_recipient(self):
        a=self.carry(self.e.agents['attack_2'],1);a.opening_stashed=True;a.position=(5,12)
        self.e.agents['attack_1'].position=(8,12)
        b=next(b for b in self.e.arrows.values() if b.state=='ground');self.e._ground(b,(5.2,12,0))
        obs=self.e.get_observation(a.id);obs['job']={'kind':'relay','receiver':'attack_1','quota':2,'arrow':b.id,'approach':a.position,'goal':(8,12),'throw_from':a.position}
        next(f for f in obs['team_roster'] if f['id']=='attack_1')['ammo']=1
        p=SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),a.id,33)
        action=p._logistics(obs);self.assertIsNone(action)

if __name__=='__main__':unittest.main()
