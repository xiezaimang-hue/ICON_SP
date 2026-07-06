import json
import io
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import web_app


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config_dir = self.root / "config"
        patches = [
            mock.patch.object(web_app.StudioState, "_initial_workspace", return_value=self.root),
            mock.patch.object(web_app, "CONFIG_DIR", config_dir),
            mock.patch.object(web_app, "CONFIG_PATH", config_dir / "config.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.state = web_app.StudioState()
        self.server = web_app.create_server(self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, data=None):
        payload = None if data is None else json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read()
        return json.loads(body) if "application/json" in content_type else body

    def test_real_image_search_endpoint_parses_bing_image_urls(self):
        class FakeResponse:
            def read(self, *_):
                return (
                    b'{"murl":"https:\\/\\/example.com\\/one.jpg"}'
                    b'{"murl":"https:\\/\\/example.com\\/two.png"}'
                )

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch.object(web_app.urllib.request, "urlopen", return_value=FakeResponse()):
            result = web_app.search_real_images("Bangkok Temple", 8)
        self.assertEqual(result["images"], [
            "https://example.com/one.jpg",
            "https://example.com/two.png",
        ])
        self.assertEqual(result["error"], "")

    def multipart(self, path, fields, files):
        boundary = "----PoiIconStudioGenericBoundary"
        parts = []
        for name, value in fields.items():
            parts.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(), b"\r\n",
            ])
        for name, filename, content_type, content in files:
            parts.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(), content, b"\r\n",
            ])
        parts.append(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            self.base + path,
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    def create_city_with_output(self):
        input_dir = self.root / "inputs" / "Seoul"
        output_dir = self.root / "outputs" / "Seoul"
        cropped = output_dir / "cropped"
        input_dir.mkdir(parents=True)
        cropped.mkdir(parents=True)
        Image.new("RGB", (400, 400), "white").save(input_dir / "batch1.png")
        (input_dir / "pois.json").write_text(
            json.dumps({"pois": [{
                "name": "Namsan Tower",
                "name_zh": "南山首尔塔",
                "description": "White observation tower",
            }]}),
            encoding="utf-8",
        )
        icon = cropped / "Namsan_Tower.png"
        Image.new("RGBA", (100, 80), (255, 0, 0, 255)).save(icon)
        (output_dir / "manifest.json").write_text(json.dumps({
            "destination": "Seoul",
            "total_pois": 1,
            "batches": [{"index": 1, "pois": ["Namsan Tower"]}],
            "mapping": {"Namsan Tower": str(icon)},
            "review": {"enabled": False},
        }), encoding="utf-8")
        return icon

    def test_state_and_destination_endpoints(self):
        self.create_city_with_output()
        state = self.request("/api/state")
        self.assertEqual(state["destinations"], ["Seoul"])
        destination = self.request("/api/destination?name=Seoul")
        self.assertEqual(destination["input"]["poi_count"], 1)
        self.assertEqual(destination["input"]["described_count"], 1)
        self.assertEqual(len(destination["records"]), 1)
        self.assertEqual(destination["records"][0]["poi_zh"], "南山首尔塔")

    def test_manual_decision_and_asset_are_local(self):
        icon = self.create_city_with_output()
        self.request("/api/destination?name=Seoul")
        self.request("/api/decision", {
            "destination": "Seoul", "key": "1:1", "decision": "redo", "note": "needs another option",
        })
        destination = self.request("/api/destination?name=Seoul")
        self.assertEqual(destination["records"][0]["decision"], "redo")
        image_bytes = self.request("/asset?path=" + urllib.parse.quote(str(icon)))
        self.assertTrue(image_bytes.startswith(b"\x89PNG"))
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/asset?path=" + urllib.parse.quote("/etc/hosts"))

    def test_candidate_selection_and_final_export_endpoints(self):
        icon = self.create_city_with_output()
        self.request("/api/destination?name=Seoul")
        output_dir = self.root / "outputs" / "Seoul"
        (output_dir / "candidate_manifest.json").write_text(json.dumps({
            "version": 1,
            "destination": "Seoul",
            "groups": {
                "p01_g01": {
                    "id": "p01_g01", "page": 1, "group": 1,
                    "source": str(self.root / "inputs" / "Seoul" / "batch1.png"),
                    "status": "processed", "items": [{
                        "key": "1:1", "index": 1, "poi": "Namsan Tower",
                        "poi_zh": "南山首尔塔", "output": str(icon),
                        "ai_status": "NOT_RUN", "confidence": None,
                        "issues": [], "reason": "",
                    }],
                }
            },
        }), encoding="utf-8")
        self.request("/api/select-candidate", {
            "destination": "Seoul", "key": "1:1",
            "candidate_id": "p01_g01", "note": "best option",
        })
        selected = self.request("/api/destination?name=Seoul")
        self.assertEqual(selected["records"][0]["decision"], "accepted")
        self.assertTrue(selected["project"]["ready_to_export"])
        exported = self.request("/api/export-final", {"destination": "Seoul"})
        self.assertEqual(exported["count"], 1)
        self.assertTrue((output_dir / "final" / "Seoul_Namsan_Tower_南山首尔塔.png").is_file())

        selections_path = output_dir / "selections.json"
        candidates_path = output_dir / "candidate_manifest.json"
        selections_before = selections_path.read_bytes()
        candidates_before = candidates_path.read_bytes()
        board = self.request("/api/export-review-board", {"destination": "Seoul"})
        self.assertEqual(board["width"], 1600)
        self.assertEqual(board["page_count"], 1)
        self.assertEqual(len(board["pages"]), 1)
        self.assertTrue(Path(board["dir"]).is_dir())
        self.assertEqual(Path(board["path"]).parent, Path(board["dir"]))
        self.assertEqual(board["poi_count"], 1)
        board_bytes = self.request("/asset?path=" + urllib.parse.quote(board["path"]))
        self.assertTrue(board_bytes.startswith(b"\x89PNG"))
        self.assertEqual(selections_path.read_bytes(), selections_before)
        self.assertEqual(candidates_path.read_bytes(), candidates_before)
        picked_dir = output_dir / "picked_from_dialog"
        fake_dialog = mock.Mock(returncode=0, stdout=str(picked_dir) + "\n", stderr="")
        with mock.patch.object(web_app.sys, "platform", "darwin"), \
                mock.patch.object(web_app.subprocess, "run", return_value=fake_dialog) as run_dialog:
            picked = self.request("/api/choose-folder", {"default_dir": str(output_dir / "single_exports")})
        self.assertFalse(picked["canceled"])
        self.assertEqual(Path(picked["path"]), picked_dir.resolve())
        self.assertIn("choose folder", run_dialog.call_args.args[0][2])
        single = self.request("/api/export-selected-candidates", {
            "destination": "Seoul", "key": "1:1", "candidate_ids": ["p01_g01"],
            "export_dir": picked["path"],
        })
        self.assertEqual(single["count"], 1)
        self.assertEqual(Path(single["export_dir"]).parent.resolve(), picked_dir.resolve())
        self.assertTrue(Path(single["export_dir"]).is_dir())
        self.assertTrue(Path(single["items"][0]["file"]).is_file())
        self.assertEqual(selections_path.read_bytes(), selections_before)
        self.assertEqual(candidates_path.read_bytes(), candidates_before)

        toggled = self.request("/api/select-candidate", {
            "destination": "Seoul", "key": "1:1", "candidate_id": "p01_g01", "note": "",
        })
        self.assertFalse(toggled["selected"])
        unselected = self.request("/api/destination?name=Seoul")
        self.assertEqual(unselected["records"][0]["decision"], "pending")

        self.request("/api/select-candidate", {
            "destination": "Seoul", "key": "1:1", "candidate_id": "p01_g01", "note": "delete it",
        })
        deleted = self.request("/api/delete-candidates", {
            "destination": "Seoul", "key": "1:1", "candidate_ids": ["p01_g01"],
        })
        self.assertEqual(deleted["deleted_count"], 1)
        self.assertEqual(deleted["cleared_selections"], ["1:1"])
        self.assertFalse(icon.exists())
        after_delete = self.request("/api/destination?name=Seoul")
        self.assertEqual(after_delete["records"][0]["decision"], "pending")
        self.assertEqual(after_delete["records"][0]["candidates"], [])

    def test_home_page_contains_full_workflow(self):
        html = self.request("/").decode("utf-8")
        self.assertIn("AI 整图初审", html)
        self.assertIn("人工评估", html)
        self.assertIn("切图当前城市", html)
        self.assertIn("导入整张表", html)
        self.assertIn("复制 PAGE", html)
        self.assertIn("原版 Prompt", html)
        self.assertIn("Prompt_图标化", html)
        self.assertIn("Prompt_本体强化", html)
        self.assertNotIn("data-prompt-variant=\"no_base\"", html)
        self.assertIn("搜索真实图片", html)
        self.assertIn("真实图片参考", html)
        self.assertIn("/api/real-images", html)
        self.assertIn("loadRealImages", html)
        self.assertIn("bing.com/images/search", html)
        self.assertIn("图片不合格", html)
        self.assertIn("系统错误", html)
        self.assertIn("点击图片设为最终", html)
        self.assertIn("data-record-key", html)
        self.assertIn("#18864b", html)
        self.assertIn("max-width:450px", html)
        self.assertIn("导出审核总览图", html)
        self.assertIn("page_count", html)
        self.assertIn("候选大图预览", html)
        self.assertIn("data-source-preview-id", html)
        self.assertIn("openSourcePreview", html)
        self.assertIn("source-preview-prev", html)
        self.assertIn("source-preview-next", html)
        self.assertIn("source-preview-title", html)
        self.assertIn("候选大图预览 · ${item.title}", html)
        self.assertIn("delete-source-preview", html)
        self.assertIn("moveSourcePreview", html)
        self.assertIn("deleteSourcePreview", html)
        self.assertIn("删除模式", html)
        self.assertIn("确定删除", html)
        self.assertIn("/api/delete-candidates", html)
        self.assertIn("data-delete-candidate", html)
        self.assertIn("单独导出", html)
        self.assertIn("单独导出模式", html)
        self.assertIn("确定导出", html)
        self.assertIn("/api/choose-folder", html)
        self.assertIn("选择保存位置失败", html)
        self.assertIn("/api/export-selected-candidates", html)
        self.assertIn("data-export-candidate", html)
        self.assertIn("#review.active", html)
        self.assertIn("grid-template-rows:auto minmax(0,1fr)", html)
        self.assertIn(".table-wrap{overflow:auto;min-height:0", html)
        self.assertIn(".detail{padding:20px;overflow:auto;min-height:0", html)

    def test_multipart_import_creates_city_inputs(self):
        image_buffer = io.BytesIO()
        Image.new("RGB", (400, 400), "white").save(image_buffer, "PNG")
        boundary = "----PoiIconStudioTestBoundary"
        parts = []

        def field(name, value):
            parts.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(), b"\r\n",
            ])

        def upload(name, filename, content_type, content):
            parts.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(), content, b"\r\n",
            ])

        field("city", "Seoul")
        upload("table", "pois.csv", "text/csv", "目的地,编号,地标\nSeoul,1,Namsan Tower\n".encode())
        upload("images", "page1.png", "image/png", image_buffer.getvalue())
        parts.append(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            self.base + "/api/import",
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.loads(response.read())
        self.assertEqual(result["poi_count"], 1)
        self.assertTrue((self.root / "inputs" / "Seoul" / "batch1.png").is_file())
        pois = json.loads((self.root / "inputs" / "Seoul" / "pois.json").read_text(encoding="utf-8"))
        self.assertEqual(pois["pois"][0]["name"], "Namsan Tower")
        self.assertEqual(pois["pois"][0]["prompt_name"], "Namsan Tower")

    def test_full_table_creates_city_prompts_then_images_fill_page_slots(self):
        rows = ["城市,编号,地标,中文,视觉描述"]
        rows.extend(f"Seoul,{index},POI {index},景点 {index},Feature {index}" for index in range(1, 18))
        rows.append("Tokyo,1,Tokyo Tower,东京塔,Red lattice tower")
        imported = self.multipart(
            "/api/import-table", {},
            [("table", "all.csv", "text/csv", ("\n".join(rows) + "\n").encode())],
        )
        self.assertEqual(imported["city_count"], 2)
        self.assertEqual(imported["total_pois"], 18)
        seoul = self.request("/api/destination?name=Seoul")
        self.assertEqual(seoul["project"]["page_count"], 2)
        self.assertFalse(seoul["project"]["ready_to_split"])
        self.assertIn("**POI 16**", seoul["project"]["pages"][0]["prompt_text"])
        self.assertIn("**POI 17**", seoul["project"]["pages"][1]["prompt_text"])
        self.assertIn("PROMPT VERSION: Prompt_图标化", seoul["project"]["pages"][0]["prompt_iconic_text"])
        self.assertIn("PROMPT VERSION: Prompt_本体强化", seoul["project"]["pages"][0]["prompt_identity_text"])
        self.assertNotIn("prompt_no_base_text", seoul["project"]["pages"][0])
        self.assertNotIn("no_base", seoul["project"]["pages"][0]["prompt_variants"])
        self.assertEqual(
            seoul["project"]["pages"][0]["prompt_variants"]["iconic"],
            seoul["project"]["pages"][0]["prompt_iconic_text"],
        )
        self.assertEqual(
            seoul["project"]["pages"][0]["prompt_variants"]["identity"],
            seoul["project"]["pages"][0]["prompt_identity_text"],
        )
        self.assertEqual(seoul["project"]["pages"][0]["poi_specs"][0]["name_zh"], "景点 1")

        image_buffer = io.BytesIO()
        Image.new("RGB", (400, 400), "white").save(image_buffer, "PNG")
        self.multipart(
            "/api/upload-images", {"city": "Seoul", "page": "1"},
            [("images", "page1.png", "image/png", image_buffer.getvalue())],
        )
        halfway = self.request("/api/destination?name=Seoul")
        self.assertTrue(halfway["project"]["ready_to_process"])
        self.assertEqual(len(halfway["project"]["pages"][0]["candidate_groups"]), 1)
        self.multipart(
            "/api/upload-images", {"city": "Seoul", "page": "2"},
            [("images", "page2.png", "image/png", image_buffer.getvalue())],
        )
        ready = self.request("/api/destination?name=Seoul")
        self.assertTrue(ready["project"]["ready_to_process"])
        self.assertEqual(ready["candidate"]["pending_groups"], 2)


if __name__ == "__main__":
    unittest.main()
