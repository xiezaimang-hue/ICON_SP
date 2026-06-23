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
            no_base_first = Path(project["pages"][0]["prompt_no_base"]).read_text(encoding="utf-8")
            no_base_second = Path(project["pages"][1]["prompt_no_base"]).read_text(encoding="utf-8")
            self.assertTrue(Path(temp_dir, "prompts", "Prompt_无底座", "page_01.txt").is_file())
        self.assertEqual(project["page_count"], 2)
        self.assertEqual(project["version"], 2)
        self.assertEqual(project["pages"][1]["poi_count"], 1)
        self.assertEqual(project["pages"][0]["poi_specs"][0]["name_zh"], "景点 1")
        self.assertIn("**POI 16**", first)
        self.assertIn("**POI 17**", second)
        self.assertNotIn("empty slot", second)
        self.assertIn("**POI 16**", no_base_first)
        self.assertIn("**POI 17**", no_base_second)
        self.assertNotIn("miniature", no_base_first.casefold())
        self.assertNotIn("Objects sit DIRECTLY on the white floor", no_base_first)
        self.assertNotIn("studio product photography", no_base_first.casefold())
        self.assertNotIn("--no", no_base_first)
        self.assertIn("no shared floor patch", no_base_first)

    def test_base_free_prompt_uses_category_specific_constraints(self):
        prompt = prompt_generator.generate_base_free_prompt("Bali", [
            {"name": "Kuta Beach", "description": "Colorful surf beach"},
            {"name": "Mount Batur", "description": "Volcanic mountain"},
            {"name": "Uluwatu Temple", "description": "Balinese cliff temple"},
            {"name": "Bali Swing", "description": "Wooden tropical swing"},
        ], 1)
        self.assertIn("zero visible thickness", prompt)
        self.assertIn("cutaway soil", prompt)
        self.assertIn("architectural footprint", prompt)
        self.assertIn("all objects stand independently", prompt)

    def test_old_project_adds_no_base_variant_without_rewriting_original(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            city_dir = Path(temp_dir)
            prompts = city_dir / "prompts"
            prompts.mkdir()
            original = prompts / "page_01.txt"
            original.write_text("DO NOT REWRITE THIS ORIGINAL", encoding="utf-8")
            project = {
                "version": 1,
                "city": "Test City",
                "total_pois": 1,
                "page_count": 1,
                "pages": [{
                    "page": 1,
                    "prompt": str(original),
                    "poi_specs": [{"name": "City Tower", "name_zh": "城市塔", "description": ""}],
                }],
            }
            (city_dir / "project.json").write_text(json.dumps(project), encoding="utf-8")
            upgraded = prompt_generator.load_city_project(city_dir)
            no_base = Path(upgraded["pages"][0]["prompt_no_base"])
            self.assertEqual(original.read_text(encoding="utf-8"), "DO NOT REWRITE THIS ORIGINAL")
            self.assertTrue(no_base.is_file())
            self.assertEqual(upgraded["version"], 2)

    def test_supplied_visual_description_is_used_verbatim(self):
        prompt = prompt_generator.generate_page_prompt(
            "Seoul", [{"name": "Namsan Tower", "description": "White observation tower on a green hill"}], 1
        )
        self.assertIn("White observation tower on a green hill", prompt)
        self.assertIn("ABSOLUTELY NO TEXT", prompt)


if __name__ == "__main__":
    unittest.main()
