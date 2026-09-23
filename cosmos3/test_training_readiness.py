"""CPU-only audit-helper tests, using synthetic temporary metadata."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from audit_training_readiness import classify, inspect_db, metadata_hours, window_id, union_duration


class ReadinessTests(unittest.TestCase):
    def test_source_log_ignores_recording_window(self):
        a = window_id("2021.08.17.13.10.50_veh-08_00122_00295")
        b = window_id("2021.08.17.13.10.50_veh-08_00313_00564")
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1:], (122, 295))
        with self.assertRaises(ValueError):
            window_id("arbitrary.db")

    def test_union_deduplicates_nested_and_overlapping_windows(self):
        self.assertEqual(union_duration([(0, 10), (3, 8), (9, 20), (30, 40)]), 30)
        self.assertEqual(union_duration([]), 0)
        rows = [{"source_log": "a", "window_start_s": 0, "window_end_s": 3600},
                {"source_log": "a", "window_start_s": 1800, "window_end_s": 3600},
                {"source_log": "b", "window_start_s": 0, "window_end_s": 3600}]
        self.assertEqual(metadata_hours(rows), 2)

    def test_protection_is_log_and_city_date_level(self):
        row = {"collection": "train_boston", "source_log": "protected", "city": "boston", "date": "2021-09-09"}
        reasons = classify(row, {"protected"}, {("boston", "2021-09-09")}, set(), set())
        self.assertEqual(reasons, ["public_navtest_source_log", "public_navtest_city_date"])
        row["source_log"] = "another_log"
        self.assertEqual(classify(row, set(), {("boston", "2021-09-09")}, set(), set()), ["public_navtest_city_date"])

    def test_official_val_and_mini_do_not_become_training(self):
        for collection in ("official_val", "mini_quarantine"):
            row = {"collection": collection, "source_log": "a", "city": "boston", "date": "2021-01-01"}
            self.assertTrue(classify(row, set(), set(), set(), set()))

    def test_image_references_are_not_available_footage(self):
        with tempfile.TemporaryDirectory(prefix="cosmos-readiness-test-") as temp:
            path = Path(temp) / "2021.08.17.13.10.50_veh-08_00122_00295.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE log(logfile TEXT,location TEXT,date TEXT);
                CREATE TABLE camera(token TEXT,channel TEXT,width INTEGER,height INTEGER,translation BLOB,rotation BLOB,intrinsic BLOB);
                CREATE TABLE image(filename_jpg TEXT,timestamp INTEGER,camera_token TEXT);
                CREATE TABLE scene(roadblock_ids TEXT);
                CREATE TABLE ego_pose(timestamp INTEGER,x REAL,y REAL,z REAL,qw REAL,qx REAL,qy REAL,qz REAL,vx REAL,vy REAL,angular_rate_z REAL);
            """)
            conn.execute("INSERT INTO log VALUES(?,?,?)", (path.stem,"us-ma-boston","2021-08-17"))
            conn.execute("INSERT INTO camera VALUES('f','CAM_F0',1920,1080,X'01',X'01',X'01')")
            for i in range(3):
                conn.execute("INSERT INTO image VALUES(?,?,?)", (f"{path.stem}/CAM_F0/{i}.jpg",1_000_000+i*100_000,"f"))
            conn.execute("INSERT INTO scene VALUES('1 2')")
            conn.commit()
            conn.close()
            before = path.read_bytes()
            row = inspect_db(path, "train_boston", {})
            self.assertEqual(row["front_image_references"], 3)
            self.assertEqual(row["missing_front_image_files"], 3)
            self.assertEqual(row["verified_usable_footage_hours"], 0)
            self.assertEqual(row["footage_status"], "missing_front_images")
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
