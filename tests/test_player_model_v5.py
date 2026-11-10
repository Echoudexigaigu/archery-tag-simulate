import copy,csv,importlib.util,json,math,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.player_model import profile,Attention,SKILLS,STYLE
from archery_tag_balance.personality_environment import SuzhouEnvironment
from archery_tag_balance.personality_policy import SuzhouPolicy
from archery_tag_balance.entities import Action
from archery_tag_balance.policies import Navigator
spec=importlib.util.spec_from_file_location('import_player_data',ROOT/'scripts/import_player_data.py');importer=importlib.util.module_from_spec(spec);spec.loader.exec_module(importer)


class PlayerModelV5(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'configs/suzhou_2026.json').read_text(encoding='utf-8'))
        self.c['player_profiles']=json.loads((ROOT/'configs/player_profiles_demo.json').read_text(encoding='utf-8'))
        self.e=SuzhouEnvironment(self.c);self.e.reset(1000,record=True);self.a=self.e.agents['attack_2']

    def carry(self,n=1):
        for _ in range(n):
            b=next(b for b in self.e.arrows.values() if b.state=='ground');self.e._carry(b,self.a);self.e._picked_up(self.a,b)

    def view(self):
        self.a.position=(5.2,12);obs=self.e.get_observation(self.a.id);obs['time']=.1;obs['enemies']=[];obs['flying_arrows']=[]
        return obs

    def test_demo_skills_equal_but_styles_differ(self):
        specs=list(self.c['player_profiles'].values());self.assertEqual(len({json.dumps(p['skills'],sort_keys=True) for p in specs}),1)
        self.assertGreater(len({json.dumps(p['style'],sort_keys=True) for p in specs}),1)
        self.assertTrue(all(p['is_demo'] for p in specs))

    def test_invalid_scores_rejected(self):
        for value in [float('nan'),float('inf'),-.1,1.1,True,'80']:
            with self.subTest(value=value),self.assertRaises(ValueError):profile({'skills':{'reaction':value}})

    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValueError):profile({'style':{'magic':.8}})

    def test_skill_and_style_are_independent_inputs(self):
        a=profile({'style':{'risk_tolerance':.1}});b=profile({'style':{'risk_tolerance':.9}})
        self.assertEqual(a['skills'],b['skills']);self.assertNotEqual(a['style'],b['style'])

    def test_side_arrow_visible_but_not_noticed_until_turn(self):
        obs=self.view();obs['flying_arrows']=[dict(id=99,team='defense',released_at=0,position=(5.2,17,1),velocity=(0,-25,0))]
        att=Attention(profile(),self.a.team,2)
        self.assertEqual(len(att.perceive(obs)['flying_arrows']),0)
        self.assertEqual(att.last_view['visible_arrows'],1)
        att.focus=math.pi/2
        self.assertEqual(len(att.perceive(obs)['flying_arrows']),1)

    def test_front_arrow_can_be_noticed_without_random_roll(self):
        obs=self.view();obs['flying_arrows']=[dict(id=99,team='defense',released_at=0,position=(15,12,1),velocity=(-25,0,0))]
        att=Attention(profile(),self.a.team,2)
        self.assertEqual(len(att.perceive(obs)['flying_arrows']),1)

    def test_occluded_arrow_is_not_retained_as_xray_information(self):
        obs=self.view();obs['flying_arrows']=[dict(id=99,team='defense',released_at=0,position=(15,12,1),velocity=(-25,0,0))]
        att=Attention(profile(),self.a.team,2);att.perceive(obs)
        obs['flying_arrows']=[];self.assertEqual(att.perceive(obs)['flying_arrows'],[]);self.assertEqual(len(att.noticed),0)

    def test_opponent_specific_concern_changes_subjective_pressure(self):
        obs=self.view();obs['enemies']=[dict(id='defense_0',player_id='P07',position=(25,12),aiming=True)]
        low=Attention(profile({'opponent_beliefs':{'P07':.1}}),'attack',2)
        high=Attention(profile({'opponent_beliefs':{'P07':.9}}),'attack',2)
        low.perceive(obs);high.perceive(obs)
        self.assertGreater(high.last_view['pressure'],low.last_view['pressure'])

    def test_risk_tolerance_changes_decision_margin_without_skill_change(self):
        obs=self.view();low=Attention(profile({'style':{'risk_tolerance':.1}}),'attack',2);high=Attention(profile({'style':{'risk_tolerance':.9}}),'attack',2)
        low.last_view={'pressure':.8};high.last_view={'pressure':.8}
        self.assertLess(low.risk(obs),high.risk(obs));self.assertEqual(low.p['skills'],high.p['skills'])

    def test_unseen_enemy_does_not_raise_pressure(self):
        obs=self.view();obs['enemies']=[dict(id='defense_0',player_id='P07',position=(5.2,18),aiming=True)]
        att=Attention(profile(),'attack',2);att.perceive(obs);self.assertEqual(att.last_view['pressure'],0)

    def test_rates_are_missing_when_there_are_no_trials(self):
        row=next(r for r in self.e.behavior.rows() if r['agent']==self.a.id)
        self.assertIsNone(row['intended_body_hit_rate']);self.assertIsNone(row['scoreboard_knockdown_rate'])

    def test_unresolved_arrow_not_treated_as_a_miss(self):
        self.carry();a=self.a;a.position=(5.2,12);a.bow_state='ready';a.nocked_arrow=a.inventory[0];a.aim_elapsed=10
        self.e._release(a,Action(aim=(25,12,1),aim_key='defense_2',interaction='shoot'))
        row=next(r for r in self.e.behavior.rows() if r['agent']==a.id)
        self.assertEqual(row['body_shots'],1);self.assertEqual(row['body_shots_resolved'],0);self.assertIsNone(row['intended_body_hit_rate'])

    def test_body_contact_is_linked_to_released_arrow(self):
        self.carry();a=self.a;a.position=(5.2,12);a.bow_state='ready';a.nocked_arrow=a.inventory[0];a.aim_elapsed=10;bid=a.nocked_arrow
        self.e._release(a,Action(aim=(25,12,1),aim_key='defense_2',interaction='shoot'))
        self.e._on_body_contact(self.e.agents['defense_2'],self.e.arrows[bid],a,True)
        row=next(r for r in self.e.behavior.rows() if r['agent']==a.id)
        self.assertEqual(row['intended_body_hits'],1);self.assertEqual(row['intended_body_hit_rate'],1)

    def test_friendly_block_is_a_resolved_unsuccessful_shot(self):
        self.carry();a=self.a;a.position=(5.2,12);a.bow_state='ready';a.nocked_arrow=a.inventory[0];a.aim_elapsed=10;bid=a.nocked_arrow
        self.e._release(a,Action(aim=(25,12,1),aim_key='defense_2',interaction='shoot'))
        self.e._on_body_contact(self.e.agents['attack_3'],self.e.arrows[bid],a,True)
        row=next(r for r in self.e.behavior.rows() if r['agent']==a.id)
        self.assertEqual(row['body_shots_resolved'],1);self.assertEqual(row['intended_body_hit_rate'],0)

    def test_csv_export_keeps_simulation_source(self):
        self.e.step({},observe=False)
        with tempfile.TemporaryDirectory(dir=ROOT/'reports') as d:
            self.assertTrue(Path(d).resolve().is_relative_to(ROOT.resolve()))
            self.e.behavior.export(d)
            with (Path(d)/'players.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),12);self.assertTrue(all(r['source']=='simulation' for r in rows))

    def test_same_skill_different_style_keeps_raw_launch_noise_equal(self):
        self.c['human_shooting']['poor_release_probability']=0
        first=self.e.agents['attack_1'];second=self.e.agents['defense_1']
        self.assertNotEqual(first.player_model['style'],second.player_model['style'])
        for a in [first,second]:a.aim_key='defense_2';a.steady_aim_s=0;a.human_profile['muzzle_speed_fps']=122.5
        state=self.e.rng.getstate();v1=self.e._launch_velocity(first,(5,12,1.25),(25,12,1))
        self.e.rng.setstate(state);v2=self.e._launch_velocity(second,(5,12,1.25),(25,12,1))
        self.assertEqual(v1,v2)

    def test_glance_returns_to_previous_focus(self):
        obs=self.view();obs['time']=2
        att=Attention(profile(),'attack',0);att.perceive(obs)
        self.assertTrue(att.last_view['scanning']);self.assertNotEqual(att.focus,0)
        obs['time']=2.3;att.perceive(obs)
        self.assertFalse(att.last_view['scanning']);self.assertEqual(att.focus,0)

    def test_deliberate_aim_is_not_repeatedly_interrupted_by_scan_timer(self):
        obs=self.view();obs['time']=2;obs['self']['aim_elapsed']=1
        att=Attention(profile(),'attack',0);att.perceive(obs)
        self.assertFalse(att.last_view['scanning'])

    def test_target_skill_does_not_force_body_skill_to_match(self):
        self.c['human_shooting']['poor_release_probability']=0;a=self.a
        a.player_model['skills'].update(body_accuracy=.2,target_accuracy=.95)
        state=self.e.rng.getstate();a.aim_key='defense_2';self.e._launch_velocity(a,(5,12,1.25),(25,12,1));body=self.e.last_launch[a.id]['sigma']
        self.e.rng.setstate(state);a.aim_key='rack:defense:0';self.e._launch_velocity(a,(5,12,1.25),(25,12,1))
        self.assertLess(self.e.last_launch[a.id]['sigma'],body)

    def test_actual_flight_contact_updates_shot_outcome(self):
        from collections import defaultdict
        victim=self.e.agents['defense_2'];victim.position=(12,12)
        b=next(iter(self.e.arrows.values()));b.state='flying';b.shooter=self.a.id;b.position=(10,12,1);b.velocity=(20,0,0);b.flight_left=1
        self.e.behavior.shot(self.a,b.id,Action(aim=(12,12,1),aim_key=victim.id),{})
        points={aid:a.position for aid,a in self.e.agents.items()}
        self.e._fly(.15,points,points,{aid:Action() for aid in points},defaultdict(float))
        self.assertEqual(self.e.behavior.shots[-1]['outcome'],'body_contact')
        self.assertEqual(self.e.behavior.shots[-1]['contact_agent'],victim.id)

    def test_import_retains_unknown_fields_and_does_not_invent_zero(self):
        tables=dict(players=[{'player_id':'P01','alias':'test'}],skills=[{'player_id':'P01','body_accuracy':80,'source':'self'}],styles=[],beliefs=[],equipment=[])
        selected,pool=importer.import_rows(tables,{'attack_0':'P01'})
        self.assertEqual(selected['attack_0']['skills']['body_accuracy'],.8)
        self.assertNotIn('target_accuracy',selected['attack_0']['skills'])
        self.assertIn('skills.target_accuracy',selected['attack_0']['missing_fields'])

    def test_conflicting_sources_require_an_explicit_choice(self):
        tables=dict(players=[{'player_id':'P01'}],skills=[{'player_id':'P01','body_accuracy':80,'source':'self'},{'player_id':'P01','body_accuracy':50,'source':'peer'}],styles=[],beliefs=[],equipment=[])
        with self.assertRaises(ValueError):importer.import_rows(tables,{'attack_0':'P01'})
        selected,_=importer.import_rows(tables,{'attack_0':'P01'},source='self')
        self.assertEqual(selected['attack_0']['skills']['body_accuracy'],.8)

    def test_same_person_cannot_fill_two_lineup_slots(self):
        tables=dict(players=[{'player_id':'P01'}],skills=[],styles=[],beliefs=[],equipment=[])
        with self.assertRaises(ValueError):importer.import_rows(tables,{'attack_0':'P01','attack_1':'P01'})

    def test_attention_does_not_override_arrow_recovery_jobs(self):
        self.a.opening_stashed=True;self.a.position=(5.2,12)
        b=next(iter(self.e.arrows.values()));self.e._ground(b,(5.5,12,0))
        self.e._refresh_supply('attack');obs=self.e.get_observation(self.a.id)
        p=SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),self.a.id,33);p(obs)
        self.assertEqual(p.intent['kind'],'pickup')

    def test_risk_hold_reason_persists_until_reconsideration(self):
        a=self.e.agents['attack_1'];a.opening_stashed=True
        b=next(iter(self.e.arrows.values()));self.e._carry(b,a);self.e._picked_up(a,b)
        a.bow_state='ready';a.nocked_arrow=b.id;a.position=(7.47,15.45)
        p=SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),a.id,33)
        p.model=profile(a.player_model);p.attention=Attention(p.model,a.team,1)
        p.attention.last_view={'pressure':.9};p.phase='peek';p.peek_until=10
        obs=self.e.get_observation(a.id);obs['time']=2;p._role_action(obs)
        self.assertEqual(p.intent['kind'],'risk_hold')
        obs['time']=2.05;p._role_action(obs)
        self.assertEqual(p.intent['kind'],'risk_hold');self.assertLess(p.attention.last_view['risk_margin'],0)


if __name__=='__main__':unittest.main()
