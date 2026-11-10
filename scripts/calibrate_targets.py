"""Geometric calibration, not a fitted or forced hit probability."""
import json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from build_suzhou import config,SuzhouEnvironment
from archery_tag_balance.geometry import advance_arrow


def main():
    results=[];count=800
    for rating in [.65,.75,.95]:
        for quick in [True,False]:
            e=SuzhouEnvironment(config());e.reset(62002,record=False)
            a=e.agents['attack_5'];a.aim_key='rack:revive:4';a.snap_revive=quick;a.steady_aim_s=0 if quick else 2.
            a.player_model['skills']['target_accuracy']=rating
            rack=e.skirmish_racks['revive'];masks=[set(range(5)),{0,4},{4}];hits=[0,0,0];sigmas=[]
            for i in range(count):
                v=e._launch_velocity(a,(10,2,1.25),rack.spot(4));drag=e.config['physics']['linear_drag_s_inv'];t=-math.log(1-drag*6/v[0])/drag
                q,_=advance_arrow((10,2,1.25),v,t,9.81,drag)
                disks={k for k in range(5) if math.hypot(q[1]-rack.spot(k)[1],q[2]-rack.spot(k)[2])<=e.rack_specs['revive']['spot_radii_m'][k]+.0125}
                for j,mask in enumerate(masks):hits[j]+=bool(disks&mask)
                sigmas.append(e.last_launch[a.id]['sigma'])
            assert hits[0]>=hits[1]>=hits[2]
            results.append(dict(target_skill=rating,release='quick_after_movement' if quick else 'steady_aim',distance_m=6,trials=count,geometric_hits_with_5_2_1_live_points=hits,geometric_rates=[round(x/count,4) for x in hits],angular_sigma_rad=sum(sigmas)/len(sigmas)))
    report=dict(rows=results,notes=['Same 800 trajectories reused for each remaining-disk mask within a row; all aimed at the center.','An incidental adjacent live disk is a success. Removed disks are not successes.','These are geometric contacts before the separate knockdown check, not measured player probabilities.','No coefficient depends on the number of remaining disks. Changing aim point also changes real geometry.'])
    (ROOT/'reports/target_geometry_calibration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
