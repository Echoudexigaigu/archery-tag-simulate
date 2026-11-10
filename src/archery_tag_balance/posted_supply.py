"""Early low-ammo calls and one bounded, local resupply task per team."""
from copy import copy
from math import hypot
from .entities import Status
from .local_supply import LocalSupplyCoordinator
from .tactical_entities import positions
from .supply_coordinator import SupplyCoordinator


class PostedSupplyCoordinator(LocalSupplyCoordinator):
    def __init__(self,e):
        super().__init__(e);self.request_since={}

    def supports(self,a):
        return [f for f in self.active(a.team) if f.id!=a.id and f.opening_stashed and (f.role.startswith('center') or f.role=='high_flank') and abs(positions(self.e,f.team,f.role)[0][1]-positions(self.e,a.team,a.role)[0][1])<=5.2]

    def throw_position(self,donor,drop):
        if abs(donor.position[1]-drop[1])>self.e.config['v6']['relay_lateral_limit_m']:return None
        where=SupplyCoordinator.throw_position(self,donor,drop)
        if where is None or self.path_length(donor.position,where,donor.team)>3.5:return None
        return where

    def options(self,a,reserved=None,spares=False):
        choices=super().options(a,reserved,spares)
        if 'cover' in a.role and self.supports(a):
            hold=positions(self.e,a.team,a.role)[0]
            choices=[o for o in choices if hypot(o['approach'][0]-hold[0],o['approach'][1]-hold[1])<=1.4]
        return choices

    def update_contract(self,team):
        c=self.contracts.get(team)
        if not c or not c.get('proactive'):return super().update_contract(team)
        e=self.e;donor=e.agents[c['donor']];receiver=e.agents[c['receiver']];b=e.arrows.get(c.get('arrow'))
        if donor.status!=Status.ACTIVE and c['stage'] not in ('flight','retrieve'):self.close(team,'donor_out');return
        if receiver.status!=Status.ACTIVE:self.close(team,'receiver_out');return
        if receiver.role!=c['receiver_role'] or donor.role!=c['donor_role']:self.close(team,'role_changed');return
        if b and b.state=='carried':
            if b.carrier==receiver.id:self.close(team,'received');return
            if b.carrier!=donor.id:self.close(team,'arrow_lost');return
        if e.t>c['deadline']:self.close(team,'timeout');return
        if hypot(receiver.position[0]-c['anchor'][0],receiver.position[1]-c['anchor'][1])>2.3:self.close(team,'receiver_moved');return
        if c['stage'] in ('flight','retrieve'):
            if b is None:self.close(team,'arrow_lost');return
            if b.state=='ground':
                options=[o for o in self.options(receiver) if o['arrow']==b.id]
                if not options:self.close(team,'landing_unreachable');return
                if c['stage']!='retrieve':c['stage']='retrieve';c['deadline']=e.t+3.5
                self.assign_collect(receiver,options[0],kind='delivered_collect',quota=min(4,len(receiver.inventory)+1),donor=donor.id,contract=c['id'])
            else:e.jobs[receiver.id]=dict(kind='wait_delivery',donor=donor.id,contract=c['id'],goal=c['anchor'],deadline=c['deadline'])
            return
        if len(receiver.inventory)>=2:self.close(team,'receiver_rearmed');return
        if len(donor.inventory)<2:
            reserved={bid:aid for aid,bid in e.supply_claims[team].items()}
            options=self.options(donor,reserved)
            source=next((o for o in options if o['arrow']==c.get('source')),None)
            if source is None and donor.inventory and options:
                source=options[0];c['source']=source['arrow']
            if source is None:self.close(team,'source_lost');return
            self.assign_collect(donor,source,kind='relay_fetch',quota=2,receiver=receiver.id,contract=c['id'])
        else:
            if c['stage']=='fetch':c['deadline']=e.t+3.5
            c['stage']='carry'
            where=self.throw_position(donor,c['drop'])
            if where is None:self.close(team,'blocked_throw');return
            c['throw_from']=where
            if c.get('arrow') not in donor.inventory:
                c['arrow']=next(bid for bid in donor.inventory if bid!=donor.nocked_arrow)
            self.reserved[c['arrow']]=receiver.id
            e.jobs[donor.id]=dict(kind='relay',receiver=receiver.id,contract=c['id'],goal=c['drop'],throw_from=where,quota=1,arrow_to_throw=c['arrow'])
        e.jobs[receiver.id]=dict(kind='wait_delivery',donor=donor.id,contract=c['id'],goal=c['anchor'],deadline=c['deadline'])

    def refresh(self,team):
        e=self.e
        super().refresh(team)
        friends=[a for a in self.active(team) if a.opening_stashed]
        requests=[a for a in friends if 'cover' in a.role and len(a.inventory)<=1 and self.supports(a) and not any(o['eta']<.65 for o in self.options(a))]
        for a in requests:
            if a.id not in self.request_since:
                self.request_since[a.id]=e.t;e._emit('ammo_call',agent=a.id,ammo=len(a.inventory))
        for aid in list(self.request_since):
            if e.agents[aid].team==team and aid not in [a.id for a in requests]:self.request_since.pop(aid)
        if team in self.contracts:return
        candidates=[]
        reserved={j['arrow']:aid for aid,j in e.jobs.items() if j.get('arrow') is not None}
        for receiver in sorted(requests,key=lambda a:(bool(a.inventory),self.request_since[a.id],a.id)):
            hold=positions(e,team,receiver.role)[0];d=1 if team=='attack' else -1
            drop=(hold[0]-.15*d,hold[1])
            for donor in self.supports(receiver):
                if self.cooldown.get(donor.id,0)>e.t or self.avoid_relays.get((donor.id,receiver.id),0)>e.t:continue
                if e._immediate_threat(donor):continue
                if donor.aim_elapsed>.15 and receiver.inventory:continue
                source=None;eta=0.;proxy=copy(donor)
                if len(donor.inventory)<2:
                    options=self.options(donor,reserved)
                    if not options:continue
                    source=options[0]
                    # An empty supplier first needs a local pair; keep one for
                    # itself. Do not recreate the V3 last-arrow donation loop.
                    if not donor.inventory:
                        count=sum(b.state=='ground' and hypot(b.position[0]-source['approach'][0],b.position[1]-source['approach'][1])<3.0 for b in e.arrows.values())
                        if count<2:continue
                    eta=source['eta']+.3;proxy.position=source['approach']
                where=self.throw_position(proxy,drop)
                if where is None:continue
                eta+=self.path_length(proxy.position,where,team)/4.2+1.3
                if eta>6.5:continue
                candidates.append((eta+(1 if receiver.inventory else 0),receiver.id,donor.id,receiver,donor,drop,where,source))
        if not candidates:return
        _,_,_,receiver,donor,drop,where,source=min(candidates,key=lambda x:x[:3])
        for aid in (donor.id,receiver.id):e.supply_claims[team].pop(aid,None);e.jobs.pop(aid,None)
        self.serial+=1
        self.contracts[team]=dict(id=self.serial,proactive=True,donor=donor.id,receiver=receiver.id,donor_role=donor.role,receiver_role=receiver.role,team=team,stage='fetch' if source else 'carry',courier=False,anchor=positions(e,team,receiver.role)[0],drop=drop,throw_from=where,created=e.t,deadline=e.t+8.,source=source['arrow'] if source else None,arrow=None)
        e._emit('supply_contract',agent=donor.id,receiver=receiver.id,contract=self.serial,early=bool(receiver.inventory))
        self.update_contract(team)
