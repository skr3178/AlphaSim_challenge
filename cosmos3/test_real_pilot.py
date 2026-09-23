"""CPU-only tests of the real-pilot manifest's source-log isolation."""
import unittest

from prepare_real_pilot import membership


class RealPilotTests(unittest.TestCase):
    def fixture(self):
        return {"scenes": {
            "train-a": {"source_log": "training-log"},
            "train-b": {"source_log": "training-log"},
            "another-window": {"source_log": "training-log"},
            "val": {"source_log": "validation-log"},
            "holdout": {"source_log": "holdout-log"},
        }, "suites": {
            "py123d_development400": ["train-a", "train-b"],
            "py123d_seen_log_extension": ["another-window"],
            "py123d_validation": ["val"],
            "py123d_validation_pool": ["val"],
            "py123d_holdout": ["holdout"],
        }}

    def test_excludes_entire_log_including_unselected_recordings(self):
        value = membership(self.fixture(), ["train-a"])
        self.assertEqual(value["excluded_scene_ids_for_candidate_evaluation"],
                         ["another-window", "train-a", "train-b"])

    def test_preserves_protected_suite_membership(self):
        fixture = self.fixture()
        value = membership(fixture, ["train-a"])
        self.assertEqual(value["protected_suites"]["py123d_holdout"], ["holdout"])
        self.assertEqual(fixture["suites"]["py123d_development400"], ["train-a", "train-b"])

    def test_rejects_duplicate_or_empty_samples(self):
        for selected in ([], ["train-a", "train-a"]):
            with self.assertRaises(ValueError):
                membership(self.fixture(), selected)

    def test_rejects_samples_outside_development(self):
        with self.assertRaises(ValueError):
            membership(self.fixture(), ["val"])

    def test_rejects_shared_validation_or_holdout_log(self):
        for scene in ("val", "holdout"):
            fixture = self.fixture()
            fixture["scenes"][scene]["source_log"] = "training-log"
            with self.assertRaisesRegex(ValueError, "overlaps protected suite"):
                membership(fixture, ["train-a"])


if __name__ == "__main__":
    unittest.main()
