import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import reviewer
import splitter


class PoiInputTests(unittest.TestCase):
    def test_loads_string_and_description_formats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "pois.json").write_text(json.dumps({
                "pois": [
                    "Namsan Seoul Tower",
                    {"name": "Hongdae", "description": "Youth district with street art"},
                ]
            }), encoding="utf-8")
            specs = splitter.load_pois_json(temp_dir)
        self.assertEqual(
            specs[0],
            {"name": "Namsan Seoul Tower", "name_zh": "", "description": ""},
        )
        self.assertEqual(specs[1]["description"], "Youth district with street art")

    def test_rejects_invalid_poi_objects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "pois.json").write_text(
                json.dumps({"pois": [{"description": "missing name"}]}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "第 1 个 POI"):
                splitter.load_pois_json(temp_dir)


class AiReviewTests(unittest.TestCase):
    def setUp(self):
        self.specs = [
            {"name": "Landmark A", "description": "Red tower"},
            {"name": "District B", "description": ""},
        ]

    def test_enforces_pass_threshold_and_issue_rule(self):
        raw = {
            "overall_summary": "test",
            "items": [
                {"index": 1, "poi": "Landmark A", "status": "PASS", "confidence": 0.95,
                 "issues": [], "reason": "clear"},
                {"index": 2, "poi": "District B", "status": "PASS", "confidence": 0.79,
                 "issues": [], "reason": "ambiguous"},
            ],
        }
        result = reviewer.normalize_ai_result(raw, 1, "/tmp/batch1.png", self.specs)
        self.assertEqual(result["items"][0]["status"], "PASS")
        self.assertEqual(result["items"][1]["status"], "REVIEW")
        self.assertEqual(result["status"], "NEEDS_REVIEW")

    def test_codex_runner_writes_structured_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir, "batch1.png")
            Image.new("RGB", (400, 400), "white").save(source)
            captured = {}

            def fake_runner(cmd, **kwargs):
                captured["cmd"] = cmd
                result_path = cmd[cmd.index("--output-last-message") + 1]
                Path(result_path).write_text(json.dumps({
                    "overall_summary": "one uncertain",
                    "items": [
                        {"index": 1, "poi": "Landmark A", "status": "PASS", "confidence": 0.9,
                         "issues": [], "reason": "match"},
                        {"index": 2, "poi": "District B", "status": "REVIEW", "confidence": 0.6,
                         "issues": ["ambiguous"], "reason": "generic area"},
                    ],
                }), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch.object(reviewer, "find_codex_executable", return_value="/fake/codex"):
                result = reviewer.review_batch_with_codex(
                    str(source), "Test City", 1, self.specs, runner=fake_runner, log=lambda _: None
                )
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(len(result["items"]), 2)
        self.assertNotIn("--ask-for-approval", captured["cmd"])
        self.assertIn("--sandbox", captured["cmd"])
        self.assertIn("read-only", captured["cmd"])

    def test_codex_failure_marks_every_item_for_review(self):
        def failed_runner(cmd, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="not logged in")

        with mock.patch.object(reviewer, "find_codex_executable", return_value="/fake/codex"):
            result = reviewer.review_batch_with_codex(
                "/tmp/missing.png", "Test City", 1, self.specs,
                runner=failed_runner, log=lambda _: None,
            )
        self.assertEqual(result["status"], "REVIEW_ERROR")
        self.assertTrue(all(x["status"] == "REVIEW_ERROR" for x in result["items"]))

    def test_partial_page_creates_only_actual_candidate_cells(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir, "batch1.png")
            Image.new("RGB", (400, 400), "white").save(source)
            batch = reviewer._error_batch(1, str(source), self.specs, "test")
            candidates = Path(temp_dir, "candidates")
            reviewer.create_candidate_crops(batch, str(candidates))
            files = list(candidates.glob("*.png"))
            self.assertEqual(len(files), 2)
            with Image.open(files[0]) as candidate:
                self.assertEqual(candidate.size, (100, 100))


class ManualReviewTests(unittest.TestCase):
    def test_decision_is_saved_and_mirrored_to_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manual_path = str(Path(temp_dir, "manual_review.json"))
            manifest_path = str(Path(temp_dir, "manifest.json"))
            ai_report = {
                "destination": "Test City",
                "batches": [{"batch": 1, "items": [{
                    "index": 1, "poi": "A", "status": "REVIEW", "confidence": 0.6,
                    "issues": ["ambiguous"], "description": "", "reason": "unclear",
                }]}],
            }
            manual = reviewer.ensure_manual_review(ai_report, manual_path)
            Path(manifest_path).write_text(json.dumps({
                "review": {"items": {"1:1": {"manual_decision": None}}}
            }), encoding="utf-8")
            job = {"manual": manual, "manual_path": manual_path, "manifest_path": manifest_path}
            reviewer.save_manual_decision(job, "1:1", "redo", "regenerate this icon")
            saved = json.loads(Path(manual_path).read_text(encoding="utf-8"))
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(saved["items"][0]["decision"], "redo")
        self.assertTrue(saved["completed"])
        self.assertEqual(manifest["review"]["items"]["1:1"]["manual_decision"], "redo")

    def test_full_manual_review_includes_ai_pass_and_not_run_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_a = str(Path(temp_dir, "A.png"))
            output_b = str(Path(temp_dir, "B.png"))
            manifest_path = str(Path(temp_dir, "manifest.json"))
            Path(manifest_path).write_text(json.dumps({
                "destination": "Test City",
                "batches": [{"index": 1, "pois": ["A", "B"]}],
                "mapping": {"A": output_a, "B": output_b},
                "review": {
                    "enabled": True,
                    "items": {
                        "1:1": {"batch": 1, "index": 1, "poi": "A", "ai_status": "PASS",
                                "confidence": 0.9, "issues": [], "manual_decision": None}
                    },
                },
            }), encoding="utf-8")
            manual, manual_path = reviewer.ensure_full_manual_review(manifest_path)
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(len(manual["items"]), 2)
        self.assertEqual(manual["items"][0]["ai_status"], "PASS")
        self.assertEqual(manual["items"][1]["ai_status"], "NOT_RUN")
        self.assertEqual(manifest["review"]["manual_summary"]["pending"], 2)
        self.assertTrue(manual_path.endswith("review/manual_review.json"))


class IntegrationTests(unittest.TestCase):
    def test_double_click_launchers_enable_interactive_review_choice(self):
        self.assertIn("--interactive-review", (ROOT / "run.command").read_text(encoding="utf-8"))
        self.assertIn("--interactive-review", (ROOT / "run.bat").read_text(encoding="utf-8"))

    def test_review_disabled_keeps_ai_off_and_writes_normal_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir, "inputs", "TestCity")
            output_dir = Path(temp_dir, "outputs")
            input_dir.mkdir(parents=True)
            Image.new("RGB", (400, 400), "white").save(input_dir / "batch1.png")
            (input_dir / "pois.json").write_text(
                json.dumps({"pois": ["Landmark A"]}), encoding="utf-8"
            )

            def fake_split(source, pois, out_dir):
                os.makedirs(out_dir, exist_ok=True)
                output = Path(out_dir, "Landmark_A.png")
                Image.new("RGBA", (100, 100), (255, 0, 0, 255)).save(output)
                return True, "", {"Landmark A": str(output.resolve())}

            with mock.patch.object(splitter, "split_one_grid", side_effect=fake_split):
                result = splitter.process_destination(
                    "TestCity", str(input_dir), str(output_dir), review_enabled=False
                )

            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertTrue(result["success"])
        self.assertIsNone(result["review_job"])
        self.assertEqual(manifest["review"], {"enabled": False})

    def test_review_enabled_writes_ai_report_candidates_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir, "inputs", "TestCity")
            output_dir = Path(temp_dir, "outputs")
            input_dir.mkdir(parents=True)
            Image.new("RGB", (400, 400), "white").save(input_dir / "batch1.png")
            (input_dir / "pois.json").write_text(
                json.dumps({"pois": [{"name": "District A", "description": "Colorful street"}]}),
                encoding="utf-8",
            )

            def fake_split(source, pois, out_dir):
                os.makedirs(out_dir, exist_ok=True)
                output = Path(out_dir, "District_A.png")
                Image.new("RGBA", (100, 100), (255, 0, 0, 255)).save(output)
                return True, "", {"District A": str(output.resolve())}

            fake_review = {
                "batch": 1,
                "source": str((input_dir / "batch1.png").resolve()),
                "status": "NEEDS_REVIEW",
                "summary": "ambiguous",
                "items": [{
                    "index": 1, "row": 1, "column": 1, "poi": "District A",
                    "description": "Colorful street", "status": "REVIEW", "confidence": 0.65,
                    "issues": ["ambiguous"], "reason": "not uniquely identifiable",
                }],
            }
            with mock.patch.object(splitter, "split_one_grid", side_effect=fake_split), \
                 mock.patch.object(reviewer, "review_batch_with_codex", return_value=fake_review):
                result = splitter.process_destination(
                    "TestCity", str(input_dir), str(output_dir), review_enabled=True
                )

            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            ai_path = Path(output_dir, "TestCity", "review", "ai_review.json")
            candidates = list(Path(output_dir, "TestCity", "review", "candidates").glob("*.png"))
            ai_exists = ai_path.exists()
        self.assertTrue(ai_exists)
        self.assertTrue(manifest["review"]["enabled"])
        self.assertEqual(manifest["review"]["summary"]["needs_review"], 1)
        self.assertEqual(len(candidates), 1)


if __name__ == "__main__":
    unittest.main()
