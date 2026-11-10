from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'configs/suzhou_2026.json';c=json.loads(p.read_text())
c['schema_version']='suzhou-v3-roles-logistics'
c['ruleset_name']='苏州 V3 · 岗位与箭支补给'
c['rules']['carry_limit']=4
c['policy'].update(name='suzhou_v3_roles_logistics',opening_gather_quota=3)
c['human_shooting'].update(novice_angle_sd_rad=.065,expert_angle_sd_rad=.018,poor_release_probability=.09)
c['ground_runout'].update(direction_sd_degrees=6,max_deviation_degrees=16)
c['v3']={'role_order':['high_flank','high_cover','center_1','center_2','low_cover','revive_lane'],
 'role_names':['高边','高掩体','中一','中二','矮掩体','复活路'],
 'vacancy_priority':['revive_lane','low_cover','high_cover','high_flank','center_2','center_1'],
 'reassign_delay_s':1.3,'reassign_interval_s':2.5,'role_min_hold_s':4,
 'revive_decision_delay_s':1.0,'snap_aim_s':.14,'snap_error_multiplier':1.25,
 'loaded_speed_multiplier':.89,'nocking_speed_multiplier':.82,'extra_carry_speed_cost':.035,
 'extra_carry_error_cost':.07,'throw_range_m':7.0,'throw_cooldown_s':1.0,
 'toss_direction_sd_degrees':24,'toss_max_deviation_degrees':55,'hit_pause_s':.85,
 'death_discard_delay_s':.28,'death_discard_range_m':2.2,'waiting_spacing_m':.8,
 'pickup_stall_timeout_s':2.4,'pickup_approach_radius_m':.61,
 'notes':'User V3 adds casual immediate dying-discard within first steps. This is an explicit simulation override of earlier draft text requiring dropped arrows.'}
p.write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n')
print('Configured V3')
