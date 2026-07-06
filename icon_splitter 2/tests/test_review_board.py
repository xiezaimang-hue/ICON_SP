import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import review_board


def make_record(index, candidate_count, image_path, decision="pending", broken_last=False):
    candidates = []
    for group in range(1, candidate_count + 1):
        candidates.append({
            "candidate_id": f"p01_g{group:02d}",
            "page": 1,
            "group": group,
            "output": "/missing/candidate.png" if broken_last and group == candidate_count else str(image_path),
            "ai_status": ["PASS", "REVIEW", "FAIL", "NOT_RUN"][group % 4],
        })
    return {
        "key": f"1:{index}",
        "batch": 1,
        "index": index,
        "poi": f"Very Long English POI Name {index}",
        "poi_zh": f"中文地标名称{index}",
        "candidates": candidates,
        "selected_candidate": candidates[-1]["candidate_id"] if decision == "accepted" and candidates else "",
        "decision": decision,
        "note": "这是一条用于跨职能审核的较长人工备注，会被限制为最多两行显示。" if index == 1 else "",
    }


class ReviewBoardTests(unittest.TestCase):
    def test_board_renders_all_candidates_statuses_and_broken_placeholder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            icon = root / "icon.png"
            Image.new("RGBA", (220, 180), (30, 190, 120, 255)).save(icon)
            records = [
                make_record(1, 1, icon, "accepted"),
                make_record(2, 4, icon, "pending"),
                make_record(3, 10, icon, "redo", broken_last=True),
                make_record(4, 0, icon, "pending"),
            ]
            data = {
                "records": records,
                "summary": {"total": 4, "accepted": 1, "pending": 2, "redo": 1},
            }
            output_dir = root / "outputs"
            with mock.patch.object(review_board.candidate_manager, "build_candidate_data", return_value=data):
                result = review_board.export_review_board(
                    "Bali", root / "inputs", output_dir,
                    {"city": "Bali / 巴厘岛"},
                )
            self.assertEqual(result["width"], 1600)
            self.assertEqual(result["page_count"], 1)
            self.assertEqual(len(result["pages"]), 1)
            self.assertTrue(Path(result["dir"]).is_dir())
            self.assertEqual(Path(result["path"]).parent, Path(result["dir"]))
            self.assertEqual(result["poi_count"], 4)
            self.assertEqual(result["candidate_count"], 15)
            self.assertEqual(result["broken_candidate_count"], 1)
            with Image.open(result["path"]) as board:
                self.assertEqual(board.width, 1600)
                self.assertGreater(board.height, 500)
                self.assertLessEqual(board.height, 2400)
                colors = board.convert("RGB").getcolors(board.width * board.height)
                color_map = {color: count for count, color in colors}
                self.assertGreater(color_map.get((24, 134, 75), 0), 50)
                self.assertGreater(color_map.get((179, 38, 30), 0), 20)

    def test_fifty_pois_are_split_into_editable_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            records = [make_record(index, 0, root / "none.png") for index in range(1, 51)]
            data = {
                "records": records,
                "summary": {"total": 50, "accepted": 0, "pending": 50, "redo": 0},
            }
            with mock.patch.object(review_board.candidate_manager, "build_candidate_data", return_value=data):
                result = review_board.export_review_board(
                    "Bangkok", root / "inputs", root / "outputs",
                    {"city": "Bangkok / 曼谷"},
                )
            self.assertEqual(result["width"], 1600)
            self.assertGreater(result["page_count"], 1)
            self.assertTrue(Path(result["path"]).is_file())
            self.assertEqual(len(result["pages"]), result["page_count"])
            for page in result["pages"]:
                self.assertTrue(Path(page["path"]).is_file())
                self.assertEqual(Path(page["path"]).parent, Path(result["dir"]))
                with Image.open(page["path"]) as image:
                    self.assertEqual(image.width, 1600)
                    self.assertLessEqual(image.height, 2400)


if __name__ == "__main__":
    unittest.main()
