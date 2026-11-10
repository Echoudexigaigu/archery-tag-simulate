"""V6 local recovery and short, spare-only delivery contracts.

Lane limits refer to the currently assigned role, not the initial player ID.
No player is sent across the entire width to sustain a remote post.
"""
from math import hypot
from .supply_coordinator import SupplyCoordinator
from .tactical_entities import positions


class LocalSupplyCoordinator(SupplyCoordinator):
    def options(self,a,reserved=None,spares=False):
        home=positions(self.e,a.team,a.role)[0]
        center=a.role.startswith('center');cfg=self.e.config['v6']
        lateral=cfg['center_lane_reach_m'] if center else cfg['post_lane_reach_m']
        choices=super().options(a,reserved,spares)
        result=[]
        for o in choices:
            goal=o['approach']
            if abs(goal[1]-home[1])>lateral or abs(goal[1]-a.position[1])>lateral:continue
            if o['distance']>cfg['maximum_recovery_path_m']:continue
            if center:
                # Local owner should handle an outer lane when still alive and
                # empty. Centers recover or assist adjacent posts instead.
                owners=[f for f in self.active(a.team) if f.id!=a.id and not f.inventory and f.opening_stashed and not ('cover' in f.role and getattr(self,'supports',lambda a:[])(f)) and abs(positions(self.e,f.team,f.role)[0][1]-goal[1])<1.6]
                if any(hypot(f.position[0]-goal[0],f.position[1]-goal[1])+1.<o['distance'] for f in owners):continue
            option=dict(o)
            option['score']+=.8*abs(goal[1]-home[1])+.18*hypot(goal[0]-home[0],goal[1]-home[1])
            result.append(option)
        return sorted(result,key=lambda o:(o['score'],o['arrow']))

    def throw_position(self,donor,drop):
        if abs(donor.position[1]-drop[1])>self.e.config['v6']['relay_lateral_limit_m']:return None
        where=super().throw_position(donor,drop)
        if where is None or self.path_length(donor.position,where,donor.team)>1.6:return None
        return where

    def update_contract(self,team):
        c=self.contracts.get(team)
        if c:
            donor=self.e.agents[c['donor']];receiver=self.e.agents[c['receiver']]
            if c['stage'] not in ('flight','retrieve'):
                if len(donor.inventory)<2:self.close(team,'keep_own_arrow');return
                own=self.options(receiver)
                remaining=self.path_length(donor.position,c['throw_from'],team)/4.2+1.1
                if own and own[0]['eta']+.25<remaining:self.close(team,'self_pickup_faster');return
        super().update_contract(team)

    def refresh(self,team):
        e=self.e;self.remember(team);friends=[a for a in self.active(team) if a.opening_stashed]
        e.supply_claims[team]={}
        for aid in list(e.jobs):
            if e.agents[aid].team==team and e.agents[aid] not in friends:e.jobs.pop(aid,None)
        self.update_contract(team)
        c=self.contracts.get(team);locked={c['donor'],c['receiver']} if c else set()
        old_jobs=dict(e.jobs)
        for a in friends:
            if a.id not in locked:e.jobs.pop(a.id,None)
        reserved={bid:aid for aid,bid in e.supply_claims[team].items()}
        # Global nearest-cost assignment among empty players. It no longer
        # gives a distant low-ID player first choice of a local player's arrow.
        pairs=[]
        for a in friends:
            if a.id in locked or a.inventory:continue
            for o in self.options(a,reserved):
                bonus=.55 if old_jobs.get(a.id,{}).get('arrow')==o['arrow'] else 0
                pairs.append((o['score']-bonus,a.id,o['arrow'],a,o))
        assigned=set()
        for _,aid,bid,a,o in sorted(pairs,key=lambda x:x[:3]):
            if aid in assigned or bid in reserved:continue
            self.assign_collect(a,o);assigned.add(aid);reserved[bid]=aid
        # Pick up one nearby spare only to meet local demand (or the person's
        # configured carry preference). Armed players do not roam to hoard.
        for a in friends:
            if a.id in locked or not a.inventory:continue
            demand=any(not r.inventory and ('cover' in r.role or r.role=='revive_lane') and abs(r.position[1]-a.position[1])<=e.config['v6']['relay_lateral_limit_m'] and hypot(r.position[0]-a.position[0],r.position[1]-a.position[1])<=6 for r in friends)
            quota=max(a.human_profile['carry_preference'],2 if demand and a.role.startswith('center') else 1)
            if len(a.inventory)>=quota:continue
            options=self.options(a,reserved,spares=True)
            if options:
                o=options[0];self.assign_collect(a,o,quota=quota);reserved[o['arrow']]=a.id
        if c:return
        candidates=[]
        for receiver in friends:
            if receiver.inventory or not ('cover' in receiver.role or receiver.role=='revive_lane'):continue
            self_eta=e.jobs.get(receiver.id,{}).get('eta',float('inf'))
            if self_eta<1.4:continue
            d=1 if team=='attack' else -1;drop=(receiver.position[0]-.35*d,receiver.position[1])
            for donor in friends:
                if donor.id==receiver.id or len(donor.inventory)<2:continue
                if not (donor.role.startswith('center') or donor.role=='high_flank'):continue
                if self.cooldown.get(donor.id,0)>e.t or self.avoid_relays.get((donor.id,receiver.id),0)>e.t:continue
                if e._immediate_threat(donor) or donor.aim_elapsed>.15:continue
                where=self.throw_position(donor,drop)
                if where is None:continue
                eta=self.path_length(donor.position,where,team)/4.2+1.35
                if eta+.6>=self_eta or eta>2.2:continue
                candidates.append((eta,donor.id,receiver.id,donor,receiver,where,drop))
        if not candidates:return
        _,_,_,donor,receiver,where,drop=min(candidates,key=lambda x:x[:3])
        for aid in (donor.id,receiver.id):e.supply_claims[team].pop(aid,None);e.jobs.pop(aid,None)
        self.serial+=1
        self.contracts[team]=dict(id=self.serial,donor=donor.id,receiver=receiver.id,team=team,stage='carry',courier=False,anchor=receiver.position,drop=drop,throw_from=where,created=e.t,deadline=e.t+3.5,arrow=None)
        e._emit('supply_contract',agent=donor.id,receiver=receiver.id,contract=self.serial)
        self.update_contract(team)
