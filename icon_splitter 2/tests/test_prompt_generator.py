import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prompt_generator


class PromptGeneratorTests(unittest.TestCase):
    def test_seventeen_pois_create_two_prompt_pages(self):
        specs = [
            {"name": f"POI {index}", "name_zh": f"景点 {index}", "description": ""}
            for index in range(1, 18)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            project = prompt_generator.write_city_project(Path(temp_dir), "Test City", specs)
            first = Path(project["pages"][0]["prompt"]).read_text(encoding="utf-8")
            second = Path(project["pages"][1]["prompt"]).read_text(encoding="utf-8")
        self.assertEqual(project["page_count"], 2)
        self.assertEqual(project["pages"][1]["poi_count"], 1)
        self.assertEqual(project["pages"][0]["poi_specs"][0]["name_zh"], "景点 1")
        self.assertIn("**POI 16**", first)
        self.assertIn("**POI 17**", second)
        self.assertNotIn("empty slot", second)

    def test_supplied_visual_description_is_used_verbatim(self):
        prompt = prompt_generator.generate_page_prompt(
            "Seoul", [{"name": "Namsan Tower", "description": "White observation tower on a green hill"}], 1
        )
        self.assertIn("White observation tower on a green hill", prompt)
        self.assertIn("ABSOLUTELY NO TEXT", prompt)


if __name__ == "__main__":
    unittest.main()
