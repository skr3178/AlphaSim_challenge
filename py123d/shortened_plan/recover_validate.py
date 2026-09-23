"""Recover frozen validation assets, then evaluate fixed candidates; no tuning."""
import datetime
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import run_screen as screen
from run_sweep import paired

sys.path.insert(0, str(screen.ROOT/'tools'))
from eval_common import asset_missing, source_log

OLD=Path('/home/skr/alpasim-challenge/nuplan-track')
EXPANSION=Path('/media/skr/SeagateHub1/alpasim-navtest-expansion-20260918')
RECOVERY=Path('/media/skr/SeagateHub1/alpasim-validation-recovery-20260922')


def main():
    out=screen.HERE/'artifacts'/('validation-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True)
    print('ARTIFACTS='+str(out),flush=True)
    state=dict(status='recovering',results=[],official_parity=False)
    def save():screen.save(out/'status.json',state)
    save()
    try:
        ids=[x for x in (screen.ROOT/'evaluation/scene-lists/py123d_validation.txt').read_text().splitlines() if x and not x.startswith('#')]
        dev=[x for x in (screen.ROOT/'evaluation/scene-lists/py123d_development400.txt').read_text().splitlines() if x and not x.startswith('#')]
        assert len(set(ids))==150
        assert not {source_log(s) for s in ids}&{source_log(s) for s in dev}
        screen.save(out/'scene_ids.json',ids)
        # Freeze code and candidate settings BEFORE looking at validation results.
        source=out/'source'
        shutil.copytree(screen.SOURCE/'src',source/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        screen.save(out/'source-sha256.json',{str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
        prior=json.loads((screen.HERE/'artifacts/sweep-20260922T070619Z/status.json').read_text())
        configs={r['arm']:r for r in prior['results'] if r['arm'] in ('baseline','combo_2','acceleration_weight_2p0')}
        assert len(configs)==3
        screen.save(out/'fixed-candidates.json',configs)
        missing=[s for s in ids if asset_missing(EXPANSION/'data',s)]
        assert len(missing)==6, f'Inventory changed: {len(missing)} missing; review before recovery'
        screen.save(out/'missing-scenes.json',missing)
        spec=importlib.util.spec_from_file_location('stager',screen.ROOT/'tools/download-navtest-expansion.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class RecoveryStager(module.Stager):
            def status(self,phase,**values):
                self.state.update(status=phase,**values)
                screen.save(out/'download-status.json',self.state)
        stager=RecoveryStager(screen.ROOT/'evaluation/downloads/2026-09-18-seagate/plan.json')
        stager.initialize()  # Holds original download lock; preserves original plan/status.
        shard=next(s for s in stager.plan['shards'] if s['name']=='part013.tar.gz')
        archive=stager.download(shard)  # Resume and verify full SHA-256 before extraction.
        RECOVERY.mkdir(exist_ok=True)
        marker=RECOVERY/'selected-scenes.json'
        if marker.exists():assert json.loads(marker.read_text())==missing
        else:
            assert not any(RECOVERY.iterdir()), 'Unmarked recovery destination'
            screen.save(marker,missing)
        for name in ('staging','receipts','data/navtest/assets','data/navtest/configs'):(RECOVERY/name).mkdir(parents=True,exist_ok=True)
        stager.root=RECOVERY;stager.data=RECOVERY/'data';stager.plan['missing_scene_ids']=missing
        for s in missing:shutil.copy2(OLD/'navtest/configs'/(s+'.yaml'),stager.data/'navtest/configs'/(s+'.yaml'))
        stager.extract(archive,shard)
        assert all(not asset_missing(stager.data,s) for s in missing), 'Required scenes not all in shard013; stop to inspect'
        stager.lock.close()
        # Compose a new runtime root. No writes to original cache or scene trees.
        data=out/'runtime-data'
        (data/'navtest/assets').mkdir(parents=True)
        (data/'navtest/configs').symlink_to(OLD/'navtest/configs',target_is_directory=True)
        (data/'nuplan_test').symlink_to(OLD/'nuplan_test',target_is_directory=True)
        roots={}
        for s in ids:
            root=stager.data if s in missing else EXPANSION/'data'
            assert not asset_missing(root,s),s
            (data/'navtest/assets'/s).symlink_to(root/'navtest/assets'/s,target_is_directory=True)
            roots[s]=str(root)
        # Validate extracted member sizes against verified-shard receipts.
        checked=set();total=0
        for receipts,root in [(EXPANSION/'receipts',EXPANSION/'data'),(RECOVERY/'receipts',RECOVERY/'data')]:
            for receipt in receipts.glob('*.json'):
                r=json.loads(receipt.read_text())
                for relative,size in r['files'].items():
                    scene=relative.split('/')[0]
                    if scene not in roots or str(root)!=roots[scene]:continue
                    p=root/'navtest/assets'/relative
                    assert p.is_file() and p.stat().st_size==size,(p,size)
                    checked.add(scene);total+=size
        assert checked==set(ids),'Missing receipt coverage'
        screen.save(out/'asset-audit.json',dict(scenes=150,source_logs=len({source_log(s) for s in ids}),bytes=total,roots=roots))
        state.update(status='assets_ready',runtime_data=str(data));save()
        if '--prepare-only' in sys.argv:
            state['status']='preparation_complete'
            return
        lock=open('/home/skr/alpasim-challenge/logs/.run-eval.lock','a')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert not subprocess.check_output(['docker','ps','-q'],text=True).strip(),'Other GPU containers running; stop safely'
        assert shutil.disk_usage(screen.ROOT).free>10*1024**3
        state['image_id']=subprocess.check_output(['docker','image','inspect',screen.IMAGE,'--format','{{.Id}}'],text=True).strip()
        mounts=(OLD,EXPANSION/'data',RECOVERY/'data')
        for name,scenes in [('smoke_validation',[ids[0]]),('baseline',ids),('combo_2',ids),('acceleration_weight_2p0',ids)]:
            state.update(status='evaluating',current=name);save()
            config=configs['baseline' if name=='smoke_validation' else name]
            r=screen.run_arm(out,source,name,config['stabilization_weight'],scenes,config['gains'],
                             predicted_yaw=config.get('predicted_yaw',False),data_root=data,extra_mounts=mounts)
            if name!='smoke_validation':
                def rows(n):return {r['clipgt_id']:r for r in json.loads((out/n/'simulation/aggregate/results-summary.json').read_text())['rollouts']}
                r['paired']=paired(rows('baseline'),rows(name))
            state['results'].append(r);save()
            lines=['# Frozen 150-scene validation','',
                   'Unseen source logs relative to local development; not proof of model-training disjointness or official parity.','',
                   '| Arm | Scenes | Score | At fault | Corridor | Progress | D2GT |','|---|---:|---:|---:|---:|---:|---:|']
            for row in state['results']:
                lines.append(f"| {row['arm']} | {row['scenes']} | {row['score']:.5f} | {row['collisions']:.0f} | {row['corridor_exits']:.0f} | {row['progress']:.4f} | {row['d2gt']:.3f} |")
            (out/'COMPARISON.md').write_text('\n'.join(lines)+'\n')
            print('COMPLETED '+name,flush=True)
        state['status']='completed'
    except BaseException as e:
        state.update(status='failed',error=repr(e));raise
    finally:save()


if __name__=='__main__':main()
