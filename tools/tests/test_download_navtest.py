"""Tiny synthetic archives only: no network, real data writes, GPU or simulation."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("download_navtest", TOOLS / "download-navtest-expansion.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SCENE = "2021.09.09.10.00.00_veh-01_00000_00100-0123456789abcdef"
OTHER = "2021.09.09.11.00.00_veh-01_00000_00100-0123456789abcdef"


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = self.root / "plan.json"
        self.plan.write_text(json.dumps({"destination": str(self.root), "missing_scene_ids": [SCENE]}))
        self.job = module.Stager(self.plan)
        for name in ["archives", "staging", "receipts", "data/navtest/assets", "data/navtest/configs"]:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / "data/navtest/configs" / f"{SCENE}.yaml").write_text("config")

    def make_archive(self):
        path = self.root / "archives/part002.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for scene in [SCENE, OTHER]:
                for name in ["video_scene_dict.pkl", "background/model.ckpt", "road_height_map/road_height_map.npy"]:
                    info = tarfile.TarInfo(f"navtest/assets/{scene}/{name}")
                    data = b"fixture"
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        shard = {"name": path.name, "size": path.stat().st_size,
                 "sha256": module.digest(path), "url": "https://example.invalid/archive"}
        return path, shard

    def test_rejects_path_traversal(self):
        for path in ["/tmp/escape", "navtest/assets/../escape", "navtest\\assets\\escape", "other/place"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.safe_member(tarfile.TarInfo(path))

    def test_rejects_links_and_devices(self):
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]:
            info = tarfile.TarInfo(f"navtest/assets/{SCENE}/escape")
            info.type = kind
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                module.safe_member(info)

    def test_accepts_normal_member(self):
        info = tarfile.TarInfo(f"./navtest/assets/{SCENE}/background/model.ckpt")
        self.assertEqual(str(module.safe_member(info)), f"{SCENE}/background/model.ckpt")

    def test_extracts_only_selected_scenes_and_can_resume_promotion(self):
        path, shard = self.make_archive()
        with patch.object(module, "require_space"):
            self.job.extract(path, shard)
            # Re-reading a verified shard must preserve and validate existing output.
            self.job.extract(path, shard)
        self.assertFalse((self.root / "data/navtest/assets" / OTHER).exists())
        self.assertTrue(self.job.completed(shard))
        self.assertFalse(module.asset_missing(self.job.data, SCENE))
        receipt = json.loads((self.root / "receipts" / (path.name + ".json")).read_text())
        self.assertEqual(receipt["scene_ids"], [SCENE])
        self.assertEqual(receipt["archive_scene_ids"], sorted([SCENE, OTHER]))

    def test_changed_output_is_not_silently_accepted(self):
        path, shard = self.make_archive()
        with patch.object(module, "require_space"):
            self.job.extract(path, shard)
        (self.job.data / "navtest/assets" / SCENE / "video_scene_dict.pkl").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "Previously staged file"):
            self.job.completed(shard)

    def test_existing_archive_checksum_is_verified(self):
        path, shard = self.make_archive()
        self.assertEqual(self.job.download(shard), path)
        shard["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "verification failed"):
            self.job.download(shard)
        self.assertTrue(path.exists())

    def test_complete_partial_is_verified_and_promoted_without_network(self):
        path, shard = self.make_archive()
        partial = path.with_suffix(path.suffix + ".part")
        path.rename(partial)
        with patch.object(module.subprocess, "Popen") as popen:
            self.assertEqual(self.job.download(shard), path)
            popen.assert_not_called()
        self.assertTrue(path.exists())

    def test_incomplete_download_uses_resume_and_verifies_bytes(self):
        data = b"a complete synthetic download"
        shard = {"name": "part002.tar.gz", "size": len(data),
                 "sha256": hashlib.sha256(data).hexdigest(), "url": "https://example.invalid/shard"}
        partial = self.root / "archives/part002.tar.gz.part"
        partial.write_bytes(data[:5])

        def fake_curl(command):
            self.assertIn("--continue-at", command)
            self.assertEqual(command[command.index("--output") + 1], str(partial))
            with partial.open("ab") as stream:
                stream.write(data[5:])
            return Mock(returncode=0, poll=Mock(return_value=0))

        with patch.object(module.subprocess, "Popen", side_effect=fake_curl), patch.object(module, "require_space"):
            path = self.job.download(shard)
        self.assertEqual(path.read_bytes(), data)

    def test_low_disk_space_fails_closed(self):
        with patch.object(module.shutil, "disk_usage", return_value=Mock(free=100)):
            with self.assertRaisesRegex(RuntimeError, "Insufficient space"):
                module.require_space(self.root, 1000)


if __name__ == "__main__":
    unittest.main()
