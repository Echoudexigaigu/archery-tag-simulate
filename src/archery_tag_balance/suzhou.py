"""Parallel Suzhou rules. NY reference modules are copied unchanged.

Written rules are separated from provisional geometry and policy. A queue entry
does not return to the match until it has physically reached its own baseline.
All first ground/panel contacts end live flight, including visible low bounces.
"""
from collections import Counter
from math import atan2, cos, hypot, radians, sin, sqrt
import random

from .entities import Status, TargetRack, Obstacle
from .environment import Environment
from .geometry import ballistic_velocity, lerp, segment_box, segment_cylinder
from .human_skirmish import ROLES
from .skirmish import SkirmishEnvironment
from .varied_environment import VariedSkirmishEnvironment, landing_time
from .runout_environment import RunoutSkirmishEnvironment
from .rebound_environment import ReboundSkirmishEnvironment


class SuzhouEnvironment(ReboundSkirmishEnvironment):
    def _validate(self):
        # NY's opening-centerline invariant does not apply to front-cover piles.
        Environment._validate(self)
        c=self.config
        if c.get('ruleset_id')!='suzhou_2026_next_battle':
            raise ValueError('Select the independent Suzhou ruleset')
        if any(t['players']!=6 or t['lives']!=1 for t in c['teams'].values()):
            raise ValueError('Suzhou is six players, one life per field entry')
        if c['time']['round_s']!=240:
            raise ValueError('Regulation round is 240 seconds')
        mid=c['field']['length_m']/2
        if any(abs(p[0]-mid)!=6 for p in c['suzhou']['revive_pads'].values()):
            raise ValueError('Revive pads must be 6 metres from the center rack')
        for spec in c['skirmish_racks']:
            if len(spec['spot_weights'])!=5 or len(spec['spot_radii_m'])!=5:
                raise ValueError('Exactly five weighted scoring disks required')

    def _setup_opening(self):
        # Reuse personality/timing initialization, replace only NY rule state.
        VariedSkirmishEnvironment._setup_opening(self)
        self.arrows.clear()
        self.combat_started=True
        self.combat_started_at=0.0
        self.revive_queue={t:[] for t in self.config['teams']}
        self.revive_runner={t:None for t in self.config['teams']}
        self.out_routes={}
        self.outside_positions={}
        self.out_stage={}
        self.revive_approved=set()
        self.invalid_revive_shots=Counter()
        self.target_block_since={}
        self.target_block_warned=set()
        self.policy_intents={}
        self.cache_positions={}
        self.scores={t:{'body':0,'target':0} for t in self.config['teams']}
        self.rack_specs={s['team']:s for s in self.config['skirmish_racks']}
        self.rack_specs['revive']=self.config['suzhou']['revive_rack']
        spec=self.rack_specs['revive']
        x,y,z=spec['position_xyz_m']
        y=self.config['field']['width_m']-y if self.mirror_y else y
        self.skirmish_racks['revive']=TargetRack((x,y,z),tuple(spec['size_m']),list(map(tuple,spec['offsets_hv_m'])),spec['spot_radii_m'][0])
        self.rack_footprints.append(Obstacle('rack_revive',(x,y),(.05,spec['size_m'][0],z+spec['size_m'][1]/2)))
        self.navigation_obstacles=self.obstacles+self.rack_footprints
        self.profile_rng=random.Random(self.config.get('roster_seed',20261107))
        for a in self.agents.values():
            a.shoot_unlocked=False
            a.center_visited=False
            a.has_bow=True
            a.opening_stashed=False
            # Profiles stay fixed across match seeds; only in-match execution varies.
            pr=self.profile_rng
            style=pr.choices(['snap','balanced','deliberate'],[.28,.44,.28])[0]
            a.eta=pr.uniform(.35,.85)
            a.human_profile.update(tempo=pr.uniform(.85,1.15),accuracy=pr.uniform(.85,1.2),
                range_bias=pr.gauss(0,.035),yaw_bias=pr.gauss(0,.012),pitch_bias=pr.gauss(0,.008),
                pickup_tempo=pr.uniform(.85,1.2),aim_style=style,
                personal_aim_s=pr.uniform(*{'snap':(.3,.65),'balanced':(.8,1.5),'deliberate':(1.8,2.8)}[style]),
                follow_through=pr.choices(['continue','sidestep','withdraw'],[.75,.17,.08])[0],draw_power=1.0,
                reaction_s=pr.uniform(*self.config.get('motion_refinement',{}).get('reaction_range_s',[.16,.28])))
            a.human_profile.update(self.config.get('roster',{}).get(a.id,{}))
            a.human_profile.setdefault('muzzle_speed_fps',pr.uniform(120,125))
            a.human_profile.setdefault('name',a.id)
            direction=1 if a.team=='attack' else -1
            own=[o for o in self.obstacles if o.id.startswith(a.team+'_')]
            own_left=max(own,key=lambda o:o.center[1]) if direction==1 else min(own,key=lambda o:o.center[1])
            own_right=next(o for o in own if o is not own_left)
            cover=own_left if int(a.id.rsplit('_',1)[1])<3 else own_right
            if 'cover' in a.role:
                cache=(cover.center[0]-direction*(cover.size[0]/2+.43),cover.center[1])
            elif 'flank' in a.role:
                cache=(cover.center[0]-direction*(cover.size[0]/2+2.1),cover.center[1]+(.12 if cover.center[1]>10 else -.12))
            else:
                cache=(3.3 if direction==1 else 28.7,a.spawn[1]+(.4 if int(a.id.rsplit('_',1)[1])==2 else -.4))
            self.cache_positions[a.id]=cache
            self._next_pickup_duration(a)
            for j in range(3):
                b=self._new_arrow((*self.opening_pile(a),0))
                # Piles are shared resources, not private ownership.
                b.opening_arrow=False
        self.total_arrows=len(self.arrows)

    def opening_pile(self,a):
        y=a.spawn[1]
        for o in self.obstacles:
            if o.id.startswith(a.team) and abs(y-o.center[1])<o.size[1]/2+.45:
                y=o.center[1]+(1 if y>self.config['field']['width_m']/2 else -1)*(o.size[1]/2+.65)
        return (self.config['suzhou']['arrow_line_x_m'][a.team],y)

    def opening_lane(self,a):
        return a.spawn[1]

    def _pickup_allowed(self,a,b):
        return a.status==Status.ACTIVE and len(a.inventory)<self.config['rules']['carry_limit']

    def _picked_up(self,a,b):
        first=not a.opening_received
        a.opening_received=a.center_visited=a.shoot_unlocked=True
        b.opening_arrow,b.opening_owner=False,None
        if len(a.inventory)==1:
            self._prepare_arrow(a)
        self._next_pickup_duration(a)
        if first:self._emit('opening_arrow_collected',agent=a.id)

    def _drop(self,a):
        if not a.opening_stashed:
            goal=self.cache_positions[a.id]
            if len(a.inventory)<2 or hypot(a.position[0]-goal[0],a.position[1]-goal[1])>.65:return
            while len(a.inventory)>1:
                bid=a.inventory.pop()
                self._ground(self.arrows[bid],(*a.position,0))
                self._emit('stash',agent=a.id,arrow=bid,position=a.position)
            a.opening_stashed=True
            self._prepare_arrow(a)
            self._emit('opening_cache_ready',agent=a.id)
            return
        # Actions are held across several physics ticks. Repeated execution of
        # the same drop must not throw away the one arrow retained for shooting.
        if len(a.inventory)>1:
            self._ground(self.arrows[a.inventory.pop()],(*a.position,0))

    def on_revive_pad(self,a):
        px,py=self.config['suzhou']['revive_pads'][a.team]
        if self.mirror_y:py=self.config['field']['width_m']-py
        sx,sy=self.config['suzhou']['revive_pad_size_m']
        # Body point proxies a foot position; keep explicit, no metre-wide aura.
        return abs(a.position[0]-px)<=sx/2+1e-9 and abs(a.position[1]-py)<=sy/2+1e-9

    def _release(self,a,action):
        if not a.opening_received:return
        # Feet must remain strictly inside firing bounds, never on field lines.
        lo,hi=self.config['teams'][a.team]['shoot_x_bounds_m']
        if not lo<a.position[0]<hi:return
        before=self.counts['shot'];bid=a.inventory[0] if a.inventory else None
        valid=self.on_revive_pad(a) and bool(self.revive_queue[a.team])
        VariedSkirmishEnvironment._release(self,a,action)
        if self.counts['shot']!=before:
            self.arrows[bid].valid_revive_release=valid
            self.arrows[bid].revive_release_position=a.position
            self.arrows[bid].aim_band='target' if str(action.aim_key).startswith('rack:') else ('low' if action.aim[2]<.55 else 'torso' if action.aim[2]<1.15 else 'upper')
            if a.inventory:self._prepare_arrow(a)

    def _launch_velocity(self,a,origin,target):
        p,s,h=self.config['physics'],self.config['human_shooting'],a.human_profile
        nominal=h['muzzle_speed_fps']*.3048
        estimate=max(.8,min(1.2,1+h['range_bias']+self.rng.gauss(0,.018+.026*(1-a.eta))))
        perceived=(origin[0]+(target[0]-origin[0])*estimate,origin[1]+(target[1]-origin[1])*estimate,target[2])
        v=ballistic_velocity(origin,perceived,nominal,p['gravity_m_s2'],p['linear_drag_s_inv'],p['arrow_max_flight_s'])
        if v is None:return None
        sigma=self._skill(a.eta,s['novice_angle_sd_rad'],s['expert_angle_sd_rad'])*h['accuracy']*self._accuracy_multiplier(a)
        unsettled=max(0,1-(self.t-a.last_move_at)/s['settle_s'])
        sigma*=1+.35*unsettled+.35*(1-a.stamina)+.2*(self.t<a.movement_dodge_ready_at)
        poor=self.rng.random()<s['poor_release_probability']*(1-.45*a.eta)
        if poor:sigma*=1.8
        yaw=atan2(v[1],v[0])+h['yaw_bias']+self.rng.gauss(0,sigma)
        pitch=max(radians(-35),min(radians(self.config['flight_variation']['max_elevation_degrees']),atan2(v[2],hypot(*v[:2]))+h['pitch_bias']+self.rng.gauss(0,.8*sigma)))
        speed=nominal*max(.91,min(1.06,self.rng.gauss(1,.025)))
        result=(speed*cos(pitch)*cos(yaw),speed*cos(pitch)*sin(yaw),speed*sin(pitch))
        duration=landing_time(origin,result,p['gravity_m_s2'],p['linear_drag_s_inv'],p['arrow_max_flight_s'])
        self.last_launch[a.id]=dict(sigma=sigma,speed=speed,speed_fps=speed/.3048,
            range_estimate=estimate,poor_release=poor,aim_required=a.human_aim_s,
            planned_flight_s=duration,aim_style=h['aim_style'],steady_aim_s=a.steady_aim_s,
            aim_height_m=target[2],target_band='target' if str(a.aim_key).startswith('rack:') else ('low' if target[2]<.55 else 'torso' if target[2]<1.15 else 'upper'))
        return result

    def _try_dodge(self,a,b,action):
        # A geometric direct hit counts. Physical sidesteps/crouches remain.
        return False

    def _contacts(self,b,p,q,old_positions,new_positions):
        hits=Environment._contacts(self,b,p,q,old_positions,new_positions)
        radius=self.config['physics']['arrow_radius_m']
        # Approximate bow silhouette, separately from the body, as a thin vertical
        # cylinder in front of the holder. Held loose arrows share this envelope.
        for a in self.agents.values():
            if a.id==b.shooter or a.status!=Status.ACTIVE:continue
            dx=.3*(1 if a.team=='attack' else -1)
            old=(old_positions[a.id][0]+dx,old_positions[a.id][1])
            new=(new_positions[a.id][0]+dx,new_positions[a.id][1])
            lower=.45 if a.crouched else .65
            u=segment_cylinder((p[0],p[1],p[2]-lower),(q[0],q[1],q[2]-lower),old,new,.055+radius,.65)
            if u is not None:hits.append((u,1,'player',a.id))
        for key,rack in self.skirmish_racks.items():
            if abs(q[0]-p[0])<1e-12:continue
            u=(rack.position[0]-p[0])/(q[0]-p[0])
            if not 0<=u<=1:continue
            point=lerp(p,q,u)
            if abs(point[1]-rack.position[1])>rack.size[0]/2+radius or abs(point[2]-rack.position[2])>rack.size[1]/2+radius:continue
            radii=self.rack_specs[key]['spot_radii_m']
            spot=next((k for k in range(5) if hypot(point[1]-rack.spot(k)[1],point[2]-rack.spot(k)[2])<=radii[k]+radius),-1)
            if spot>=0 and not rack.standing[spot] and hypot(point[1]-rack.spot(spot)[1],point[2]-rack.spot(spot)[2])<=max(0,radii[spot]-radius):continue
            hits.append((u,0,'skirmish_rack',(key,spot)))
        return sorted(hits)

    def _contact_skirmish_rack(self,b,target,point,rewards):
        key,spot=target;rack=self.skirmish_racks[key];shooter=self.agents[b.shooter]
        standing=spot>=0 and rack.standing[spot]
        if standing:
            # Geometric disk contact followed by an explicit, uncalibrated drop
            # probability. Rim and failed drops rebound as dead arrows.
            speed=sqrt(sum(v*v for v in b.velocity));incidence=abs(b.velocity[0])/max(speed,1e-9)
            prob=self.config['target_scoring']['knockdown_probability']*min(1,speed/10)*(.6+.4*incidence)
            success=self.rng.random()<prob
            if key=='revive' and not (getattr(b,'valid_revive_release',False) and self.revive_queue[shooter.team]):
                success=False;self.invalid_revive_shots[shooter.team]+=1
                self._emit('invalid_revive',agent=shooter.id,arrow=b.id,reason='pad_or_empty_queue')
            self._emit('rack_roll',team=key,spot=spot,shooter=shooter.id,probability=prob,success=success)
            if success:
                rack.standing[spot]=False
                if key=='revive':
                    aid=self.revive_queue[shooter.team].pop(0)
                    self.revive_approved.add(aid)
                    self._emit('revive_granted',agent=aid,shooter=shooter.id,spot=spot)
                else:
                    beneficiary='defense' if key=='attack' else 'attack'
                    self.scores[beneficiary]['target']+=self.rack_specs[key]['spot_weights'][spot]
                    self._emit('rack_target',team=key,spot=spot,shooter=shooter.id)
                self._ground(b,point)
                return
        normal=(-1 if b.velocity[0]>0 else 1,0)
        self._start_rebound(b,point,b.velocity,normal,'rack')

    def _eliminate(self,a,shooter,rewards):
        if a.status!=Status.ACTIVE:return
        pos=a.position
        Environment._eliminate(self,a,shooter,rewards)
        a.respawn_at=None
        self.scores[shooter.team]['body']+=1
        self.revive_queue[a.team].append(a.id)
        self.outside_positions[a.id]=pos
        y=self.config['suzhou']['waiting_y_m'][a.team]
        if self.mirror_y:y=self.config['field']['width_m']-y
        # Exit to a side and follow an outside lane; eliminated silhouettes are
        # display-only, never colliders and never arrow collectors.
        outside_x=-.35 if a.team=='attack' else self.config['field']['length_m']+.35
        wait=tuple(self.config['suzhou'].get('waiting_positions_m',{}).get(a.team,[a.spawn[0],y]))
        self.out_routes[a.id]=[(a.spawn[0],pos[1]),(outside_x,pos[1]),(outside_x,y),wait]
        self.out_stage[a.id]='leaving'
        self._emit('queue_join',agent=a.id,position=len(self.revive_queue[a.team]))

    def _advance_out_route(self,a,dt):
        route=self.out_routes[a.id];point=self.outside_positions[a.id]
        remaining=dt*self.config['suzhou']['off_field_run_speed_m_s']
        while route and remaining>0:
            goal=route[0];distance=hypot(goal[0]-point[0],goal[1]-point[1])
            if distance<=remaining:
                point=goal;route.pop(0);remaining-=distance
            else:
                f=remaining/distance;point=(point[0]+f*(goal[0]-point[0]),point[1]+f*(goal[1]-point[1]));remaining=0
        self.outside_positions[a.id]=point
        if route:return
        if self.out_stage[a.id]=='leaving':
            self.out_stage[a.id]='waiting'
            self._emit('queue_arrived',agent=a.id)
        if a.id not in self.revive_approved:return
        if self.out_stage[a.id]=='waiting':
            self.out_stage[a.id]='returning'
            x= -.35 if a.team=='attack' else self.config['field']['length_m']+.35
            self.out_routes[a.id]=[(x,point[1]),(x,a.spawn[1]),a.spawn]
            return
        # Entry becomes active only after travelling to the baseline entry point.
        r=self.config['physics']['player_radius_m']
        if any(b.status!=Status.ELIMINATED and hypot(b.position[0]-a.spawn[0],b.position[1]-a.spawn[1])<2*r+.05 for b in self.agents.values() if b.id!=a.id):return
        a.position,a.velocity=a.spawn,(0,0)
        a.lives,a.status=1,Status.ACTIVE
        a.shoot_unlocked,a.has_bow=True,True
        a.opening_stashed=True
        a.aim_elapsed,a.reload_left,a.pickup_elapsed=0,0,0
        self.revive_approved.remove(a.id)
        del self.out_routes[a.id],self.outside_positions[a.id],self.out_stage[a.id]
        self._emit('respawn',agent=a.id)

    def _timers(self,dt):
        super()._timers(dt)
        for aid in list(self.out_routes):self._advance_out_route(self.agents[aid],dt)

    def _refresh_supply(self,team):
        super()._refresh_supply(team)
        # Unique arrows alone do not prevent a crowd at clustered arrows.
        # Reallocate with a spatial reservation cost, leaving one close occupant
        # at each cover. These are common tactical rules, not a teamwork rating.
        memory=self.supply_memory[team]
        empty=[a for a in self.agents.values() if a.team==team and a.status==Status.ACTIVE and a.opening_stashed and not a.inventory]
        proposals=[]
        for a in empty:
            for bid,b in memory.items():
                point=b['position'];dist=hypot(point[0]-a.position[0],point[1]-a.position[1])
                crowd=sum(max(0,1.8-hypot(point[0]-p.position[0],point[1]-p.position[1])) for p in self.agents.values() if p.id!=a.id and p.team==team and p.status==Status.ACTIVE)
                cover_cost=0
                for o in self.obstacles:
                    if o.id.startswith(team) and hypot(point[0]-o.center[0],point[1]-o.center[1])<1.5 and 'cover' not in a.role:
                        cover_cost+=2
                proposals.append((dist+.45*abs(point[1]-a.spawn[1])+2*crowd+cover_cost,a.id,bid))
        claims={};reserved=[];taken=set()
        for _,aid,bid in sorted(proposals):
            point=memory[bid]['position']
            if aid in claims or bid in taken:continue
            if any(hypot(point[0]-p[0],point[1]-p[1])<1.35 for p in reserved):continue
            claims[aid]=bid;taken.add(bid);reserved.append(point)
        self.supply_claims[team]=claims

    def _update_rule_state(self):
        # No NY center-visit, stash, bow collection, automatic timer respawn.
        if self.supply_dirty or self.t+1e-9>=self.next_supply_update:
            for team in self.config['teams']:self._refresh_supply(team)
            self.next_supply_update,self.supply_dirty=self.t+.4,False
        for team in self.config['teams']:
            eligible=[a for a in self.agents.values() if a.team==team and a.status==Status.ACTIVE and a.opening_stashed and a.inventory and a.reload_left<=0]
            if self.revive_queue[team] and any(self.skirmish_racks['revive'].standing) and eligible:
                pad=self.config['suzhou']['revive_pads'][team]
                old=self.revive_runner[team]
                keep=next((a for a in eligible if a.id==old),None)
                chosen=keep or min(eligible,key=lambda a:hypot(a.position[0]-pad[0],a.position[1]-pad[1])+.4*a.human_aim_s)
                self.revive_runner[team]=chosen.id
            else:self.revive_runner[team]=None
        # Do not silently legalize camping in front of a score target.
        for a in self.agents.values():
            if a.status!=Status.ACTIVE:continue
            rack=self.skirmish_racks[a.team];direction=1 if a.team=='attack' else -1
            front=(a.position[0]-rack.position[0])*direction
            blocking=0<front<2 and abs(a.position[1]-rack.position[1])<.65
            if blocking:
                start=self.target_block_since.setdefault(a.id,self.t)
                if self.t-start>3 and a.id not in self.target_block_warned:
                    self.target_block_warned.add(a.id);self._emit('target_obstruction_warning',agent=a.id)
            else:
                self.target_block_since.pop(a.id,None);self.target_block_warned.discard(a.id)

    def remaining_score(self,team):
        alive=sum(a.status==Status.ACTIVE for a in self.agents.values() if a.team==team)
        target=sum(w for w,s in zip(self.rack_specs[team]['spot_weights'],self.skirmish_racks[team].standing) if s)
        return dict(alive=alive,target=target,total=alive+target)

    def _resolve_winner(self):
        alive={t:sum(a.status==Status.ACTIVE for a in self.agents.values() if a.team==t) for t in self.config['teams']}
        lost={t:alive[t]==0 or not any(self.skirmish_racks[t].standing) for t in alive}
        if any(lost.values()):
            self.victory_reason='mutual_loss' if all(lost.values()) else ('target_clear' if any(not any(self.skirmish_racks[t].standing) for t in lost if lost[t]) else 'elimination')
            return 'draw' if all(lost.values()) else next(t for t in lost if not lost[t])
        if self.t+1e-8>=self.config['time']['round_s']:
            totals={t:self.remaining_score(t)['total'] for t in alive}
            self.victory_reason='remaining_score'
            return 'draw' if len(set(totals.values()))==1 else max(totals,key=totals.get)
        return None

    def get_observation(self,agent_id=None):
        obs=RunoutSkirmishEnvironment.get_observation(self,agent_id)
        if agent_id is not None:
            a=self.agents[agent_id]
            obs.update(revive_queue=list(self.revive_queue[a.team]),revive_runner=self.revive_runner[a.team],opening_pile=self.opening_pile(a))
            obs['self'].update(on_revive_pad=self.on_revive_pad(a),muzzle_speed_fps=a.human_profile['muzzle_speed_fps'],
                opening_stashed=a.opening_stashed,cache_position=self.cache_positions[a.id],reaction_s=a.human_profile['reaction_s'])
            for enemy in obs['enemies']:
                enemy['aiming']=self.agents[enemy['id']].aim_elapsed>.12
        return obs

    def _record_frame(self):
        RunoutSkirmishEnvironment._record_frame(self)
        f=self.trace[-1]
        f.update(revive_queue={t:list(q) for t,q in self.revive_queue.items()},revive_approved=sorted(self.revive_approved),
            remaining_score={t:self.remaining_score(t) for t in self.config['teams']},winner=self.winner,victory_reason=self.victory_reason)
        for p in f['players']:
            a=self.agents[p['id']]
            p.update(name=a.human_profile['name'],muzzle_speed_fps=a.human_profile['muzzle_speed_fps'],
                out_position=self.outside_positions.get(a.id),out_stage=self.out_stage.get(a.id),
                revive_runner=self.revive_runner[a.team]==a.id,intent=self.policy_intents.get(a.id,{}),cache_position=self.cache_positions[a.id])
            if a.status==Status.ACTIVE and not a.opening_stashed:
                p['stage']='gathering' if len(a.inventory)<3 else 'caching'
        for b in f['arrows']:
            arrow=self.arrows[b['id']]
            b['aim_band']=getattr(arrow,'aim_band',None)

    def assert_invariants(self):
        RunoutSkirmishEnvironment.assert_invariants(self)
        queued=[x for q in self.revive_queue.values() for x in q]
        assert len(queued)==len(set(queued))
        assert not set(queued)&self.revive_approved
        assert len(self.arrows)==36
        for aid in queued+list(self.revive_approved):assert self.agents[aid].status==Status.ELIMINATED
        for a in self.agents.values():
            assert a.lives==(1 if a.status==Status.ACTIVE else 0)
            if a.status==Status.ACTIVE:
                lo,hi=self.config['teams'][a.team]['move_x_bounds_m']
                assert lo-1e-8<=a.position[0]<=hi+1e-8

    def summary(self):
        row=Environment.summary(self)
        row.update(ruleset=self.config['ruleset_id'],victory_reason=self.victory_reason,
            remaining_score={t:self.remaining_score(t) for t in self.config['teams']},
            target_status={t:list(r.standing) for t,r in self.skirmish_racks.items()},
            revive_grants=self.counts['revive_granted'],panel_rebounds=self.counts['panel_rebound'],
            invalid_revive_shots=dict(self.invalid_revive_shots),geometry_verified=self.config['suzhou']['diagram_verified'])
        row.update(stashed_arrows=self.counts['stash'],movement_evades=self.counts['evade_move'])
        return row
