import sys,json,math,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.tactical_environment import SuzhouEnvironment
from archery_tag_balance.tactical_policy import SuzhouPolicy
from archery_tag_balance.policies import Navigator
from archery_tag_balance.supply_coordinator import SupplyCoordinator
from archery_tag_balance.entities import Status,Action


class SupplyV4(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'configs/suzhou_2026.json').read_text(encoding='utf-8'))
        self.e=SuzhouEnvironment(self.c);self.e.reset(1000,record=True)
        for b in self.e.arrows.values():self.e._ground(b,(31,19,0))
        self.co=self.e.supply_coordinator=SupplyCoordinator(self.e)
        self.receiver=self.ready('attack_1',(7.4,15.45))
        self.donor=self.ready('attack_2',(3,15.45))

    def ready(self,aid,position):
        a=self.e.agents[aid];a.position=position;a.opening_stashed=a.opening_received=a.shoot_unlocked=True
        a.human_profile['carry_preference']=1;return a

    def arrow(self,position):
        b=next(b for b in self.e.arrows.values() if b.state=='ground' and b.position[0]>30)
        self.e._ground(b,(*position,0));return b

    def carry(self,a,n):
        for _ in range(n):
            b=next(b for b in self.e.arrows.values() if b.state=='ground' and b.position[0]>30)
            self.e._carry(b,a);self.e._picked_up(a,b)

    def test_cover_fetches_visible_arrows_two_metres_behind(self):
        b=self.arrow((5.4,15.45));self.co.refresh('attack')
        self.assertEqual(self.e.jobs[self.receiver.id]['kind'],'collect')
        self.assertEqual(self.e.jobs[self.receiver.id]['arrow'],b.id)
        self.assertNotIn('attack',self.co.contracts)

    def test_cover_can_recover_rear_stock_without_a_living_supplier(self):
        self.donor.opening_stashed=False;b=self.arrow((1.5,15.45));self.co.refresh('attack')
        self.assertEqual(self.e.jobs[self.receiver.id]['arrow'],b.id)

    def test_one_own_arrow_is_not_automatically_donated(self):
        self.carry(self.donor,1);self.co.refresh('attack')
        self.assertNotIn('attack',self.co.contracts)
        self.assertNotEqual(self.e.jobs.get(self.donor.id,{}).get('kind'),'relay')

    def test_short_self_pickup_beats_spare_arrow_relay(self):
        self.carry(self.donor,2);b=self.arrow((6.4,15.45));self.co.refresh('attack')
        self.assertNotIn('attack',self.co.contracts)
        self.assertEqual(self.e.jobs[self.receiver.id]['arrow'],b.id)

    def test_real_spare_relay_has_one_recipient_and_fixed_goal(self):
        self.carry(self.donor,2);self.co.refresh('attack');c=self.co.contracts['attack']
        anchor=c['drop'];self.receiver.position=(7.4,16)
        self.assertEqual(self.co.transfer_goal(self.donor,self.receiver.id),anchor)
        self.assertEqual(self.e.jobs[self.receiver.id]['kind'],'wait_delivery')
        self.assertEqual(self.e.jobs[self.donor.id]['receiver'],self.receiver.id)

    def test_each_team_has_at_most_one_courier(self):
        self.carry(self.donor,2);other=self.ready('attack_3',(4,5));self.carry(other,2)
        self.ready('attack_4',(7.7,5));self.co.refresh('attack')
        jobs=[j for aid,j in self.e.jobs.items() if aid.startswith('attack') and j['kind'] in ('relay','relay_fetch')]
        self.assertLessEqual(len(jobs),1)

    def test_throw_releases_donor_instead_of_repeating_job(self):
        self.carry(self.donor,2);self.co.refresh('attack')
        self.e._throw_from_agent(self.donor,self.receiver.id)
        self.assertEqual(self.e.counts['arrow_pass'],1);self.assertEqual(len(self.donor.inventory),1)
        self.assertNotIn(self.donor.id,self.e.jobs)
        self.co.refresh('attack');self.assertNotEqual(self.e.jobs.get(self.donor.id,{}).get('kind'),'relay')

    def test_unloading_bow_does_not_leave_duplicate_arrow_reservations(self):
        self.carry(self.donor,2);self.donor.bow_state='ready';self.donor.nocked_arrow=self.donor.inventory[0]
        self.co.refresh('attack');first=self.co.contracts['attack']['arrow']
        self.donor.bow_state='empty';self.donor.nocked_arrow=None;self.co.refresh('attack')
        self.assertEqual(self.co.contracts['attack']['arrow'],first);self.assertEqual(len(self.co.reserved),1)
        self.co.close('attack','test_cancel');self.assertEqual(self.co.reserved,{})

    def test_landed_delivery_becomes_pickup_instead_of_wait(self):
        self.carry(self.donor,2);self.co.refresh('attack');self.e._throw_from_agent(self.donor,self.receiver.id)
        c=self.co.contracts['attack'];b=self.e.arrows[c['arrow']]
        self.e._ground(b,(7,15.45,0));self.co.refresh('attack')
        self.assertEqual(self.e.jobs[self.receiver.id]['kind'],'delivered_collect')
        self.assertEqual(self.e.jobs[self.receiver.id]['arrow'],b.id)

    def test_receipt_completes_contract_and_does_not_pass_back(self):
        self.carry(self.donor,2);self.co.refresh('attack');self.e._throw_from_agent(self.donor,self.receiver.id)
        c=self.co.contracts['attack'];b=self.e.arrows[c['arrow']]
        self.e._carry(b,self.receiver);self.e._picked_up(self.receiver,b);self.co.refresh('attack')
        self.assertNotIn('attack',self.co.contracts)
        self.assertNotEqual(self.e.jobs.get(self.receiver.id,{}).get('kind'),'relay')

    def test_stale_pass_marker_does_not_block_visible_self_recovery(self):
        b=self.arrow((6.8,15.45));b.pass_recipient=self.receiver.id;b.released_at=self.e.t
        self.co.refresh('attack');self.assertEqual(self.e.jobs[self.receiver.id]['arrow'],b.id)

    def test_missing_delivery_times_out_and_self_pickup_resumes(self):
        self.carry(self.donor,2);self.co.refresh('attack');self.e.t=5
        b=self.arrow((6.5,15.45));self.co.refresh('attack')
        self.assertNotIn('attack',self.co.contracts)
        self.assertEqual(self.e.jobs[self.receiver.id]['arrow'],b.id)

    def test_receiver_death_cancels_transfer(self):
        self.carry(self.donor,2);self.co.refresh('attack');self.receiver.status=Status.ELIMINATED
        self.co.refresh('attack');self.assertNotIn('attack',self.co.contracts)
        self.assertNotIn(self.donor.id,self.e.jobs)

    def test_blocked_toss_is_not_dispatched_through_high_cover(self):
        self.donor.position=(9.6,15.45);self.carry(self.donor,2)
        self.assertFalse(self.co.clear_throw(self.donor.position,(7.05,15.45)))
        self.co.refresh('attack');c=self.co.contracts.get('attack')
        if c:self.assertTrue(self.co.clear_throw(c['throw_from'],c['drop']))

    def test_resource_claims_stay_stable_across_refreshes(self):
        self.donor.opening_stashed=False;b=self.arrow((5.4,15.45));self.co.refresh('attack')
        self.arrow((5.7,15.45));self.e.t=.5;self.co.refresh('attack')
        self.assertEqual(self.e.jobs[self.receiver.id]['arrow'],b.id)

    def test_empty_waiting_player_has_no_idle_footwork(self):
        a=self.donor;policy=SuzhouPolicy(self.c,Navigator(self.c,self.e.navigation_obstacles),a.id,33)
        obs=self.e.get_observation(a.id);obs['time']=1;hold1=policy._positions(obs)[1]
        obs['time']=2;self.assertEqual(hold1,policy._positions(obs)[1])


if __name__=='__main__':unittest.main()
