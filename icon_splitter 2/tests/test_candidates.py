import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import candidate_manager
import prompt_generator


def png_bytes(color="white"):
    buffer = io.BytesIO()
    Image.new("RGB", (400, 400), color).save(buffer, "PNG")
    return buffer.getvalue()


def upload(name, color="white"):
    return SimpleNamespace(filename=name, file=io.BytesIO(png_bytes(color)))


class CandidateManagerTests(unittest.TestCase):
    def create_project(self, root, count=2):
        input_dir = Path(root, "inputs", "Seoul")
        output_dir = Path(root, "outputs", "Seoul")
        input_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        specs = [
            {"name": f"POI {index}", "name_zh": f"景点{index}", "description": ""}
            for index in range(1, count + 1)
        ]
        project = prompt_generator.write_city_project(input_dir, "Seoul / 首尔", specs)
        return input_dir, output_dir, project

    def test_page_accepts_ten_groups_and_rejects_eleventh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir, _, project = self.create_project(temp_dir)
            saved = candidate_manager.add_uploads(
                input_dir, project, 1, [upload(f"candidate_{i}.png") for i in range(10)]
            )
            self.assertEqual(len(saved), 10)
            with self.assertRaisesRegex(ValueError, "最多10组"):
                candidate_manager.add_uploads(input_dir, project, 1, [upload("eleven.png")])

    def test_legacy_batch_is_registered_without_moving_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir, _, project = self.create_project(temp_dir)
            legacy = input_dir / "batch1.png"
            legacy.write_bytes(png_bytes())
            index = candidate_manager.ensure_source_index(input_dir, project)
            group = index["pages"]["1"][0]
            self.assertEqual(group["group"], 1)
            self.assertTrue(group["legacy"])
            self.assertTrue(legacy.is_file())

    def test_process_select_delete_and_export_bilingual_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir, output_dir, project = self.create_project(temp_dir)
            candidate_manager.add_uploads(input_dir, project, 1, [upload("one.png", "red")])

            def fake_split(source, labels, out_dir, **kwargs):
                target = Path(out_dir)
                target.mkdir(parents=True, exist_ok=True)
                mapping = {}
                for index, label in enumerate(labels, 1):
                    path = target / f"{label}.png"
                    Image.new("RGBA", (220, 160), (index * 40, 20, 30, 255)).save(path)
                    mapping[label] = str(path.resolve())
                return True, "", mapping

            with mock.patch.object(candidate_manager.splitter, "split_one_grid", side_effect=fake_split):
                result = candidate_manager.process_pending_groups(
                    "Seoul", input_dir, output_dir, project, ai_review=False, log=lambda _: None
                )
            self.assertEqual(result["processed"], 1)
            data = candidate_manager.build_candidate_data("Seoul", input_dir, output_dir, project)
            self.assertEqual(len(data["records"][0]["candidates"]), 1)
            self.assertFalse(data["ready_to_export"])

            candidate_id = data["records"][0]["candidates"][0]["candidate_id"]
            for record in data["records"]:
                candidate_manager.select_candidate(
                    output_dir, "Seoul", record["key"], candidate_id, "chosen"
                )
            selected = candidate_manager.build_candidate_data("Seoul", input_dir, output_dir, project)
            self.assertTrue(selected["ready_to_export"])
            exported = candidate_manager.export_final(
                "Seoul", input_dir, output_dir, project
            )
            self.assertEqual(exported["count"], 2)
            final_files = sorted(path.name for path in (output_dir / "final").glob("*.png"))
            self.assertEqual(final_files, [
                "Seoul_首尔_POI_1_景点1.png",
                "Seoul_首尔_POI_2_景点2.png",
            ])
            with Image.open(output_dir / "final" / final_files[0]) as image:
                self.assertLessEqual(max(image.size), 100)

            toggled_off = candidate_manager.select_candidate(
                output_dir, "Seoul", selected["records"][0]["key"], candidate_id, "chosen"
            )
            self.assertFalse(toggled_off["selected"])
            after_toggle = candidate_manager.build_candidate_data(
                "Seoul", input_dir, output_dir, project
            )
            self.assertEqual(after_toggle["records"][0]["decision"], "pending")
            candidate_manager.select_candidate(
                output_dir, "Seoul", selected["records"][0]["key"], candidate_id, "chosen"
            )

            deleted = candidate_manager.delete_group(
                input_dir, output_dir, project, "Seoul", candidate_id
            )
            self.assertEqual(len(deleted["cleared_selections"]), 2)
            after_delete = candidate_manager.build_candidate_data(
                "Seoul", input_dir, output_dir, project
            )
            self.assertEqual(after_delete["summary"]["accepted"], 0)

    def test_partial_selection_blocks_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir, output_dir, project = self.create_project(temp_dir)
            with self.assertRaisesRegex(ValueError, "2 个POI未选定"):
                candidate_manager.export_final("Seoul", input_dir, output_dir, project)

    def test_export_selected_candidates_keeps_state_and_writes_single_export_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir, output_dir, project = self.create_project(temp_dir, count=1)
            candidate_manager.add_uploads(input_dir, project, 1, [
                upload("one.png", "red"),
                upload("two.png", "blue"),
            ])

            def fake_split(source, labels, out_dir, **kwargs):
                target = Path(out_dir)
                target.mkdir(parents=True, exist_ok=True)
                color = (255, 0, 0, 255) if "group_01" in str(target) else (0, 0, 255, 255)
                path = target / "cell_01.png"
                Image.new("RGBA", (220, 180), color).save(path)
                return True, "", {"cell_01": str(path.resolve())}

            with mock.patch.object(candidate_manager.splitter, "split_one_grid", side_effect=fake_split):
                candidate_manager.process_pending_groups(
                    "Seoul", input_dir, output_dir, project, ai_review=False, log=lambda _: None
                )
            data = candidate_manager.build_candidate_data("Seoul", input_dir, output_dir, project)
            first, second = data["records"][0]["candidates"]
            candidate_manager.select_candidate(
                output_dir, "Seoul", "1:1", first["candidate_id"], "still selected"
            )
            manifest_before = candidate_manager.candidate_manifest_path(output_dir).read_bytes()
            selections_before = candidate_manager.selections_path(output_dir).read_bytes()

            custom_dir = Path(temp_dir, "custom_single_exports")
            exported = candidate_manager.export_selected_candidates(
                "Seoul", input_dir, output_dir, project, "1:1", [second["candidate_id"]], str(custom_dir)
            )

            self.assertEqual(exported["count"], 1)
            self.assertTrue(Path(exported["export_dir"]).is_dir())
            self.assertEqual(Path(exported["export_dir"]).parent.resolve(), custom_dir.resolve())
            self.assertTrue(Path(exported["items"][0]["file"]).is_file())
            self.assertIn("group_02", Path(exported["items"][0]["file"]).name)
            with Image.open(exported["items"][0]["file"]) as image:
                self.assertLessEqual(max(image.size), 100)
            self.assertEqual(candidate_manager.candidate_manifest_path(output_dir).read_bytes(), manifest_before)
            self.assertEqual(candidate_manager.selections_path(output_dir).read_bytes(), selections_before)

    def test_incremental_processing_skips_processed_groups_and_appends_new_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir, output_dir, project = self.create_project(temp_dir, count=1)
            candidate_manager.add_uploads(input_dir, project, 1, [upload("first.png", "red")])
            split_calls = []

            def fake_split(source, labels, out_dir, **kwargs):
                split_calls.append(Path(source).name)
                target = Path(out_dir)
                target.mkdir(parents=True, exist_ok=True)
                color = (255, 0, 0, 255) if "group_01" in str(target) else (0, 0, 255, 255)
                path = target / "cell_01.png"
                Image.new("RGBA", (120, 120), color).save(path)
                return True, "", {"cell_01": str(path.resolve())}

            with mock.patch.object(candidate_manager.splitter, "split_one_grid", side_effect=fake_split):
                first_result = candidate_manager.process_pending_groups(
                    "Seoul", input_dir, output_dir, project, ai_review=False, log=lambda _: None
                )
            self.assertEqual(first_result["processed"], 1)
            self.assertEqual(first_result["skipped"], 0)

            first_data = candidate_manager.build_candidate_data("Seoul", input_dir, output_dir, project)
            first_candidate = first_data["records"][0]["candidates"][0]
            candidate_manager.select_candidate(
                output_dir, "Seoul", "1:1", first_candidate["candidate_id"], "keep selected"
            )

            candidate_manager.add_uploads(input_dir, project, 1, [upload("second.png", "blue")])
            with mock.patch.object(candidate_manager.splitter, "split_one_grid", side_effect=fake_split):
                second_result = candidate_manager.process_pending_groups(
                    "Seoul", input_dir, output_dir, project, ai_review=False, log=lambda _: None
                )

            self.assertEqual(second_result["processed"], 1)
            self.assertEqual(second_result["skipped"], 1)
            self.assertEqual(split_calls, ["group_01.png", "group_02.png"])

            after = candidate_manager.build_candidate_data("Seoul", input_dir, output_dir, project)
            record = after["records"][0]
            self.assertEqual(len(record["candidates"]), 2)
            self.assertEqual([item["candidate_id"] for item in record["candidates"]], ["p01_g01", "p01_g02"])
            self.assertEqual(record["selected_candidate"], "p01_g01")
            self.assertEqual(record["decision"], "accepted")

    def test_delete_single_candidate_keeps_other_groups_and_clears_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir, output_dir, project = self.create_project(temp_dir, count=1)
            candidate_manager.add_uploads(input_dir, project, 1, [
                upload("one.png", "red"),
                upload("two.png", "blue"),
            ])

            def fake_split(source, labels, out_dir, **kwargs):
                target = Path(out_dir)
                target.mkdir(parents=True, exist_ok=True)
                color = (255, 0, 0, 255) if "group_01" in str(target) else (0, 0, 255, 255)
                path = target / "cell_01.png"
                Image.new("RGBA", (120, 120), color).save(path)
                return True, "", {"cell_01": str(path.resolve())}

            with mock.patch.object(candidate_manager.splitter, "split_one_grid", side_effect=fake_split):
                candidate_manager.process_pending_groups(
                    "Seoul", input_dir, output_dir, project, ai_review=False, log=lambda _: None
                )
            data = candidate_manager.build_candidate_data("Seoul", input_dir, output_dir, project)
            first, second = data["records"][0]["candidates"]
            first_path = Path(first["output"])
            self.assertTrue(first_path.is_file())
            candidate_manager.select_candidate(
                output_dir, "Seoul", "1:1", first["candidate_id"], "remove this one"
            )

            deleted = candidate_manager.delete_candidates(
                output_dir, "Seoul", "1:1", [first["candidate_id"]]
            )
            self.assertEqual(deleted["deleted_count"], 1)
            self.assertEqual(deleted["cleared_selections"], ["1:1"])
            self.assertFalse(first_path.exists())

            after = candidate_manager.build_candidate_data("Seoul", input_dir, output_dir, project)
            self.assertEqual(after["records"][0]["decision"], "pending")
            self.assertEqual(len(after["records"][0]["candidates"]), 1)
            self.assertEqual(after["records"][0]["candidates"][0]["candidate_id"], second["candidate_id"])


if __name__ == "__main__":
    unittest.main()
