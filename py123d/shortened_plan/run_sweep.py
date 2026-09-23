"""Bounded single-variable screening, gated combinations, repeats and validation.

Runs sequentially under the same global GPU lock as other evaluation launchers.
Never trains, builds an image, uploads or submits. Validation membership is fixed.
"""
import argparse
import datetime
import fcntl
import hashlib
import itertools
import json
import shutil
import socket
import subprocess
from pathlib import Path

import run_screen as screen

GRID = {
    'long_position_weight': [.5, 4., 8.],
    'lat_position_weight': [.25, 3., 8.],
    'heading_weight': [.25, 3., 8.],
    'acceleration_weight': [0., .5, 2.],
    'rel_front_steering_angle_weight': [.5, 2., 9.],
    'rel_acceleration_weight': [.1, 3., 8.],
    'idx_start_penalty': [0, 5, 15],
}


def validate(arm):
    assert set(arm['gains']) == set(GRID)
    for k,v in arm['gains'].items():
        assert 0 <= v <= (19 if k == 'idx_start_penalty' else 10)
        if k == 'idx_start_penalty': assert type(v) is int
    assert 0 <= arm['weight'] <= .25


def arms():
    base = json.loads((screen.HERE/'gains/baseline.json').read_text())
    result = [dict(name='baseline', gains=base, weight=0., yaw=False, changes={})]
    for key, values in GRID.items():
        for value in values:
            result.append(dict(name=key+'_'+str(value).replace('.','p'),
                               gains={**base,key:value},weight=0.,yaw=False,changes={key:value}))
    result.append(dict(name='predicted_yaw',gains=base,weight=0.,yaw=True,changes={'yaw':True}))
    for weight in [.05,.15,.25]:
        result.append(dict(name='stabilization_'+str(weight).replace('.','p'),gains=base,weight=weight,yaw=False,changes={'weight':weight}))
    for a in result: validate(a)
    return result


def rows(output, name):
    return {r['clipgt_id']:r for r in json.loads((output/name/'simulation/aggregate/results-summary.json').read_text())['rollouts']}


def paired(base, candidate):
    assert set(base)==set(candidate)
    delta=[candidate[k]['score']-base[k]['score'] for k in base]
    new_safety=sum(any(candidate[k]['metrics'][m]>base[k]['metrics'][m] for m in
                       ('collision_at_fault','left_corridor_laterally')) for k in base)
    return dict(delta=sum(delta)/len(delta), better=sum(v>1e-6 for v in delta),
                worse=sum(v< -1e-6 for v in delta), new_safety_failures=new_safety)


