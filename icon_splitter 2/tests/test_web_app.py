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
            "destination": "Seoul", "key": "1:1", "decision": "accepted", "note": "looks right",
        })
        destination = self.request("/api/destination?name=Seoul")
        self.assertEqual(destination["records"][0]["decision"], "accepted")
        image_bytes = self.request("/asset?path=" + urllib.parse.quote(str(icon)))
        self.assertTrue(image_bytes.startswith(b"\x89PNG"))
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/asset?path=" + urllib.parse.quote("/etc/hosts"))

    def test_home_page_contains_full_workflow(self):
        html = self.request("/").decode("utf-8")
        self.assertIn("AI 整图初审", html)
        self.assertIn("人工评估", html)
        self.assertIn("切图当前城市", html)
        self.assertIn("导入整张表", html)
        self.assertIn("复制 PAGE", html)

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
        self.assertEqual(pois["pois"], ["Namsan Tower"])

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
        self.assertEqual(seoul["project"]["pages"][0]["poi_specs"][0]["name_zh"], "景点 1")

        image_buffer = io.BytesIO()
        Image.new("RGB", (400, 400), "white").save(image_buffer, "PNG")
        self.multipart(
            "/api/upload-images", {"city": "Seoul"},
            [("images", "page1.png", "image/png", image_buffer.getvalue())],
        )
        halfway = self.request("/api/destination?name=Seoul")
        self.assertFalse(halfway["project"]["ready_to_split"])
        self.multipart(
            "/api/upload-images", {"city": "Seoul"},
            [("images", "page2.png", "image/png", image_buffer.getvalue())],
        )
        ready = self.request("/api/destination?name=Seoul")
        self.assertTrue(ready["project"]["ready_to_split"])


if __name__ == "__main__":
    unittest.main()
