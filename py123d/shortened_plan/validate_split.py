"""Run available144 while recovery proceeds, then missing6; merge per scene."""
import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import run_screen as screen
from run_sweep import paired
from recover_validate import OLD, EXPANSION, RECOVERY
from eval_common import asset_missing


def main():
    recovery_status=Path(sys.argv[1])
    out=screen.HERE/'artifacts'/('split-validation-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True);print('ARTIFACTS='+str(out),flush=True)
    state=dict(status='starting',current=None,results=[],recovery_status=str(recovery_status))
    def save():screen.save(out/'status.json',state)
    save()
    try:
        lock=open('/home/skr/alpasim-challenge/logs/.run-eval.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert not subprocess.check_output(['docker','ps','-q'],text=True).strip()
        original=screen.HERE/'artifacts/validation-20260922T095904Z'
        ids=json.loads((original/'scene_ids.json').read_text())
        missing=json.loads((original/'missing-scenes.json').read_text())
        available=[s for s in ids if s not in missing]
        assert len(available)==144 and len(missing)==6
        configs=json.loads((original/'fixed-candidates.json').read_text())
        screen.save(out/'fixed-candidates.json',configs)
        screen.save(out/'batches.json',dict(available144=available,missing6=missing))
        source=out/'source';shutil.copytree(original/'source',source)
        screen.save(out/'source-sha256.json',{str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
        data=out/'runtime-data';(data/'navtest/assets').mkdir(parents=True)
        (data/'navtest/configs').symlink_to(OLD/'navtest/configs',target_is_directory=True)
        (data/'nuplan_test').symlink_to(OLD/'nuplan_test',target_is_directory=True)
        mounts=(OLD,EXPANSION/'data',RECOVERY/'data')
        # Do not mount the recovery directory until it exists.
        def stage(scenes,root):
            receipts=list((root.parent/'receipts').glob('*.json'))
            checked=set()
            for f in receipts:
                for relative,size in json.loads(f.read_text())['files'].items():
                    scene=relative.split('/')[0]
                    if scene not in scenes:continue
                    p=root/'navtest/assets'/relative
                    assert p.is_file() and p.stat().st_size==size,p
                    checked.add(scene)
            assert checked==set(scenes)
            for scene in scenes:
                assert not asset_missing(root,scene),scene
                (data/'navtest/assets'/scene).symlink_to(root/'navtest/assets'/scene,target_is_directory=True)
        stage(available,EXPANSION/'data')
        state['status']='evaluating';save()
        for batch,scenes in [('available144',available),('missing6',missing)]:
            if batch=='missing6':
                state['status']='waiting_for_recovery';save()
                deadline=time.monotonic()+14400
                while True:
                    if recovery_status.exists():
                        r=json.loads(recovery_status.read_text())
                        if r['status']=='failed':raise RuntimeError('Recovery failed: '+r.get('error',''))
                        if r['status']=='preparation_complete':break
                    if time.monotonic()>deadline:raise TimeoutError('Recovery not ready; partial results retained')
                    time.sleep(30)
                stage(missing,RECOVERY/'data')
            arm_list=[('smoke_available', [scenes[0]])] if batch=='available144' else []
            arm_list += [(name,scenes) for name in ('baseline','combo_2','acceleration_weight_2p0')]
            for name,arm_ids in arm_list:
                arm=batch+'_'+name;state.update(status='evaluating',current=arm);save()
                config=configs['baseline' if name=='smoke_available' else name]
                assert shutil.disk_usage(screen.ROOT).free>8*1024**3
                result=screen.run_arm(out,source,arm,config['stabilization_weight'],arm_ids,config['gains'],
                                     predicted_yaw=config.get('predicted_yaw',False),data_root=data,
                                     extra_mounts=tuple(p for p in mounts if p.exists()))
                state['results'].append(result);save();print('COMPLETED '+arm,flush=True)
        combined={}
        for name in ('baseline','combo_2','acceleration_weight_2p0'):
            rows=[]
            for batch in ('available144','missing6'):
                rows+=json.loads((out/(batch+'_'+name)/'simulation/aggregate/results-summary.json').read_text())['rollouts']
            assert len(rows)==150 and {r['clipgt_id'] for r in rows}==set(ids)
            combined[name]={r['clipgt_id']:r for r in rows}
            screen.save(out/(name+'-combined-rollouts.json'),rows)
        results=[]
        for name,rows in combined.items():
            results.append(dict(arm=name,scenes=150,score=sum(r['score'] for r in rows.values())/150,
                                collisions=sum(r['metrics']['collision_at_fault'] for r in rows.values()),
                                corridor_exits=sum(r['metrics']['left_corridor_laterally'] for r in rows.values()),
                                paired=paired(combined['baseline'],rows)))
        screen.save(out/'combined-results.json',results)
        lines=['# Complete 150-scene validation','', 'Per-scene merge of fixed 144 + 6 batches, not an average of batch averages.','',
               '| Arm | Score | Delta | At fault | Corridor | New safety failures |','|---|---:|---:|---:|---:|---:|']
        for r in results:lines.append(f"| {r['arm']} | {r['score']:.5f} | {r['paired']['delta']:+.5f} | {r['collisions']:.0f} | {r['corridor_exits']:.0f} | {r['paired']['new_safety_failures']} |")
        (out/'COMPARISON.md').write_text('\n'.join(lines)+'\n')
        state['status']='completed'
    except BaseException as e:state.update(status='failed',error=repr(e));raise
    finally:save()


if __name__=='__main__':main()
