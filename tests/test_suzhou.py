import copy,json,sys,unittest
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.suzhou import SuzhouEnvironment
from archery_tag_balance.entities import Action,Status


def env(seed=1000):
    c=json.loads((ROOT/'configs/suzhou_2026.json').read_text(encoding='utf-8'))
    c['roster']=json.loads((ROOT/'configs/roster.json').read_text(encoding='utf-8'))
    c['target_scoring']['knockdown_probability']=1
    e=SuzhouEnvironment(c);e.reset(seed,record=True)
    return e


class SuzhouRules(unittest.TestCase):
    def setUp(self):self.e=env();self.rewards=defaultdict(float)

    def kill(self,aid):
        self.e._eliminate(self.e.agents[aid],self.e.agents['attack_0' if aid.startswith('defense') else 'defense_0'],self.rewards)

    def hit_board(self,key,spot,shooter='attack_0',valid=True):
        e=self.e;b=next(b for b in e.arrows.values() if b.state=='ground')
        b.state='flying';b.shooter=shooter;b.position=e.skirmish_racks[key].spot(spot);b.velocity=(35,0,0);b.valid_revive_release=valid
        e._contact_skirmish_rack(b,(key,spot),b.position,self.rewards)
        return b

    def test_opening_has_36_arrows_on_own_frontlines_and_bows(self):
        e=self.e;self.assertEqual(len(e.arrows),36)
        self.assertEqual(sum(b.position[0]==9 for b in e.arrows.values()),18)
        self.assertEqual(sum(b.position[0]==23 for b in e.arrows.values()),18)
        self.assertTrue(all(a.has_bow and not a.shoot_unlocked for a in e.agents.values()))

    def test_first_pickup_unlocks_without_return_to_baseline(self):
        e=self.e;a=e.agents['attack_0'];a.position=e.opening_pile(a)
        b=next(iter(e.arrows.values()));e._carry(b,a);e._picked_up(a,b)
        self.assertTrue(a.shoot_unlocked);self.assertGreater(a.position[0],5);self.assertGreater(a.reload_left,0)

    def test_one_hit_out_and_no_timed_respawn(self):
        self.kill('defense_0');a=self.e.agents['defense_0']
        for _ in range(500):self.e._timers(.1)
        self.assertEqual(a.status,Status.ELIMINATED);self.assertEqual(a.lives,0);self.assertIsNone(a.respawn_at)

    def test_revive_fifo_and_no_instant_reentry(self):
        e=self.e;self.kill('attack_2');self.kill('attack_0')
        self.hit_board('revive',0,shooter='attack_1')
        self.assertEqual(e.revive_queue['attack'],['attack_0'])
        self.assertIn('attack_2',e.revive_approved)
        self.assertEqual(e.agents['attack_2'].status,Status.ELIMINATED)
        for _ in range(1000):e._timers(.05)
        self.assertEqual(e.agents['attack_2'].position,e.agents['attack_2'].spawn)
        self.assertEqual(e.agents['attack_2'].status,Status.ACTIVE)
        self.assertEqual(e.agents['attack_2'].lives,1)
        self.assertEqual(e.agents['attack_0'].status,Status.ELIMINATED)

    def test_cannot_bank_revives_without_casualty(self):
        self.hit_board('revive',0)
        self.assertTrue(all(self.e.skirmish_racks['revive'].standing))
        self.assertFalse(self.e.revive_approved)

    def test_wrong_pad_shot_does_not_revive_or_consume_disk(self):
        self.kill('attack_3');b=self.hit_board('revive',0,valid=False)
        self.assertTrue(self.e.skirmish_racks['revive'].standing[0])
        self.assertEqual(self.e.revive_queue['attack'],['attack_3'])
        self.assertEqual(b.state,'settling')

    def test_shared_revive_supply_for_both_sides(self):
        self.kill('attack_3');self.kill('defense_3')
        self.hit_board('revive',0,'attack_0');self.hit_board('revive',1,'defense_0')
        self.assertEqual(sum(self.e.skirmish_racks['revive'].standing),3)
        self.assertEqual(self.e.revive_approved,{'attack_3','defense_3'})

    def test_clear_scoring_rack_is_immediate_win_with_people_alive(self):
        for k in range(5):self.hit_board('defense',k)
        self.assertEqual(self.e._resolve_winner(),'attack');self.assertEqual(self.e.victory_reason,'target_clear')
        self.assertEqual(self.e.remaining_score('defense')['alive'],6)

    def test_timeout_uses_remaining_weighted_disks_and_people(self):
        e=self.e;e.t=240;e.scores['attack']['body']=999
        e.skirmish_racks['attack'].standing[0]=False
        self.assertEqual(e.remaining_score('attack')['total'],11)
        self.assertEqual(e.remaining_score('defense')['total'],12)
        self.assertEqual(e._resolve_winner(),'defense')

    def test_own_scoring_disk_loss_benefits_opponent(self):
        self.hit_board('attack',0,shooter='attack_0')
        self.assertFalse(self.e.skirmish_racks['attack'].standing[0])
        self.assertEqual(self.e.scores['defense']['target'],1)

    def test_full_elimination_wins_despite_remaining_revival_disks(self):
        for i in range(6):self.kill('defense_'+str(i))
        self.assertEqual(self.e._resolve_winner(),'attack')

    def test_strict_pad_geometry(self):
        a=self.e.agents['attack_0'];a.position=(10,2);self.assertTrue(self.e.on_revive_pad(a))
        a.position=(10.151,2);self.assertFalse(self.e.on_revive_pad(a))

    def test_profile_and_gear_are_stable_across_match_seeds(self):
        other=env(2000)
        for aid,a in self.e.agents.items():
            self.assertEqual(a.human_profile,other.agents[aid].human_profile)
            self.assertEqual(a.eta,other.agents[aid].eta)

    def test_measured_139fps_is_not_a_hard_limit(self):
        a=self.e.agents['attack_0'];a.human_profile['muzzle_speed_fps']=145
        a.position=(12,10)
        v=self.e._launch_velocity(a,(*a.position,1.25),(20,11,1))
        self.assertGreater(sum(x*x for x in v)**.5/.3048,139)

    def test_no_shoot_zone_blocks_release(self):
        e=self.e;a=e.agents['attack_0'];a.position=(14.5,10);a.opening_received=a.shoot_unlocked=True
        b=next(iter(e.arrows.values()));e._carry(b,a);a.aim_elapsed=10
        e._release(a,Action(aim=(25,10,1),aim_key='defense_0',interaction='shoot'))
        self.assertEqual(e.counts['shot'],0)

    def test_arrow_stamps_pad_legality_when_released(self):
        e=self.e;self.kill('attack_2');a=e.agents['attack_0'];a.position=(10,2);a.opening_received=a.shoot_unlocked=True
        b=next(iter(e.arrows.values()));e._carry(b,a);a.aim_elapsed=10
        e._release(a,Action(aim=(16,2,.75),aim_key='rack:revive:4',interaction='shoot'))
        self.assertEqual(e.counts['shot'],1);self.assertTrue(b.valid_revive_release)
        a.position=(12,12);self.assertTrue(b.valid_revive_release)

    def test_body_collision_cannot_be_cancelled_by_random_save(self):
        self.assertFalse(self.e._try_dodge(self.e.agents['attack_0'],next(iter(self.e.arrows.values())),Action()))

    def test_dead_rebound_never_hits_player(self):
        e=self.e;b=next(iter(e.arrows.values()));b.state='flying';b.shooter='attack_0';b.velocity=(35,0,0)
        e._start_rebound(b,(20,10,1),b.velocity,(-1,0),'cover')
        a=e.agents['defense_0'];a.position=b.position[:2]
        old={aid:a.position for aid,a in e.agents.items()}
        e._fly(.05,old,old,{aid:Action() for aid in e.agents},self.rewards)
        self.assertEqual(e.counts['hit'],0);self.assertEqual(a.status,Status.ACTIVE)

    def test_high_and_low_cover_differ_in_vertical_protection(self):
        e=self.e;b=next(iter(e.arrows.values()));b.shooter='defense_0';b.flight_left=4
        positions={aid:a.position for aid,a in e.agents.items()}
        high=e._contacts(b,(7,15.45,1.4),(10,15.45,1.4),positions,positions)
        low=e._contacts(b,(7,5,1.4),(10,5,1.4),positions,positions)
        self.assertTrue(any(h[2]=='obstacle' for h in high))
        self.assertFalse(any(h[2]=='obstacle' for h in low))
        low_crouch=e._contacts(b,(7,5,.7),(10,5,.7),positions,positions)
        self.assertTrue(any(h[2]=='obstacle' for h in low_crouch))

    def test_bow_first_contact_is_in_collision_envelope(self):
        e=self.e;a=e.agents['attack_0'];a.position=(10,10)
        b=next(iter(e.arrows.values()));b.shooter='defense_0';b.flight_left=4
        positions={aid:a.position for aid,a in e.agents.items()}
        contacts=e._contacts(b,(11,10,1.1),(10.31,10,1.1),positions,positions)
        self.assertTrue(any(h[2:] == ('player','attack_0') for h in contacts))

    def test_no_contacts_resolve_after_regulation_deadline(self):
        e=self.e;e.t=240-e.config['time']['dt_s'];a=e.agents['attack_0'];a.position=(10,19)
        b=next(iter(e.arrows.values()));b.state='flying';b.position=(11,19,1);b.velocity=(-1,0,0);b.flight_left=2;b.shooter='defense_0'
        e.step({},observe=False)
        self.assertEqual(e.t,240);self.assertTrue(e.done);self.assertEqual(e.counts['hit'],0)
        with self.assertRaises(RuntimeError):e.step({},observe=False)


if __name__=='__main__':unittest.main()
