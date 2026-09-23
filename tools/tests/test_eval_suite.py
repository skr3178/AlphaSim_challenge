"""Metadata-only tests: no simulator, GPU, network or production asset writes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from eval_common import load_manifest, load_yaml, scene_ids, source_log

spec = importlib.util.spec_from_file_location("eval_suite", TOOLS / "eval-suite.py")
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.runs = self.root / "runs"
        self.output = self.root / "evaluation"
        self.public = self.root / "public.yaml"
        self.ids = []
        # Four cities, six logs/city, two clips/log. Both clips share one log
        # but have different recording windows to detect accidental window splits.
        for city_idx, city in enumerate(("us-nv-las-vegas-strip", "us-ma-boston",
                                          "us-pa-pittsburgh-hazelwood", "sg-one-north")):
            for log_idx in range(6):
                for clip in range(2):
                    scene = f"2021.09.{city_idx + 1:02d}.10.{log_idx:02d}.00_veh-01_{clip:05d}_00100-{clip:016x}"
                    self.ids.append(scene)
                    self.write(self.data / "navtest/configs" / f"{scene}.yaml",
                               f"!!python/object:any.InertType\ncentral_log: {scene.rsplit('-', 1)[0]}\ncity: {city}\n")
        self.write(self.public, "scenes:\n  scene_ids:\n" + "".join(f"    - {s}\n" for s in self.ids))
        self.summary = self.runs / "old/aggregate/results-summary.json"
        self.write(self.summary, json.dumps({"rollouts": [{"clipgt_id": self.ids[0], "scene_score": .9}]}))

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def build(self, **kwargs):
        return suite.build_manifest(self.public, self.data, [self.summary], 20260911,
                                    kwargs.pop("validation_size", 10), **kwargs)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(TOOLS / "eval-suite.py"),
                               "--public-scenes", str(self.public), "--data-root", str(self.data),
                               "--runs-root", str(self.runs), "--output", str(self.output),
                               "--validation-size", "10", *args], capture_output=True, text=True)

    def validate(self, manifest):
        path = self.root / "manifest.json"
        self.write(path, json.dumps(manifest))
        return load_manifest(path)

    def add_assets(self, scene):
        for name in ("video_scene_dict.pkl", "road_height_map/road_height_map.npy", "background/test.ckpt"):
            self.write(self.data / "navtest/assets" / scene / name, "fixture")

    def test_partition_and_source_log_separation(self):
        manifest = self.validate(self.build())
        groups = manifest["suites"]
        self.assertEqual(len(groups["py123d_validation"]), 10)
        self.assertIn(self.ids[1], groups["py123d_seen_log_extension"])
        exposed = {source_log(self.ids[0])}
        val = {source_log(s) for s in groups["py123d_validation_pool"]}
        holdout = {source_log(s) for s in groups["py123d_holdout"]}
        self.assertFalse(exposed & (val | holdout))
        self.assertFalse(val & holdout)

    def test_selection_ignores_scores_assets_and_input_order(self):
        before = self.build()["suites"]
        self.write(self.summary, json.dumps({"rollouts": [{"clipgt_id": self.ids[0], "scene_score": 0}]}))
        self.add_assets(self.ids[3])
        self.write(self.public, "scenes:\n  scene_ids:\n" + "".join(f"    - {s}\n" for s in reversed(self.ids)))
        self.assertEqual(before, self.build()["suites"])

    def test_unfinished_run_is_quarantined(self):
        planned = self.runs / "unfinished/generated-user-config-0.yaml"
        self.write(planned, f"scenes:\n  - scene_id: {self.ids[2]}\n")
        manifest = self.build(resolved_configs=[planned])
        self.assertIn(self.ids[2], manifest["suites"]["py123d_development400"])
        self.assertIn(self.ids[3], manifest["suites"]["py123d_seen_log_extension"])
        self.assertFalse(manifest["scenes"][self.ids[2]]["previously_evaluated"])
        self.validate(manifest)

    def test_rejects_oversized_validation(self):
        with self.assertRaisesRegex(ValueError, "only .* available"):
            self.build(validation_size=1000)

    def test_no_fresh_city_is_disclosed(self):
        exposed = self.ids[36:]
        self.write(self.summary, json.dumps({"rollouts": [{"clipgt_id": s} for s in exposed]}))
        manifest = self.build()
        self.assertIn("No unseen source logs in: singapore.", manifest["limitations"])

    def test_rejects_duplicate_public_ids(self):
        self.write(self.public, f"scenes:\n  scene_ids:\n    - {self.ids[0]}\n    - {self.ids[0]}\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            scene_ids(self.public)

    def test_rejects_log_leakage_on_reload(self):
        manifest = self.build()
        val = manifest["suites"]["py123d_validation_pool"]
        scene = val.pop()
        # The other clip from this log remains in the pool.
        manifest["suites"]["py123d_validation"] = [s for s in val][:10]
        manifest["suites"]["py123d_holdout"].append(scene)
        with self.assertRaisesRegex(ValueError, "source-log leakage"):
            self.validate(manifest)

    def test_assets_and_metadata_drift(self):
        manifest = self.build()
        self.add_assets(self.ids[0])
        report = suite.availability(manifest, self.data)
        self.assertEqual(report["suites"]["py123d_development400"]["available"], 1)
        self.write(self.data / "navtest/assets" / self.ids[0] / "background/test.ckpt", "")
        config = self.data / "navtest/configs" / f"{self.ids[0]}.yaml"
        self.write(config, config.read_text() + "# changed\n")
        report = suite.availability(manifest, self.data)
        self.assertIn(self.ids[0], report["missing"])
        self.assertEqual(report["changed_configs"], [self.ids[0]])

    def test_frozen_cli_configs_and_nonzero_preflight(self):
        result = self.cli("--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest_path = self.output / "public-suite.json"
        frozen = manifest_path.read_bytes()
        manifest = load_manifest(manifest_path)
        for name, ids in manifest["suites"].items():
            if ids:
                cfg = self.output / "configs/nuplan_scenes" / f"{name}.yaml"
                self.assertEqual(scene_ids(cfg), ids)
                self.assertEqual(load_yaml(cfg)["scenes"]["test_suite_id"], "null")
                self.assertEqual((self.output / "scene-lists" / f"{name}.txt").read_text().splitlines(), ids)
        self.assertEqual(self.cli("--write").returncode, 2)
        self.assertEqual(self.cli("--check-suite", "unknown").returncode, 2)
        result = self.cli("--check-suite", "py123d_validation")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(frozen, manifest_path.read_bytes())
        self.add_assets(self.ids[0])
        self.assertEqual(self.cli("--check-suite", "py123d_development400").returncode, 0)

    def test_inventory_snapshot_does_not_change_manifest(self):
        self.assertEqual(self.cli("--write").returncode, 0)
        frozen = (self.output / "public-suite.json").read_bytes()
        report = self.root / "refreshed-inventory.json"
        self.assertEqual(self.cli("--inventory-output", str(report)).returncode, 0)
        self.assertTrue(report.is_file())
        self.assertEqual(self.cli("--inventory-output", str(report)).returncode, 2)
        self.assertEqual(frozen, (self.output / "public-suite.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
