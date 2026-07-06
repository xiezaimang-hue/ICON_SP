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
            iconic_first = Path(project["pages"][0]["prompt_iconic"]).read_text(encoding="utf-8")
            iconic_second = Path(project["pages"][1]["prompt_iconic"]).read_text(encoding="utf-8")
            identity_first = Path(project["pages"][0]["prompt_identity"]).read_text(encoding="utf-8")
            identity_second = Path(project["pages"][1]["prompt_identity"]).read_text(encoding="utf-8")
            self.assertTrue(Path(temp_dir, "prompts", "Prompt_图标化", "page_01.txt").is_file())
            self.assertTrue(Path(temp_dir, "prompts", "Prompt_本体强化", "page_01.txt").is_file())
        self.assertEqual(project["page_count"], 2)
        self.assertEqual(project["version"], 5)
        self.assertEqual(project["pages"][1]["poi_count"], 1)
        self.assertEqual(project["pages"][0]["poi_specs"][0]["name_zh"], "景点 1")
        self.assertIn("**POI 16**", first)
        self.assertIn("**POI 17**", second)
        self.assertNotIn("empty slot", second)
        self.assertNotIn("prompt_no_base", project["pages"][0])
        self.assertIn("PROMPT VERSION: Prompt_图标化", iconic_first)
        self.assertIn("HIGH-QUALITY SIMPLIFIED ICONS", iconic_first)
        self.assertIn("2 to 4 oversized primitive volumes", iconic_first)
        self.assertIn("one dominant big silhouette", iconic_first)
        self.assertIn("50px mobile icon", iconic_first)
        self.assertIn("EXACTLY 1 distinct icon items", iconic_second)
        self.assertIn("PROMPT VERSION: Prompt_本体强化", identity_first)
        self.assertIn("LANDMARK-FAITHFUL SIMPLIFIED 3D ICONS", identity_first)
        self.assertIn("signature silhouette", identity_first)
        self.assertIn("faithful landmark colors", identity_first)
        self.assertIn("EXACTLY 1 distinct icon items", identity_second)

    def test_identity_prompt_uses_category_specific_constraints(self):
        prompt = prompt_generator.generate_identity_prompt("Bali", [
            {"name": "Kuta Beach", "description": "Colorful surf beach"},
            {"name": "Mount Batur", "description": "Volcanic mountain"},
            {"name": "Uluwatu Temple", "description": "Balinese cliff temple"},
            {"name": "Bali Swing", "description": "Wooden tropical swing"},
        ], 1)
        self.assertIn("real POI body's visual identity", prompt)
        self.assertIn("low-detail block modeling", prompt)
        self.assertIn("dominant color palette", prompt)
        self.assertIn("3 to 5 chunky matte-clay volumes", prompt)

    def test_old_project_refreshes_generated_prompts_and_adds_identity_variant(self):
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
            iconic = Path(upgraded["pages"][0]["prompt_iconic"])
            identity = Path(upgraded["pages"][0]["prompt_identity"])
            self.assertIn("POIS IN ORDER: City Tower", original.read_text(encoding="utf-8"))
            self.assertTrue(iconic.is_file())
            self.assertTrue(identity.is_file())
            self.assertNotIn("prompt_no_base", upgraded["pages"][0])
            self.assertEqual(upgraded["pages"][0]["poi_specs"][0]["prompt_name"], "City Tower")
            self.assertEqual(upgraded["version"], 5)

    def test_chinese_poi_gets_english_prompt_name(self):
        prompt = prompt_generator.generate_identity_prompt(
            "Bangkok / 曼谷", [{"name": "郑王庙", "description": ""}], 1
        )
        self.assertIn("POIS IN ORDER: Wat Arun", prompt)
        self.assertIn("**Wat Arun**", prompt)
        self.assertNotIn("**郑王庙**", prompt)

        with tempfile.TemporaryDirectory() as temp_dir:
            project = prompt_generator.write_city_project(
                Path(temp_dir), "Bangkok / 曼谷", [{"name": "郑王庙", "description": ""}]
            )
        spec = project["pages"][0]["poi_specs"][0]
        self.assertEqual(spec["name"], "郑王庙")
        self.assertEqual(spec["name_zh"], "郑王庙")
        self.assertEqual(spec["prompt_name"], "Wat Arun")

    def test_iconic_prompt_keeps_quality_but_reduces_detail(self):
        prompt = prompt_generator.generate_iconic_prompt(
            "Tokyo", [{"name": "Shibuya", "description": "busy crossing with tall buildings"}], 1
        )
        self.assertIn("Preserve image quality", prompt)
        self.assertIn("Avoid tiny windows, dense decorations", prompt)
        self.assertIn("toy-like chunky massing", prompt)
        self.assertIn("readable at 50px mobile icon size", prompt)
        self.assertIn("8k", prompt)

    def test_supplied_visual_description_is_used_verbatim(self):
        prompt = prompt_generator.generate_page_prompt(
            "Seoul", [{"name": "Namsan Tower", "description": "White observation tower on a green hill"}], 1
        )
        self.assertIn("White observation tower on a green hill", prompt)
        self.assertIn("ABSOLUTELY NO TEXT", prompt)

    def test_optional_source_id_is_preserved_in_project_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = prompt_generator.write_city_project(Path(temp_dir), "Activity Types", [
                {
                    "id": "5927",
                    "name": "Nearby Route",
                    "name_zh": "周边路线",
                    "description": "A short local travel route icon",
                }
            ])
        self.assertEqual(project["pages"][0]["poi_specs"][0]["id"], "5927")


if __name__ == "__main__":
    unittest.main()
