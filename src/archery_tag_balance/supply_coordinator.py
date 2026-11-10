"""Finite, exclusive supply jobs: self recovery before optional one-arrow relays."""
from math import hypot,cos,sin,pi
from .entities import Status
from .geometry import segment_box,advance_arrow
from .policies import Navigator


class SupplyCoordinator:
    def __init__(self,env):
        self.e=env;self.nav=Navigator(env.config,env.navigation_obstacles)
        self.contracts={};self.serial=0;self.cooldown={};self.reserved={}
        self.avoid_relays={};self.closed=[]

    def active(self,team):
        return [a for a in self.e.agents.values() if a.team==team and a.status==Status.ACTIVE]

    def path_length(self,start,end,team):
        path=self.nav.path(start,end,team)
        if not path:return 0. if hypot(start[0]-end[0],start[1]-end[1])<.04 else float('inf')
        total=0.;p=start
        for q in path:total+=hypot(p[0]-q[0],p[1]-q[1]);p=q
        if hypot(p[0]-end[0],p[1]-end[1])>.05:
            if not self.nav.clear(p,end):return float('inf')
            total+=hypot(p[0]-end[0],p[1]-end[1])
        return total

    def remember(self,team):
        e=self.e;memory=e.supply_memory[team];friends=self.active(team)
        lo,hi=e.config['teams'][team]['pickup_x_bounds_m']
        for b in e.arrows.values():
            if b.state!='ground' or not lo<=b.position[0]<=hi:continue
            if any(hypot(b.position[0]-a.position[0],b.position[1]-a.position[1])<=40 and e.line_clear((*a.position,e.player_height(a)*.9),(*b.position[:2],.05)) for a in friends):
                memory[b.id]=dict(id=b.id,position=b.position,seen_at=e.t)
        for bid in list(memory):
            if e.arrows[bid].state!='ground' or e.t-memory[bid]['seen_at']>12:memory.pop(bid)
        e.supply_snapshot[team]=list(memory.values())

    def options(self,a,reserved=None,spares=False):
        e=self.e;friends=self.active(a.team);reserved=reserved or {};choices=[]
        direction=1 if a.team=='attack' else -1
        for bid in e.supply_memory[a.team]:
            if reserved.get(bid,a.id)!=a.id or self.reserved.get(bid,a.id)!=a.id or e.supply_avoid.get((a.id,bid),0)>e.t:continue
            b=e.arrows[bid]
            if b.state!='ground':continue
            raw=hypot(b.position[0]-a.position[0],b.position[1]-a.position[1])
            if spares and raw>1.2:continue
            # Rearward recovery is allowed even for cover holders. Forward
            # excursions carry a cost; protected posts do not chase midfield.
            forward=(b.position[0]-a.position[0])*direction
            if 'cover' in a.role and forward>1.0:continue
            points=[p for p in e.pickup_points(b,a.team) if all(f.id==a.id or hypot(p[0]-f.position[0],p[1]-f.position[1])>.72 for f in friends)]
            if not points:continue
            points.sort(key=lambda p:hypot(p[0]-a.position[0],p[1]-a.position[1]))
            # Avoid gratuitous sub-centimetre changes to a valid existing job.
            old=e.jobs.get(a.id,{})
            if old.get('arrow')==bid and old.get('approach') in points:points.insert(0,old['approach'])
            for goal in points[:3]:
                length=self.path_length(a.position,goal,a.team)
                if length==float('inf'):continue
                crowd=sum(max(0,1.3-hypot(goal[0]-f.position[0],goal[1]-f.position[1])) for f in friends if f.id!=a.id)
                exposure=max(0,forward)*(.75 if 'cover' in a.role else .3)
                lane=.12*abs(goal[1]-a.position[1])
                score=length+exposure+2*crowd+lane
                choices.append(dict(arrow=bid,approach=goal,distance=length,eta=length/4.2+.15,score=score))
                break
        choices.sort(key=lambda p:(p['score'],p['arrow']))
        return choices

    def assign_collect(self,a,option,kind='collect',**extra):
        e=self.e;job=dict(kind=kind,quota=1,**option);job.update(extra);e.jobs[a.id]=job
        e.supply_claims[a.team][a.id]=option['arrow']

    def close(self,team,reason):
        c=self.contracts.pop(team,None)
        if not c:return
        e=self.e
        for aid in [c['donor'],c['receiver']]:
            if e.jobs.get(aid,{}).get('contract')==c['id']:e.jobs.pop(aid,None)
        for bid,owner in list(self.reserved.items()):
            if owner==c['receiver']:self.reserved.pop(bid)
        self.cooldown[c['donor']]=e.t+4
        self.avoid_relays[(c['donor'],c['receiver'])]=e.t+5
        self.closed.append(dict(id=c['id'],reason=reason,t=e.t))
        e._emit('supply_complete' if reason=='received' else 'supply_cancel',agent=c['donor'],receiver=c['receiver'],reason=reason)

    def clear_throw(self,origin,goal):
        e=self.e;dx,dy=goal[0]-origin[0],goal[1]-origin[1];n=max(.01,hypot(dx,dy))
        trim=min(.7,n*.18);dx-=dx/n*trim;dy-=dy/n*trim
        duration=.48+min(.45,hypot(dx,dy)/12);z=1.
        velocity=(dx/duration,dy/duration,(.5*9.81*duration**2-z)/duration)
        p=(*origin,z)
        for i in range(1,13):
            q,_=advance_arrow((*origin,z),velocity,duration*i/12,9.81,0)
            if any(segment_box(p,q,*o.bounds(.04)) is not None for o in e.navigation_obstacles):return False
            p=q
        return True

    def throw_position(self,donor,drop):
        e=self.e;lo,hi=e.config['teams'][donor.team]['move_x_bounds_m'];friends=self.active(donor.team)
        candidates=[donor.position]
        for radius in [2.8,4.5]:
            for i in range(12):candidates.append((drop[0]+radius*cos(i*pi/6),drop[1]+radius*sin(i*pi/6)))
        valid=[]
        for p in candidates:
            if not lo<=p[0]<=hi or not .3<=p[1]<=19.7 or hypot(p[0]-drop[0],p[1]-drop[1])>6.2:continue
            if not self.nav.clear(p,p) or any(f.id!=donor.id and hypot(p[0]-f.position[0],p[1]-f.position[1])<.75 for f in friends):continue
            if not self.clear_throw(p,drop):continue
            cost=self.path_length(donor.position,p,donor.team)
            if cost!=float('inf'):valid.append((cost,p))
        return min(valid,key=lambda row:row[0])[1] if valid else None

    def update_contract(self,team):
        e=self.e;c=self.contracts.get(team)
        if not c:return
        donor=e.agents[c['donor']];receiver=e.agents[c['receiver']]
        if receiver.status!=Status.ACTIVE or receiver.inventory:
            self.close(team,'received' if receiver.inventory else 'receiver_out');return
        if hypot(receiver.position[0]-c['anchor'][0],receiver.position[1]-c['anchor'][1])>2.2:
            self.close(team,'receiver_moved');return
        if e.t>c['deadline']:
            self.close(team,'timeout');return
        bid=c.get('arrow');b=e.arrows.get(bid)
        if c['stage'] in ('flight','retrieve'):
            if b is None or (b.state=='carried' and b.carrier!=receiver.id):self.close(team,'arrow_lost');return
            if b.state=='ground':
                if bid not in e.supply_memory[team]:return
                options=[o for o in self.options(receiver) if o['arrow']==bid]
                if not options:self.close(team,'landing_unreachable');return
                if c['stage']!='retrieve':c['stage']='retrieve';c['deadline']=e.t+4
                self.assign_collect(receiver,options[0],kind='delivered_collect',donor=donor.id,contract=c['id'])
            else:
                e.jobs[receiver.id]=dict(kind='wait_delivery',donor=donor.id,contract=c['id'],goal=c['anchor'],deadline=c['deadline'])
            return
        if donor.status!=Status.ACTIVE or not (donor.role.startswith('center') or donor.role=='high_flank'):
            self.close(team,'donor_unavailable');return
        # A recipient may abandon a promised transfer for an immediately
        # available arrow; it never waits merely because a stale tag exists.
        own=self.options(receiver)
        if own and own[0]['eta']<.65:
            self.close(team,'receiver_self_pickup');return
        if donor.inventory:
            # Existing armed donors keep their last arrow. Empty couriers
            # explicitly collecting for this contract may deliver their one.
            if len(donor.inventory)==1 and not c['courier']:
                self.close(team,'donor_needs_last_arrow');return
            c['stage']='carry';old=c.get('arrow')
            chosen=old if old in donor.inventory and old!=donor.nocked_arrow else next((i for i in donor.inventory if i!=donor.nocked_arrow),donor.inventory[-1])
            if old is not None and old!=chosen:self.reserved.pop(old,None)
            c['arrow']=chosen
            self.reserved[c['arrow']]=receiver.id
            where=c.get('throw_from')
            if where is None or not self.clear_throw(where,c['drop']):
                where=self.throw_position(donor,c['drop']);c['throw_from']=where
            if where is None:self.close(team,'blocked_throw');return
            e.jobs[donor.id]=dict(kind='relay',receiver=receiver.id,contract=c['id'],goal=c['drop'],throw_from=where,quota=1,arrow_to_throw=c['arrow'])
        else:
            options=self.options(donor,{bid:aid for aid,bid in e.supply_claims[team].items()})
            current=e.jobs.get(donor.id,{})
            option=next((o for o in options if o['arrow']==current.get('arrow')),options[0] if options else None)
            if option is None:self.close(team,'no_source_arrow');return
            self.assign_collect(donor,option,kind='relay_fetch',receiver=receiver.id,contract=c['id'])
        e.jobs[receiver.id]=dict(kind='wait_delivery',donor=donor.id,contract=c['id'],goal=c['anchor'],deadline=c['deadline'])

    def dispatched(self,donor,bid,receiver):
        c=self.contracts.get(donor.team)
        if not c or c['donor']!=donor.id or c['receiver']!=receiver:return
        c.update(stage='flight',arrow=bid,deadline=self.e.t+3.)
        self.reserved[bid]=receiver
        self.e.jobs.pop(donor.id,None);self.cooldown[donor.id]=self.e.t+5
        self.e.supply_dirty=True

    def transfer_goal(self,donor,receiver):
        c=self.contracts.get(donor.team)
        return c['drop'] if c and c['donor']==donor.id and c['receiver']==receiver else self.e.agents[receiver].position

    def refresh(self,team):
        e=self.e;self.remember(team);friends=[a for a in self.active(team) if a.opening_stashed]
        e.supply_claims[team]={}
        for aid,job in list(e.jobs.items()):
            if e.agents[aid].team!=team:continue
            a=e.agents[aid]
            if a.status!=Status.ACTIVE or (a.inventory and job.get('kind') in ('collect','delivered_collect')):
                e.jobs.pop(aid,None)
        self.update_contract(team)
        contract=self.contracts.get(team)
        locked={contract['donor'],contract['receiver']} if contract else set()
        reserved={bid:aid for aid,bid in e.supply_claims[team].items()}
        # Empty players recover their own arrows first. Empty cover positions
        # can retreat to rear stock; they are not restricted to an 85cm bubble.
        order=sorted([a for a in friends if a.id not in locked],key=lambda a:(bool(a.inventory),0 if a.role=='revive_lane' else 1,a.id))
        options_by={}
        for a in order:
            if a.inventory:
                e.jobs.pop(a.id,None)
                if len(a.inventory)>=a.human_profile['carry_preference']:continue
            options=self.options(a,reserved,spares=bool(a.inventory));options_by[a.id]=options
            old=e.jobs.get(a.id,{})
            prior=next((o for o in options if o['arrow']==old.get('arrow')),None)
            option=prior if prior and prior['score']<=options[0]['score']+1.5 else options[0] if options else None
            if option:
                self.assign_collect(a,option,quota=a.human_profile['carry_preference'] if a.inventory else 1);reserved[option['arrow']]=a.id
            else:e.jobs.pop(a.id,None)
        if contract:return
        # At most one courier per team. A relay must beat the recipient's own
        # feasible recovery, including collection, travel and arrow settling.
        requests=sorted([a for a in friends if not a.inventory and (a.role=='revive_lane' or 'cover' in a.role)],key=lambda a:(a.role!='revive_lane',a.id))
        candidates=[]
        for receiver in requests:
            own=e.jobs.get(receiver.id,{});self_eta=own.get('eta',float('inf'))
            if self_eta<1.1:continue
            d=1 if team=='attack' else -1;drop=(receiver.position[0]-.35*d,receiver.position[1])
            for donor in friends:
                if donor.id==receiver.id or self.cooldown.get(donor.id,0)>e.t or self.avoid_relays.get((donor.id,receiver.id),0)>e.t:continue
                if not (donor.role.startswith('center') or donor.role=='high_flank'):continue
                if e._immediate_threat(donor) or donor.aim_elapsed>.15:continue
                if donor.role=='high_flank' and (len(donor.inventory)<2 or hypot(donor.position[0]-drop[0],donor.position[1]-drop[1])>4.5):continue
                if donor.inventory and len(donor.inventory)<2:continue
                courier=not donor.inventory
                source=e.jobs.get(donor.id,{})
                if courier and source.get('arrow') is None:continue
                where=self.throw_position(donor,drop)
                if where is None:continue
                eta=self.path_length(donor.position,where,team)/4.2+1.35
                if courier:eta+=source.get('eta',2)+.4
                if eta>min(4.,self_eta-.45):continue
                lane=.08*abs(donor.position[1]-receiver.position[1])
                candidates.append((eta+lane,donor,receiver,where,drop,courier))
        if not candidates:return
        _,donor,receiver,where,drop,courier=min(candidates,key=lambda row:row[0])
        for aid in [donor.id,receiver.id]:e.supply_claims[team].pop(aid,None)
        self.serial+=1
        c=dict(id=self.serial,donor=donor.id,receiver=receiver.id,team=team,stage='fetch' if courier else 'carry',courier=courier,anchor=receiver.position,drop=drop,throw_from=where,created=e.t,deadline=e.t+4.,arrow=None)
        self.contracts[team]=c
        e._emit('supply_contract',agent=donor.id,receiver=receiver.id,contract=c['id'])
        self.update_contract(team)
