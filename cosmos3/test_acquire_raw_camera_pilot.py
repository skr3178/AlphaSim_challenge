import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from cosmos3.acquire_raw_camera_pilot import ARCHIVE_PREFIX, BoundedReader, Ledger, validate_member


class AcquisitionSafetyTests(unittest.TestCase):
    def test_reader_caps_bytes(self):
        reader = BoundedReader(io.BytesIO(b"0123456789"), 4)
        self.assertEqual(reader.read(100), b"0123")
        with self.assertRaises(ValueError):
            reader.read(1)
        self.assertEqual(reader.count, 4)

    def test_ledger_reserves_interrupted_transfers(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.jsonl"
            ledger = Ledger(path, cap=100)
            first = ledger.begin(60, "test")
            with self.assertRaises(RuntimeError):
                ledger.begin(50, "overflow")
            self.assertEqual(Ledger(path, cap=100).charged, 60)
            ledger.finish(first, 20)
            self.assertEqual(Ledger(path, cap=100).charged, 20)

    def test_path_and_link_rejection(self):
        window = "2021.08.19.14.17.23_veh-28_00021_00114"
        name = "fe95dd8ca9f85644.jpg"
        expected = {f"{window}/CAM_F0/{name}": {}}
        member = tarfile.TarInfo(f"{ARCHIVE_PREFIX}{window}/CAM_F0/{name}")
        member.size = 100
        self.assertEqual(validate_member(member, window, expected)[0], name)
        for bad in ("../" + name, "/" + name, "unlisted.jpg", "sub/" + name):
            member.name = f"{ARCHIVE_PREFIX}{window}/CAM_F0/{bad}"
            with self.assertRaises(ValueError):
                validate_member(member, window, expected)
        member.name = f"{ARCHIVE_PREFIX}{window}/CAM_F0/{name}"
        member.type = tarfile.SYMTYPE
        with self.assertRaises(ValueError):
            validate_member(member, window, expected)


if __name__ == "__main__":
    unittest.main()
