"""A bounded gather--carry--distribute job, separate from combat carry style.

One dedicated carrier per team may traverse its own REAR field. Cover holders
recover only within their shadow when support lives. Ground knowledge still
comes from actual team observations. Every arrow and transfer is physical.
"""
from math import hypot
from .supply_coordinator import SupplyCoordinator
from .tactical_entities import positions
from .entities import Status


class BatchSupplyCoordinator(SupplyCoordinator):
    def __init__(self,e):
        super().__init__(e);self.request_since={};self.cache_owner={};self.last_served={}

    def supports(self,a):
        return [f for f in self.active(a.team) if f.id!=a.id and f.opening_stashed and 'cover' not in f.role]

    def station(self,a):
        plan=getattr(getattr(self.e,'match_planner',None),'plans',{}).get(a.id,{})
        if plan.get('mode')=='lockdown' and plan.get('goal'):return tuple(plan['goal'])
        if plan.get('objective')=='score_battle' and a.role=='revive_lane':return (6.8 if a.team=='attack' else 25.2,6.7)
        return positions(self.e,a.team,a.role)[0]

    def protected(self,a,point):
        plan=getattr(getattr(self.e,'match_planner',None),'plans',{}).get(a.id,{})
        if plan.get('mode')=='lockdown':return hypot(point[0]-self.station(a)[0],point[1]-self.station(a)[1])<1.
        bunker=next(o for o in self.e.obstacles if o.id==a.team+('_high' if a.role=='high_cover' else '_low'))
        d=1 if a.team=='attack' else -1
        rear=(bunker.center[0]-point[0])*d
        return bunker.size[0]/2+.26<=rear<=bunker.size[0]/2+1.6 and abs(point[1]-bunker.center[1])<=bunker.size[1]/2+.08

    def options(self,a,reserved=None,spares=False,transport=False):
        choices=super().options(a,reserved,False);result=[]
        home=self.station(a);d=1 if a.team=='attack' else -1
        for o in choices:
            b=self.e.arrows[o['arrow']];owner=self.cache_owner.get(b.id)
            if owner and owner!=a.id:continue
            if transport and any('cover' in f.role and f.opening_stashed and hypot(b.position[0]-self.station(f)[0],b.position[1]-self.station(f)[1])<1.2 for f in self.active(a.team)):
                continue
            # Transporters use the whole own half. The lane cap that stranded
            # upper players is deliberately absent from rear-field gathering.
            if 'cover' in a.role and self.supports(a) and not self.protected(a,o['approach']):continue
            if not transport and 'cover' not in a.role and not a.role.startswith('center'):
                if abs(o['approach'][1]-home[1])>3.2:continue
            if spares and o['distance']>1.8:continue
            # Moving across the back is cheap; exposed forward collection is
            # still possible but more expensive than rear stock.
            depth=b.position[0] if d==1 else 32-b.position[0]
            item=dict(o);item['score']=o['distance']+.7*max(0,depth-7)
            if transport:
                nearby=sum(x.state=='ground' and hypot(x.position[0]-b.position[0],x.position[1]-b.position[1])<2.5 for x in self.e.arrows.values())
                item['score']-=min(1.8,.3*nearby)
            result.append(item)
        return sorted(result,key=lambda o:(o['score'],o['arrow']))

    def close(self,team,reason):
        c=self.contracts.pop(team,None)
        if not c:return
        for aid in [c['donor'],c.get('receiver')]:
            if self.e.jobs.get(aid,{}).get('contract')==c['id']:self.e.jobs.pop(aid,None)
            self.e.supply_claims[team].pop(aid,None)
        if c.get('arrow') is not None:self.reserved.pop(c['arrow'],None)
        self.cooldown[c['donor']]=self.e.t+1.0
        self.closed.append(dict(id=c['id'],reason=reason,t=self.e.t))
        self.e._emit('batch_complete' if reason=='distributed' else 'batch_cancel',agent=c['donor'],reason=reason)

    def _finish_leg(self,c,reason):
        e=self.e;receiver=c.get('receiver');bid=c.get('arrow')
        if bid is not None:self.reserved.pop(bid,None)
        if receiver:
            if e.jobs.get(receiver,{}).get('contract')==c['id']:e.jobs.pop(receiver,None)
            e.supply_claims[c['team']].pop(receiver,None)
            c['served'].append(receiver);self.last_served[receiver]=e.t
        if reason in ('received','cached'):
            e._emit('supply_complete',agent=c['donor'],receiver=receiver,reason=reason)
        else:e._emit('supply_cancel',agent=c['donor'],receiver=receiver,reason=reason)
        c.update(stage='distribute',receiver=None,arrow=None,drop=None,throw_from=None)

    def dispatched(self,donor,bid,receiver):
        c=self.contracts.get(donor.team)
        if not c or c['donor']!=donor.id or c.get('receiver')!=receiver:return
        c.update(stage='flight',arrow=bid,leg_deadline=self.e.t+4.0)
        self.reserved[bid]=receiver
        self.e.jobs[donor.id]=dict(kind='batch_pause',contract=c['id'])
        self.e.supply_dirty=True

    def _delivery(self,c,friends):
        e=self.e;donor=e.agents[c['donor']]
        if len(donor.inventory)<=1:self.close(c['team'],'distributed');return
        receivers=[a for a in friends if a.id!=donor.id and a.id in self.request_since and a.id not in c['served']]
        candidates=[]
        for a in receivers:
            anchor=self.station(a)
            if 'cover' not in a.role and hypot(a.position[0]-anchor[0],a.position[1]-anchor[1])>3:continue
            drop=(anchor[0]-(.13 if a.team=='attack' else -.13),anchor[1])
            where=super().throw_position(donor,drop)
            if where is None:continue
            length=self.path_length(donor.position,where,donor.team)
            age=min(60,e.t-self.request_since[a.id])
            priority=length/3.-.16*age-(3 if not a.inventory else 0)-(1.5 if 'cover' in a.role else 0)
            candidates.append((bool(a.inventory),priority,a.id,a,anchor,drop,where))
        if not candidates:
            # Extra arrows become a useful rear cache, not a shooting burden
            # forced on a player whose combat preference is just one.
            goal=(3.5 if donor.team=='attack' else 28.5,positions(e,donor.team,donor.role)[0][1])
            c['stage']='stash';e.jobs[donor.id]=dict(kind='batch_stash',goal=goal,contract=c['id']);return
        _,_,_,receiver,anchor,drop,where=min(candidates,key=lambda row:row[:3])
        chosen=next((bid for bid in donor.inventory if bid!=donor.nocked_arrow),None)
        if chosen is None:self.close(c['team'],'no_loose_arrow');return
        c.update(stage='deliver',receiver=receiver.id,anchor=anchor,drop=drop,throw_from=where,arrow=chosen,leg_deadline=e.t+self.path_length(donor.position,where,donor.team)/2.5+4.)
        self.reserved[chosen]=receiver.id
        e._emit('batch_leg',agent=donor.id,receiver=receiver.id,arrow=chosen)

    def update_contract(self,team):
        e=self.e;c=self.contracts.get(team)
        if not c:return
        donor=e.agents[c['donor']]
        if donor.status!=Status.ACTIVE:self.close(team,'carrier_out');return
        if e.t>c['deadline']:self.close(team,'timeout');return
        friends=[a for a in self.active(team) if a.opening_stashed]
        if c['stage']=='gather':
            if len(donor.inventory)>=c['quota']:
                c['stage']='distribute';e._emit('batch_loaded',agent=donor.id,ammo=len(donor.inventory),quota=c['quota'])
            else:
                reserved={bid:aid for aid,bid in e.supply_claims[team].items()}
                options=self.options(donor,reserved,transport=True)
                if len(donor.inventory)>=2:
                    # Finish a useful local sweep before travelling to recipients.
                    options=[o for o in options if o['distance']<5.0]
                if options:
                    old=e.jobs.get(donor.id,{})
                    option=next((o for o in options if o['arrow']==old.get('arrow')),options[0])
                    self.assign_collect(donor,option,kind='batch_collect',quota=c['quota'],contract=c['id']);return
                if len(donor.inventory)>=2:c['stage']='distribute'
                else:self.close(team,'no_more_sources');return
        if c['stage']=='distribute':self._delivery(c,friends)
        if team not in self.contracts:return
        if c['stage']=='stash':
            if len(donor.inventory)<=1:self.close(team,'distributed')
            elif any(a.id!=donor.id and a.id in self.request_since and a.id not in c['served'] for a in friends):
                c['stage']='distribute';self._delivery(c,friends)
            return
        receiver=e.agents.get(c.get('receiver'))
        if receiver is None or receiver.status!=Status.ACTIVE:
            self._finish_leg(c,'receiver_out');return
        b=e.arrows.get(c.get('arrow'))
        if b is None:self._finish_leg(c,'arrow_lost');return
        if b.state=='carried' and b.carrier==receiver.id:
            self._finish_leg(c,'received');return
        if e.t>c['leg_deadline']:
            self._finish_leg(c,'leg_timeout');return
        if c['stage']=='deliver':
            if b.carrier!=donor.id:self._finish_leg(c,'arrow_taken');return
            e.jobs[donor.id]=dict(kind='batch_deliver',receiver=receiver.id,goal=c['drop'],throw_from=c['throw_from'],arrow_to_throw=b.id,contract=c['id'])
        elif c['stage'] in ('flight','retrieve'):
            e.jobs[donor.id]=dict(kind='batch_pause',contract=c['id'])
            if b.state=='ground':
                choices=[o for o in self.options(receiver) if o['arrow']==b.id and o['distance']<3.]
                if not choices:self._finish_leg(c,'landing_outside_safe_reach');return
                if receiver.inventory:
                    self.cache_owner[b.id]=receiver.id;self._finish_leg(c,'cached');return
                c['stage']='retrieve'
                self.assign_collect(receiver,choices[0],kind='delivered_collect',quota=1,contract=c['id'],donor=donor.id)
                return
            if b.state=='carried':self._finish_leg(c,'arrow_taken');return
        e.jobs[receiver.id]=dict(kind='wait_delivery',donor=donor.id,goal=c['anchor'],deadline=c['leg_deadline'],contract=c['id'])

    def refresh(self,team):
        e=self.e;self.remember(team);friends=[a for a in self.active(team) if a.opening_stashed]
        for bid,aid in list(self.cache_owner.items()):
            if e.agents[aid].status!=Status.ACTIVE or e.arrows[bid].state!='ground':self.cache_owner.pop(bid,None)
        # Calls persist across both teams' refreshes. Cache stock counts, too.
        requesters=[]
        for a in friends:
            home=self.station(a)
            stock=sum(e.arrows[bid].state=='ground' and hypot(e.arrows[bid].position[0]-home[0],e.arrows[bid].position[1]-home[1])<1.2 for bid in e.supply_memory[team])
            if len(a.inventory)+min(1,stock)<(2 if 'cover' in a.role else 1):
                requesters.append(a)
                if a.id not in self.request_since:self.request_since[a.id]=e.t;e._emit('ammo_call',agent=a.id,ammo=len(a.inventory))
        for aid in list(self.request_since):
            if e.agents[aid].team==team and aid not in [a.id for a in requesters]:self.request_since.pop(aid,None)
        e.supply_claims[team]={}
        self.update_contract(team)
        c=self.contracts.get(team);locked={c['donor'],c.get('receiver')} if c else set()
        for aid in list(e.jobs):
            if e.agents[aid].team==team and aid not in locked:e.jobs.pop(aid,None)
        reserved={bid:aid for aid,bid in e.supply_claims[team].items()}
        # One team-wide rear collector. Centers are preferred; an unarmed
        # flank is the fallback when centers have been reassigned or are out.
        need_run=any(not a.inventory or ('cover' in a.role and e.t-self.request_since[a.id]>1.) for a in requesters)
        if not c and len(friends)>=2 and need_run:
            candidates=[]
            for a in friends:
                if 'cover' in a.role or self.cooldown.get(a.id,0)>e.t or e._immediate_threat(a):continue
                if not any(r.id!=a.id and ('cover' in r.role or hypot(r.position[0]-self.station(r)[0],r.position[1]-self.station(r)[1])<=3) for r in requesters):continue
                if len(a.inventory)>=2:
                    candidates.append((-5.,a.id,a,None));continue
                options=self.options(a,reserved,transport=True)
                if len(options)<max(1,2-len(a.inventory)):continue
                option=options[0];penalty=0 if a.role.startswith('center') else 4.
                candidates.append((option['score']+penalty,a.id,a,option))
            if candidates:
                _,_,donor,source=min(candidates,key=lambda row:row[:2]);self.serial+=1
                self.contracts[team]=dict(id=self.serial,team=team,donor=donor.id,receiver=None,arrow=None,stage='gather' if len(donor.inventory)<3 else 'distribute',quota=min(4,len(donor.inventory)+len(self.options(donor,reserved,transport=True))),served=[],created=e.t,deadline=e.t+38.)
                e._emit('batch_start',agent=donor.id,quota=self.contracts[team]['quota'])
                self.update_contract(team);c=self.contracts.get(team);locked={c['donor'],c.get('receiver')} if c else set()
                reserved={bid:aid for aid,bid in e.supply_claims[team].items()}
        # Non-carriers recover their own local arrows, in nearest-cost order.
        pairs=[]
        for a in friends:
            if a.id in locked or a.inventory:continue
            for o in self.options(a,reserved):pairs.append((o['score'],a.id,o['arrow'],a,o))
        assigned=set()
        for _,aid,bid,a,o in sorted(pairs,key=lambda row:row[:3]):
            if aid in assigned or bid in reserved:continue
            self.assign_collect(a,o);assigned.add(aid);reserved[bid]=aid
