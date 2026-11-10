"""Dead-arrow runout after first ground contact, with absorbing field nets.

The landing samples a short directional runout. An eased path and damped low
hops express that runout; no flexible-shaft/contact mechanics are attempted.
"""
from math import atan2, cos, hypot, pi, radians, sin

from .geometry import lerp, segment_box
from .varied_environment import VariedSkirmishEnvironment


class RunoutSkirmishEnvironment(VariedSkirmishEnvironment):
    def _validate(self):
        super()._validate()
        c=self.config['ground_runout']
        if not 0<c['min_duration_s']<=c['max_duration_s'] or not 0<=c['min_distance_m']<=c['max_distance_m']:
            raise ValueError('Invalid runout duration or distance bounds')
        lo,hi=c['deceleration_range_m_s2']
        if not 0<lo<=hi or c['distance_cv']<0 or not 0<=c['max_deviation_degrees']<60:
            raise ValueError('Invalid runout deceleration or deviation')
        if c['direction_sd_degrees']<0 or not 0<c['speed_retention_base']+c['flatness_retention']<1:
            raise ValueError('Invalid runout direction or speed retention')

    def _allowed_arrow_states(self):
        return super()._allowed_arrow_states() | {'settling'}

    def _carry(self, arrow, agent):
        super()._carry(arrow,agent)
        arrow.landing_origin=None
        arrow.settling_elapsed=arrow.settling_duration=0.0

    def _finish_flight(self, arrow, point, kind, velocity, remaining_tick_s):
        if kind!='ground':
            super()._finish_flight(arrow,point,kind,velocity,remaining_tick_s)
            if kind=='boundary':self._emit('flight_net_stop',arrow=arrow.id)
            return
        # This records the end of live flight once, before transitioning to a
        # nonlethal, nonpickable state. No pickup step can observe the transient.
        super()._ground(arrow,point)
        horizontal=hypot(*velocity[:2])
        if horizontal<0.2:
            return
        c=self.config['ground_runout']
        flatness=horizontal/max(1e-9,horizontal+abs(velocity[2]))
        after_speed=horizontal*(c['speed_retention_base']+c['flatness_retention']*flatness)
        deceleration=self.rng.uniform(*c['deceleration_range_m_s2'])
        scatter=self.rng.lognormvariate(-0.5*c['distance_cv']**2,c['distance_cv'])
        distance=max(c['min_distance_m'],min(c['max_distance_m'],after_speed**2/(2*deceleration)*scatter))
        angle=atan2(velocity[1],velocity[0])+max(-radians(c['max_deviation_degrees']),min(radians(c['max_deviation_degrees']),self.rng.gauss(0,radians(c['direction_sd_degrees']))))
        arrow.state,arrow.carrier='settling',None
        arrow.landing_origin=arrow.position
        arrow.settling_heading=(cos(angle),sin(angle))
        arrow.settling_distance=distance
        arrow.settling_duration=max(c['min_duration_s'],min(c['max_duration_s'],2*distance/max(0.2,after_speed)))
        arrow.settling_elapsed=0.0
        arrow.settling_curve=self.rng.uniform(-0.07,0.07)*distance
        arrow.settling_hops=self.rng.choice((2,3))
        arrow.settling_height=min(0.15,0.035+0.008*abs(velocity[2]))
        arrow.velocity=(after_speed*cos(angle),after_speed*sin(angle),0.0)
        self._emit('landing',arrow=arrow.id,position=arrow.landing_origin,
                   planned_runout_m=distance,duration=arrow.settling_duration,
                   incoming_velocity=velocity)
        if remaining_tick_s>1e-9:self._advance_settling(arrow,remaining_tick_s)

    def _settling_position(self,arrow,elapsed):
        fraction=min(1.0,max(0.0,elapsed/arrow.settling_duration))
        progress=fraction*(2-fraction)  # Smooth deceleration to rest.
        ux,uy=arrow.settling_heading
        forward=arrow.settling_distance*progress
        sideways=arrow.settling_curve*sin(pi*progress)
        x0,y0,_=arrow.landing_origin
        hop_position=fraction*arrow.settling_hops
        hop=min(arrow.settling_hops-1,int(hop_position))
        height=arrow.settling_height*(0.45**hop)*sin(pi*(hop_position-hop)) if fraction<1 else 0.0
        return x0+ux*forward-uy*sideways,y0+uy*forward+ux*sideways,max(0.0,height)

    def _stop_settling(self,arrow,point,reason):
        origin=arrow.landing_origin
        super()._ground(arrow,point)
        self._emit('arrow_settled',arrow=arrow.id,position=arrow.position,reason=reason,
                   displacement_m=hypot(arrow.position[0]-origin[0],arrow.position[1]-origin[1]))

    def _advance_settling(self,arrow,dt):
        left=dt
        L,W=self.config['field']['length_m'],self.config['field']['width_m']
        radius=self.config['physics']['arrow_radius_m']
        obstacles=self.obstacles+self.rack_footprints
        while left>1e-9 and arrow.state=='settling':
            sub=min(left,0.025,arrow.settling_duration-arrow.settling_elapsed)
            if sub<=1e-9:
                self._stop_settling(arrow,arrow.position,'rest')
                break
            previous=arrow.position
            elapsed=arrow.settling_elapsed+sub
            desired=self._settling_position(arrow,elapsed)
            contacts=[]
            for axis,bound in ((0,0.0),(0,L),(1,0.0),(1,W)):
                outside=desired[axis]<=0 if bound==0 else desired[axis]>=bound
                delta=desired[axis]-previous[axis]
                if outside and abs(delta)>1e-12:
                    fraction=(bound-previous[axis])/delta
                    if -1e-9<=fraction<=1+1e-9:contacts.append((max(0.0,min(1.0,fraction)),'net'))
            for obstacle in obstacles:
                u=segment_box((*previous[:2],0.03),(*desired[:2],0.03),*obstacle.bounds(radius))
                if u is not None:contacts.append((u,'obstacle'))
            if contacts:
                u,reason=min(contacts)
                arrow.settling_elapsed+=sub*u
                self._stop_settling(arrow,lerp(previous,desired,u),reason)
                break
            arrow.position=desired
            arrow.velocity=tuple((b-a)/sub for a,b in zip(previous,desired))
            arrow.settling_elapsed=elapsed
            left-=sub
            if elapsed+1e-9>=arrow.settling_duration:
                self._stop_settling(arrow,desired,'rest')

    def _fly(self,dt,old_positions,new_positions,actions,rewards):
        # Dead arrows are advanced separately and never enter _contacts/_fly's
        # live-arrow collision queue, even during their visible low hops.
        for arrow in self.arrows.values():
            if arrow.state=='settling':self._advance_settling(arrow,dt)
        super()._fly(dt,old_positions,new_positions,actions,rewards)

    def get_observation(self,agent_id=None):
        obs=super().get_observation(agent_id)
        if agent_id is not None:
            # Radio memory is refreshed on physics ticks, not on reads. Still
            # reject any obsolete claim whose arrow has not yet become pickable.
            assignment=obs.get('supply_assignment')
            if assignment and self.arrows[assignment['id']].state!='ground':
                obs['supply_assignment']=None
        return obs

    def _record_frame(self):
        super()._record_frame()
        for row in self.trace[-1]['arrows']:
            arrow=self.arrows[row['id']]
            if arrow.state=='settling':
                row.update(landing_origin=arrow.landing_origin,
                           settling_elapsed=arrow.settling_elapsed,
                           settling_duration=arrow.settling_duration)

    def assert_invariants(self):
        super().assert_invariants()
        L,W=self.config['field']['length_m'],self.config['field']['width_m']
        for arrow in self.arrows.values():
            assert -1e-8<=arrow.position[0]<=L+1e-8
            assert -1e-8<=arrow.position[1]<=W+1e-8
            if arrow.state=='settling':
                assert arrow.carrier is None and arrow.flight_left==0
                assert arrow.landing_origin is not None

    def summary(self):
        row=super().summary()
        row.update(ground_landings=self.counts['landing'],settled_arrows=self.counts['arrow_settled'])
        return row
