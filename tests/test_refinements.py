import json,sys,unittest,copy
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.suzhou import SuzhouEnvironment
from archery_tag_balance.responsive_policy import SuzhouPolicy
from archery_tag_balance.policies import Navigator
from archery_tag_balance.entities import Action
from archery_tag_balance.geometry import ballistic_velocity
from archery_tag_balance.varied_environment import landing_time


class Refinements(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'configs/suzhou_2026.json').read_text(encoding='utf-8'))
        self.e=SuzhouEnvironment(self.c);self.e.reset(1000,record=True)
        self.nav=Navigator(self.c,self.e.navigation_obstacles)

    def policy(self,aid='attack_2'):
        return SuzhouPolicy(self.c,self.nav,aid,123)

    def test_confirmed_shapes_and_height(self):
        for o in self.e.obstacles:
            if o.id.endswith('high'):self.assertEqual(o.size,(1.1,1.1,1.5))
            else:self.assertEqual(o.size,(.8,1.2,.8))
        self.assertEqual(self.c['suzhou']['no_shoot_x_bounds_m'],[11,21])
        self.assertEqual(self.c['suzhou']['revive_rack']['position_xyz_m'][:2],[16,2])

    def test_disk_dimensions_and_center_weight(self):
        for spec in self.c['skirmish_racks']:
            self.assertEqual(spec['spot_radii_m'],[.07]*4+[.06])
            self.assertEqual(spec['spot_weights'],[1,1,1,1,2])
            self.assertEqual(spec['offsets_hv_m'][0],[-.145,-.145])

    def test_rear_center_holds_outside_no_shoot_zone(self):
        for team in ['attack','defense']:
            for i in [2,3]:
                aid=f'{team}_{i}';policy=self.policy(aid);obs=self.e.get_observation(aid)
                _,hold,_=policy._positions(obs)
                depth=hold[0] if team=='attack' else 32-hold[0]
                self.assertGreaterEqual(depth,5);self.assertLessEqual(depth,6)

    def test_opening_gathers_three_then_carries_to_cache(self):
        a=self.e.agents['attack_2'];a.position=self.e.opening_pile(a)
        policy=self.policy(a.id)
        for i in range(3):
            obs=self.e.get_observation(a.id);act=policy(obs)
            self.assertEqual(act.interaction,'pickup')
            b=next(b for b in self.e.arrows.values() if b.state=='ground')
            self.e._carry(b,a);self.e._picked_up(a,b)
        act=policy(self.e.get_observation(a.id))
        self.assertEqual(policy.intent['kind'],'cache')
        self.assertNotEqual(act.move,(0,0));self.assertEqual(len(a.inventory),3)
        a.position=self.e.cache_positions[a.id]
        for _ in range(4):self.e._drop(a)
        self.assertTrue(a.opening_stashed);self.assertEqual(len(a.inventory),1)
        self.assertEqual(self.e.counts['stash'],2)
        self.assertLess(a.position[0],5)

    def test_intent_names_assigned_arrow_not_hidden_position(self):
        a=self.e.agents['attack_2'];a.opening_stashed=True;a.opening_received=True;a.shoot_unlocked=True
        obs=self.e.get_observation(a.id)
        obs['supply_assignment']=dict(id=17,position=(7,10,0))
        p=self.policy(a.id);p(obs)
        self.assertEqual(p.intent,dict(kind='pickup',goal=(7,10),arrow=17))

    def test_visible_arrow_requires_personal_reaction_delay(self):
        a=self.e.agents['attack_2'];a.position=(5,12);p=self.policy(a.id)
        obs=self.e.get_observation(a.id);obs['time']=1
        obs['flying_arrows']=[dict(id=999,team='defense',released_at=.5,position=(15,12,1),velocity=(-25,0,0))]
        self.assertFalse(p._compact_evade(obs,(0,0),False)[2])
        obs['time']=1+obs['self']['reaction_s']+.01
        result=p._compact_evade(obs,(0,0),False)
        self.assertTrue(result[2]);self.assertIn(p.evade_action.evasion_kind,['sidestep','duck'])
        if p.evade_action.evasion_kind=='sidestep':
            speed=(sum(x*x for x in p.evade_action.move)**.5)*self.c['physics']['move_speed_m_s']
            self.assertGreater(speed,1.3);self.assertLessEqual(speed,4.2)
            # V6 extends the physical step, while keeping it within configured
            # human displacement and the regular movement-speed limit.
            self.assertLessEqual(speed*self.c['evasion']['movement_duration_s'],max(self.c['motion_refinement']['sidestep_range_m'])+.01)

    def test_low_aim_is_not_overwritten_by_torso_in_aim_refresh(self):
        p=self.policy();obs=self.e.get_observation('attack_2')
        enemy=dict(id='defense_2',position=(27,12),velocity=(0,0),height=1.7,status='active')
        target=('defense_2',(27,12,.36),enemy,22)
        self.assertEqual(p._aim(obs,target)[2],.36)

    def test_low_trajectory_reaches_ground_earlier(self):
        p=self.c['physics'];origin=(6,12,1.25);speed=122.5*.3048
        low=ballistic_velocity(origin,(24,12,.3),speed,p['gravity_m_s2'],p['linear_drag_s_inv'],4)
        torso=ballistic_velocity(origin,(24,12,1.0),speed,p['gravity_m_s2'],p['linear_drag_s_inv'],4)
        tl=landing_time(origin,low,p['gravity_m_s2'],p['linear_drag_s_inv'],4)
        tt=landing_time(origin,torso,p['gravity_m_s2'],p['linear_drag_s_inv'],4)
        self.assertLess(tl,tt)

    def test_pose_expansion_not_implemented(self):
        self.assertEqual(self.c['physics']['crouched_height_m'],.85)
        self.assertEqual(self.c['physics']['player_height_m'],1.7)
        self.assertFalse(hasattr(self.e.agents['attack_0'],'prone'))

if __name__=='__main__':unittest.main()