def eligible(result):
    # Development heuristic, NOT a significance test or safety certificate.
    return result['paired']['delta'] >= .005 and result['paired']['new_safety_failures']==0


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    configs=arms()
    if args.dry_run:
        print(json.dumps(configs,indent=2));return
    lock=open('/home/skr/alpasim-challenge/logs/.run-eval.lock','a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert not subprocess.check_output(['docker','ps','-q'],text=True).strip(), 'Other Docker work is running'
    with socket.socket() as s:s.bind(('127.0.0.1',screen.PORT))
    assert shutil.disk_usage(screen.ROOT).free>15*1024**3
    out=screen.HERE/'artifacts'/('sweep-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True)
    print('ARTIFACTS='+str(out),flush=True)
    selection=json.loads((screen.HERE/'artifacts/20260922T060953Z/selection.json').read_text())
    ids=[r['scene'] for r in selection];assert len(set(ids))==24
    screen.save(out/'selection.json',selection);screen.save(out/'sweep-manifest.json',configs)
    source=out/'source'
    shutil.copytree(screen.SOURCE/'src',source/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    screen.save(out/'source-sha256.json',{str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
    state=dict(status='running',current=None,results=[],planned_coarse=len(configs),official_parity=False,
               runtime_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=screen.RUNTIME,text=True).strip(),
               image_id=subprocess.check_output(['docker','image','inspect',screen.IMAGE,'--format','{{.Id}}'],text=True).strip())
    # Protect validation before any tuning results; never substitute development IDs.
    validation=[s for s in (screen.ROOT/'evaluation/scene-lists/py123d_validation.txt').read_text().splitlines() if s and not s.startswith('#')]
    assert len(set(validation))==150 and not set(ids)&set(validation)
    screen.save(out/'validation-scene-ids.json',validation)
    missing=[s for s in validation if not (Path('/home/skr/alpasim-challenge/nuplan-track/navtest/assets')/s).exists()]
    state['validation_assets_missing']=len(missing)

    def persist():
        screen.save(out/'status.json',state)
        lines=['# Broad Py123d development sweep','',
               'Same outcome-stratified 24 scenes. Development selection only, not a leaderboard estimate.','',
               '| Arm | N | Score | Paired delta | At-fault | Corridor | New safety failures | Plans |',
               '|---|---:|---:|---:|---:|---:|---:|---:|']
        for r in state['results']:
            p=r.get('paired',{})
            lines.append(f"| {r['arm']} | {r['scenes']} | {r['score']:.5f} | {p.get('delta',0):+.5f} | {r['collisions']:.0f} | {r['corridor_exits']:.0f} | {p.get('new_safety_failures',0)} | {r['planning_calls']} |")
        (out/'COMPARISON.md').write_text('\n'.join(lines)+'\n')

    def run(config,name=None,scene_ids=ids,baseline_name='baseline'):
        name=name or config['name'];state['current']=name;persist()
        assert shutil.disk_usage(screen.ROOT).free>8*1024**3, 'Low disk space'
        r=screen.run_arm(out,source,name,config['weight'],scene_ids,config['gains'],predicted_yaw=config['yaw'])
        r['paired']=paired(rows(out,baseline_name),rows(out,name))
        r['config']=config
        state['results'].append(r);persist();print('COMPLETED '+name,flush=True)
        return r

    try:
        for config in configs:run(config)
        promising=sorted([r for r in state['results'][1:] if eligible(r)],key=lambda r:r['paired']['delta'],reverse=True)
        # Keep only strongest candidate per knob before trying at most six pairs.
        unique=[];seen=set()
        for r in promising:
            key=next(iter(r['config']['changes']))
            if key not in seen:unique.append(r);seen.add(key)
        for i,(a,b) in enumerate(itertools.islice(itertools.combinations(unique[:4],2),6)):
            changes={**a['config']['changes'],**b['config']['changes']}
            config=dict(name=f'combo_{i+1}',gains={**configs[0]['gains'],**{k:v for k,v in changes.items() if k in GRID}},
                        weight=changes.get('weight',0.),yaw=changes.get('yaw',False),changes=changes)
            validate(config);r=run(config)
            if eligible(r):promising.append(r)
        promising.sort(key=lambda r:r['paired']['delta'],reverse=True)
        finalists=promising[:2]
        if finalists:
            run(configs[0],name='repeat_baseline')
            confirmed=[]
            for i,r in enumerate(finalists):
                repeat=run(r['config'],name=f'repeat_candidate_{i+1}',baseline_name='repeat_baseline')
                if eligible(repeat):confirmed.append(r['config'])
            state['repeat_confirmed']=[c['name'] for c in confirmed]
            if confirmed and not missing:
                run(configs[0],name='validation_baseline',scene_ids=validation,baseline_name='validation_baseline')
                for i,c in enumerate(confirmed):run(c,name=f'validation_candidate_{i+1}',scene_ids=validation,baseline_name='validation_baseline')
            elif confirmed:
                state['validation_status']='not_run_missing_runtime_assets; no finalist promoted'
        else:state['conclusion']='No coarse candidate met the predeclared gain/safety gate; keep baseline'
        state['status']='completed_screening'
    except BaseException as e:
        state.update(status='failed',error=repr(e));raise
    finally:persist()


if __name__=='__main__':main()
