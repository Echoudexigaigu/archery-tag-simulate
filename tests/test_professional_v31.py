import json,math,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.tactical_environment import SuzhouEnvironment
from archery_tag_balance.tactical_policy import SuzhouPolicy
from archery_tag_balance.tactical_entities import TacticalAction,positions
from archery_tag_balance.entities import Action
from archery_tag_balance.policies import Navigator


class ProfessionalTempo(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'configs/suzhou_2026.json').read_text())
        self.e=SuzhouEnvironment(self.c);self.e.reset(1000,record=True)
        self.a=self.e.agents['attack_2']

    def carry(self,n=1):
        for _ in range(n):
            b=next(b for b in self.e.arrows.values() if b.state=='ground')
            self.e._carry(b,self.a);self.e._picked_up(self.a,b)

    def policy(self):return SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),self.a.id,33)

    def test_opening_three_arrow_bundle_is_one_atomic_grab(self):
        a=self.a;a.position=self.e.opening_pile(a)
        self.e.step({a.id:Action(interaction='pickup',crouch=True)},observe=False)
        self.assertEqual(len(a.inventory),3);self.assertEqual(self.e.counts['opening_bundle'],1)
        self.assertEqual(len({e['t'] for e in self.e.events if e['kind']=='pickup'}),1)
        for _ in range(8):self.e.step({a.id:Action(interaction='pickup')},observe=False)
        self.assertEqual(len(a.inventory),3);self.e.assert_invariants()

    def test_ordinary_ground_pickup_finishes_without_long_bar(self):
        a=self.a;a.position=(5,12);a.opening_received=a.opening_stashed=a.shoot_unlocked=True
        b=next(iter(self.e.arrows.values()));self.e._ground(b,(5.4,12,0))
        for _ in range(8):self.e.step({a.id:TacticalAction(interaction='pickup',pickup_id=b.id,crouch=True)},observe=False)
        self.assertIn(b.id,a.inventory);self.assertLessEqual(self.e.t,.2)

    def test_fast_nock_keeps_independent_personal_aim_time(self):
        self.carry();self.e._request_nock(self.a)
        self.assertLessEqual(self.a.reload_left,.2)
        self.assertGreaterEqual(self.a.human_aim_s,.2)
        for _ in range(9):self.e.step({},observe=False)
        self.assertEqual(self.a.bow_state,'ready')

    def test_release_does_not_leave_legacy_reload_wait(self):
        self.carry(2);a=self.a;a.position=(5,12);a.bow_state='ready';a.nocked_arrow=a.inventory[0];a.aim_elapsed=10
        self.e._release(a,Action(aim=(27,12,1),aim_key='defense_2',interaction='shoot'))
        self.assertEqual(self.e.counts['shot'],1);self.assertEqual(a.reload_left,0)
        self.e._request_nock(a);self.assertLessEqual(a.reload_left,.2)

    def test_loaded_bow_keeps_professional_mobility(self):
        self.carry();bare=self.e._movement_speed(self.a)
        self.a.bow_state='ready';self.a.nocked_arrow=self.a.inventory[0]
        self.assertGreater(self.e._movement_speed(self.a)/bare,.93)

    def test_every_quiet_branch_can_be_interrupted_by_visible_arrow(self):
        self.carry();a=self.a;a.opening_stashed=True;a.position=(5.2,12)
        for branch in ['empty_bow','pass','no_target']:
            with self.subTest(branch=branch):
                p=self.policy();obs=self.e.get_observation(a.id)
                if branch=='pass':
                    obs['job']={'kind':'relay','receiver':'attack_1','quota':2}
                    next(f for f in obs['team_roster'] if f['id']=='attack_1')['position']=(7,12)
                elif branch=='no_target':
                    obs['self']['bow_state']='ready';p._targets=lambda obs:None
                obs['time']=1;obs['flying_arrows']=[dict(id=999,team='defense',released_at=.5,position=(15,12,1),velocity=(-25,0,0))]
                self.assertFalse(p._act(obs).evasion_kind)
                obs['time']=1+obs['self']['reaction_s']+.01
                self.assertIn(p._act(obs).evasion_kind,['sidestep','duck'])

    def test_local_footwork_stays_near_station_and_keeps_aiming(self):
        self.carry();a=self.a;a.opening_stashed=True;a.bow_state='ready';a.nocked_arrow=a.inventory[0]
        anchor=positions(self.c,a.team,a.role)[0];a.position=anchor;p=self.policy()
        obs=self.e.get_observation(a.id);obs['time']=2
        _,hold,_=p._positions(obs);self.assertLess(math.dist(anchor,hold),.3)
        target=('defense_2',(27,12,1),None,22)
        p._targets=lambda obs:target;p._aim=lambda obs,target:target[1];p._clear_arc=lambda *args:True
        action=p._role_action(obs)
        self.assertIsNotNone(action.aim);self.assertGreater(math.hypot(*action.move),0)

    def test_defensive_action_moves_body_and_still_costs_stamina(self):
        self.carry();a=self.a;a.opening_stashed=True;a.position=(5.2,12)
        p=self.policy();obs=self.e.get_observation(a.id);obs['time']=1
        obs['flying_arrows']=[dict(id=999,team='defense',released_at=.5,position=(15,12,1),velocity=(-25,0,0))]
        p._act(obs);obs['time']+=obs['self']['reaction_s']+.01
        action=p._act(obs);start=a.position
        for _ in range(8):self.e.step({a.id:action},observe=False)
        self.assertGreater(math.dist(start,a.position),.2)
        self.assertLess(a.stamina,1);self.assertGreater(a.movement_dodge_ready_at,self.e.t)


if __name__=='__main__':unittest.main()
