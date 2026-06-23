#!/usr/bin/env python3
"""Optional AI review and local human-review UI for the icon splitter."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional


PASS_CONFIDENCE = 0.80
REVIEW_DECISIONS = ("accepted", "rejected", "redo", "pending")
ISSUE_CODES = (
    "poi_mismatch",
    "wrong_position",
    "duplicate",
    "missing",
    "text_or_logo",
    "base_or_platform",
    "shadow",
    "style_mismatch",
    "ambiguous",
    "other",
)


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _safe_name(value: str) -> str:
    return re.sub(r"[^\w\-]", "_", value.strip()).strip("_")[:60] or "poi"


def find_codex_executable() -> Optional[str]:
    """Find Codex CLI on PATH, with a macOS app-bundle fallback."""
    found = shutil.which("codex")
    if found:
        return found
    mac_app = "/Applications/Codex.app/Contents/Resources/codex"
    if os.path.isfile(mac_app) and os.access(mac_app, os.X_OK):
        return mac_app
    return None


def _output_schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "overall_summary": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "index": {"type": "integer", "minimum": 1, "maximum": 16},
                        "poi": {"type": "string"},
                        "status": {"type": "string", "enum": ["PASS", "REVIEW", "FAIL"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "issues": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(ISSUE_CODES)},
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["index", "poi", "status", "confidence", "issues", "reason"],
                },
            },
        },
        "required": ["overall_summary", "items"],
    }


def _review_prompt(destination: str, batch_index: int, poi_specs: List[dict]) -> str:
    expected = []
    for offset, spec in enumerate(poi_specs, 1):
        row = (offset - 1) // 4 + 1
        col = (offset - 1) % 4 + 1
        description = spec.get("description") or "(no visual description supplied)"
        expected.append(
            f"{offset}. row={row}, column={col}, POI={spec['name']!r}, expected={description!r}"
        )
    return f"""You are reviewing one generated 4x4 POI icon sprite sheet.
Destination: {destination}
Batch: {batch_index}

Inspect only the attached image. Evaluate each supplied POI in row-major order. Do not use tools,
edit files, or search the web. Check:
1. The depicted icon plausibly matches the named POI and optional visual description.
2. It is in the expected row and column; flag duplicates, missing icons, or obvious swaps.
3. It contains no readable text/logo, base/platform, or obvious cast shadow.
4. It broadly follows an isometric matte-clay icon style.

If a POI is a district, neighborhood, generic activity, or otherwise has no uniquely verifiable
appearance and no useful description, mark REVIEW with confidence below 0.80 instead of guessing.
PASS is allowed only when there are no issues and confidence is at least 0.80.
Return exactly one item for every listed POI. Do not return entries for unused grid cells.

Expected cells:
{chr(10).join(expected)}
"""


def _error_batch(batch_index: int, source_path: str, poi_specs: List[dict], error: str) -> dict:
    return {
        "batch": batch_index,
        "source": os.path.abspath(source_path),
        "status": "REVIEW_ERROR",
        "summary": error,
        "error": error,
        "items": [
            {
                "index": i,
                "row": (i - 1) // 4 + 1,
                "column": (i - 1) % 4 + 1,
                "poi": spec["name"],
                "description": spec.get("description", ""),
                "status": "REVIEW_ERROR",
                "confidence": 0.0,
                "issues": ["other"],
                "reason": error,
            }
            for i, spec in enumerate(poi_specs, 1)
        ],
    }


def normalize_ai_result(
    raw: dict,
    batch_index: int,
    source_path: str,
    poi_specs: List[dict],
) -> dict:
    """Validate model output and enforce the local PASS threshold."""
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ValueError("Codex returned an invalid review object")

    by_index = {}
    for item in raw["items"]:
        if isinstance(item, dict) and isinstance(item.get("index"), int):
            by_index[item["index"]] = item

    items = []
    for index, spec in enumerate(poi_specs, 1):
        model_item = by_index.get(index)
        if model_item is None:
            raise ValueError(f"Codex review is missing grid item {index}")
        confidence = float(model_item.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        issues = [x for x in model_item.get("issues", []) if x in ISSUE_CODES]
        status = str(model_item.get("status", "REVIEW")).upper()
        if status not in ("PASS", "REVIEW", "FAIL"):
            status = "REVIEW"
        if status == "PASS" and (confidence < PASS_CONFIDENCE or issues):
            status = "REVIEW"
        items.append({
            "index": index,
            "row": (index - 1) // 4 + 1,
            "column": (index - 1) % 4 + 1,
            "poi": spec["name"],
            "description": spec.get("description", ""),
            "status": status,
            "confidence": round(confidence, 3),
            "issues": issues,
            "reason": str(model_item.get("reason", "")).strip(),
        })

    status = "PASS" if all(x["status"] == "PASS" for x in items) else "NEEDS_REVIEW"
    return {
        "batch": batch_index,
        "source": os.path.abspath(source_path),
        "status": status,
        "summary": str(raw.get("overall_summary", "")).strip(),
        "items": items,
    }


def review_batch_with_codex(
    source_path: str,
    destination: str,
    batch_index: int,
    poi_specs: List[dict],
    *,
    runner: Callable = subprocess.run,
    timeout: int = 600,
    log: Callable[[str], None] = print,
) -> dict:
    """Review one source grid through the authenticated local Codex CLI."""
    codex = find_codex_executable()
    if not codex:
        return _error_batch(batch_index, source_path, poi_specs, "未找到 Codex CLI，请安装并登录 Codex")

    try:
        with tempfile.TemporaryDirectory(prefix="icon-review-") as temp_dir:
            schema_path = os.path.join(temp_dir, "schema.json")
            result_path = os.path.join(temp_dir, "result.json")
            _write_json(schema_path, _output_schema())
            cmd = [
                codex, "exec", "--ephemeral", "--ignore-rules", "--skip-git-repo-check",
                "--sandbox", "read-only",
                "--image", os.path.abspath(source_path),
                "--output-schema", schema_path,
                "--output-last-message", result_path,
                _review_prompt(destination, batch_index, poi_specs),
            ]
            log(f"  [AI审核] 调用 Codex 检查 batch{batch_index}...")
            completed = runner(
                cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "unknown error").strip()
                raise RuntimeError(f"Codex CLI 退出码 {completed.returncode}: {detail[-500:]}")
            if not os.path.isfile(result_path):
                raise RuntimeError("Codex CLI 未生成审核结果")
            with open(result_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        result = normalize_ai_result(raw, batch_index, source_path, poi_specs)
        flagged = sum(1 for x in result["items"] if x["status"] != "PASS")
        log(f"  [AI审核] batch{batch_index}: {result['status']}，异常/待确认 {flagged} 个")
        return result
    except Exception as exc:
        error = f"AI 审核失败: {exc}"
        log(f"  [AI审核] {error}")
        return _error_batch(batch_index, source_path, poi_specs, error)


def create_candidate_crops(batch_result: dict, candidates_dir: str) -> None:
    """Create fixed-cell high-resolution crops for non-PASS review items."""
    from PIL import Image

    flagged = [x for x in batch_result["items"] if x["status"] != "PASS"]
    if not flagged:
        return
    os.makedirs(candidates_dir, exist_ok=True)
    with Image.open(batch_result["source"]) as image:
        image = image.convert("RGB")
        width, height = image.size
        for item in flagged:
            index = item["index"]
            row = (index - 1) // 4
            col = (index - 1) % 4
            left = round(col * width / 4)
            right = round((col + 1) * width / 4)
            top = round(row * height / 4)
            bottom = round((row + 1) * height / 4)
            filename = f"batch{batch_result['batch']:02d}_cell{index:02d}_{_safe_name(item['poi'])}.png"
            path = os.path.join(candidates_dir, filename)
            image.crop((left, top, right, bottom)).save(path, "PNG")
            item["candidate"] = os.path.abspath(path)


def build_ai_review(destination: str, batch_results: List[dict], review_dir: str) -> dict:
    candidates_dir = os.path.join(review_dir, "candidates")
    for batch in batch_results:
        create_candidate_crops(batch, candidates_dir)
    items = [item for batch in batch_results for item in batch["items"]]
    report = {
        "version": 1,
        "destination": destination,
        "enabled": True,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "threshold": PASS_CONFIDENCE,
        "summary": {
            "total": len(items),
            "passed": sum(1 for x in items if x["status"] == "PASS"),
            "needs_review": sum(1 for x in items if x["status"] != "PASS"),
        },
        "batches": batch_results,
    }
    _write_json(os.path.join(review_dir, "ai_review.json"), report)
    return report


def ensure_manual_review(ai_report: dict, manual_path: str) -> dict:
    existing = {}
    if os.path.isfile(manual_path):
        try:
            with open(manual_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            existing = {x["key"]: x for x in old.get("items", []) if isinstance(x, dict) and "key" in x}
        except Exception:
            existing = {}

    items = []
    for batch in ai_report["batches"]:
        for item in batch["items"]:
            if item["status"] == "PASS":
                continue
            key = f"{batch['batch']}:{item['index']}"
            previous = existing.get(key, {})
            if previous.get("poi") != item["poi"]:
                previous = {}
            items.append({
                "key": key,
                "batch": batch["batch"],
                "index": item["index"],
                "poi": item["poi"],
                "decision": previous.get("decision", "pending"),
                "note": previous.get("note", ""),
                "updated_at": previous.get("updated_at", ""),
            })
    manual = {
        "version": 1,
        "destination": ai_report["destination"],
        "completed": bool(items) and all(x["decision"] != "pending" for x in items),
        "items": items,
    }
    _write_json(manual_path, manual)
    return manual


def review_manifest_payload(ai_report: dict, ai_path: str, manual_path: str) -> dict:
    items = {}
    for batch in ai_report["batches"]:
        for item in batch["items"]:
            key = f"{batch['batch']}:{item['index']}"
            items[key] = {
                "batch": batch["batch"],
                "index": item["index"],
                "poi": item["poi"],
                "ai_status": item["status"],
                "confidence": item["confidence"],
                "issues": item["issues"],
                "manual_decision": None,
            }
    return {
        "enabled": True,
        "ai_review": os.path.abspath(ai_path),
        "manual_review": os.path.abspath(manual_path),
        "summary": ai_report["summary"],
        "items": items,
    }


def _sync_manifest(job: dict, manual: dict) -> None:
    manifest_path = job["manifest_path"]
    if not os.path.isfile(manifest_path):
        return
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    review = manifest.get("review", {})
    by_key = {x["key"]: x for x in manual.get("items", [])}
    for key, item in review.get("items", {}).items():
        if key in by_key:
            item["manual_decision"] = by_key[key].get("decision")
            item["manual_note"] = by_key[key].get("note", "")
    review["manual_completed"] = manual.get("completed", False)
    decisions = [x.get("decision", "pending") for x in manual.get("items", [])]
    review["manual_summary"] = {
        "total": len(decisions),
        "pending": decisions.count("pending"),
        "accepted": decisions.count("accepted"),
        "rejected": decisions.count("rejected"),
        "redo": decisions.count("redo"),
    }
    manifest["review"] = review
    _write_json(manifest_path, manifest)


def ensure_full_manual_review(manifest_path: str) -> tuple[dict, str]:
    """Create/merge a human-evaluation record for every cropped POI in a manifest."""
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    review = manifest.setdefault("review", {"enabled": False})
    review_dir = os.path.join(os.path.dirname(manifest_path), "review")
    manual_path = review.get("manual_review") or os.path.join(review_dir, "manual_review.json")
    existing = {}
    if os.path.isfile(manual_path):
        try:
            with open(manual_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            existing = {x["key"]: x for x in old.get("items", []) if isinstance(x, dict) and "key" in x}
        except Exception:
            existing = {}

    ai_items = review.setdefault("items", {})
    mapping = manifest.get("mapping", {})
    items = []
    for batch in manifest.get("batches", []):
        batch_index = int(batch.get("index", 0))
        for index, poi in enumerate(batch.get("pois", []), 1):
            key = f"{batch_index}:{index}"
            previous = existing.get(key, {})
            if previous.get("poi") != poi:
                previous = {}
            ai_item = ai_items.setdefault(key, {
                "batch": batch_index,
                "index": index,
                "poi": poi,
                "ai_status": "NOT_RUN",
                "confidence": None,
                "issues": [],
                "manual_decision": None,
            })
            items.append({
                "key": key,
                "batch": batch_index,
                "index": index,
                "poi": poi,
                "output": mapping.get(poi, ""),
                "ai_status": ai_item.get("ai_status", "NOT_RUN"),
                "confidence": ai_item.get("confidence"),
                "issues": ai_item.get("issues", []),
                "decision": previous.get("decision", "pending"),
                "note": previous.get("note", ""),
                "updated_at": previous.get("updated_at", ""),
            })

    manual = {
        "version": 1,
        "destination": manifest.get("destination", ""),
        "scope": "all_cropped_icons",
        "completed": bool(items) and all(x["decision"] != "pending" for x in items),
        "items": items,
    }
    review["manual_review"] = os.path.abspath(manual_path)
    manifest["review"] = review
    _write_json(manual_path, manual)
    _write_json(manifest_path, manifest)
    job = {"manual": manual, "manual_path": manual_path, "manifest_path": manifest_path}
    _sync_manifest(job, manual)
    return manual, manual_path


def save_manual_decision(job: dict, key: str, decision: str, note: str = "") -> dict:
    """Persist one human decision and mirror it into the destination manifest."""
    if decision not in REVIEW_DECISIONS:
        raise ValueError("invalid decision")
    target = next((x for x in job["manual"]["items"] if x["key"] == key), None)
    if target is None:
        raise KeyError(f"unknown review item: {key}")
    target["decision"] = decision
    target["note"] = str(note)[:1000]
    target["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    job["manual"]["completed"] = all(x["decision"] != "pending" for x in job["manual"]["items"])
    _write_json(job["manual_path"], job["manual"])
    _sync_manifest(job, job["manual"])
    return target


def _review_html() -> bytes:
    html = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>POI 图标人工复审</title>
<style>
body{font-family:Arial,"PingFang SC",sans-serif;margin:0;color:#202124;background:#f7f8fa}header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:14px 22px;z-index:2;display:flex;justify-content:space-between;align-items:center}.wrap{max-width:1200px;margin:auto;padding:20px}.item{display:grid;grid-template-columns:260px 1fr;gap:20px;background:#fff;border:1px solid #ddd;border-radius:8px;padding:16px;margin-bottom:16px}.item img{width:100%;aspect-ratio:1;object-fit:contain;background:#fff;border:1px solid #eee}.meta h2{font-size:18px;margin:0 0 8px}.meta p{margin:6px 0;line-height:1.45}.choices{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.choices button,#finish{border:1px solid #aaa;background:#fff;padding:9px 13px;border-radius:6px;cursor:pointer}.choices button.active{background:#1769e0;color:#fff;border-color:#1769e0}textarea{width:100%;min-height:60px;box-sizing:border-box;padding:8px}small{color:#666}.empty{text-align:center;padding:60px;background:#fff}.badge{font-weight:bold}.FAIL,.REVIEW_ERROR{color:#b3261e}.REVIEW{color:#9a6700}@media(max-width:700px){.item{grid-template-columns:1fr}header{align-items:flex-start;gap:10px}}
</style></head><body><header><div><strong>POI 图标人工复审</strong><br><small id="summary">加载中...</small></div><button id="finish">完成审核</button></header><main class="wrap" id="app"></main>
<script>
const labels={accepted:'人工通过',rejected:'驳回',redo:'需要重做',pending:'暂不处理'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function save(x,decision,note){await fetch('/api/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job:x.job,key:x.key,decision,note})});}
async function load(){const data=await (await fetch('/api/data')).json();const app=document.getElementById('app');document.getElementById('summary').textContent=`共 ${data.items.length} 个异常或待确认项，操作会自动保存`;if(!data.items.length){app.innerHTML='<div class="empty">没有需要人工复审的项目。</div>';return;}for(const x of data.items){const el=document.createElement('section');el.className='item';el.innerHTML=`<img src="${x.asset_url}" alt="${esc(x.poi)}"><div class="meta"><h2>${esc(x.destination)} · batch${x.batch} · 第${x.index}格</h2><p><strong>${esc(x.poi)}</strong></p><p>${x.description?esc(x.description):'<small>未提供视觉描述</small>'}</p><p class="badge ${x.status}">${x.status} · 置信度 ${Math.round(x.confidence*100)}%</p><p>${esc(x.reason)}</p><p><small>问题：${esc((x.issues||[]).join(', ')||'未指定')}</small></p><div class="choices"></div><textarea placeholder="人工备注（可选）"></textarea></div>`;const choices=el.querySelector('.choices'),note=el.querySelector('textarea');note.value=x.note||'';for(const [value,label] of Object.entries(labels)){const b=document.createElement('button');b.textContent=label;b.className=x.decision===value?'active':'';b.onclick=async()=>{await save(x,value,note.value);choices.querySelectorAll('button').forEach(v=>v.classList.remove('active'));b.classList.add('active');};choices.appendChild(b);}note.onchange=()=>save(x,choices.querySelector('.active')?.textContent?Object.entries(labels).find(v=>v[1]===choices.querySelector('.active').textContent)[0]:'pending',note.value);app.appendChild(el);}}
document.getElementById('finish').onclick=async()=>{await fetch('/api/finish',{method:'POST'});document.body.innerHTML='<main class="wrap"><div class="empty"><h2>审核结果已保存</h2><p>可以关闭此页面。</p></div></main>';};load();
</script></body></html>"""
    return html.encode("utf-8")


def serve_manual_review(jobs: List[dict], *, timeout: int = 1800, open_browser: bool = True) -> None:
    """Run a localhost review UI until Finish is clicked or timeout expires."""
    active_jobs = []
    asset_map: Dict[str, str] = {}
    for job_index, job in enumerate(jobs):
        ai = job["ai_report"]
        manual = ensure_manual_review(ai, job["manual_path"])
        _sync_manifest(job, manual)
        active_jobs.append({**job, "manual": manual})
        for batch in ai["batches"]:
            for item in batch["items"]:
                candidate = item.get("candidate")
                if candidate:
                    asset_map[f"{job_index}:{batch['batch']}:{item['index']}"] = candidate

    if not any(job["manual"]["items"] for job in active_jobs):
        return

    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send(self, body: bytes, content_type: str, status=HTTPStatus.OK):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                self._send(_review_html(), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/data":
                payload = []
                for job_index, job in enumerate(active_jobs):
                    manual_by_key = {x["key"]: x for x in job["manual"]["items"]}
                    for batch in job["ai_report"]["batches"]:
                        for item in batch["items"]:
                            if item["status"] == "PASS":
                                continue
                            key = f"{batch['batch']}:{item['index']}"
                            human = manual_by_key[key]
                            payload.append({**item, **human, "job": job_index,
                                "destination": job["ai_report"]["destination"],
                                "batch": batch["batch"],
                                "asset_url": "/asset/" + urllib.parse.quote(f"{job_index}:{batch['batch']}:{item['index']}")})
                self._send(json.dumps({"items": payload}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return
            if parsed.path.startswith("/asset/"):
                token = urllib.parse.unquote(parsed.path[len("/asset/"):])
                path = asset_map.get(token)
                if path and os.path.isfile(path):
                    with open(path, "rb") as f:
                        self._send(f.read(), "image/png")
                else:
                    self._send(b"not found", "text/plain", HTTPStatus.NOT_FOUND)
                return
            self._send(b"not found", "text/plain", HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if self.path == "/api/finish":
                finished.set()
                self._send(b'{"ok":true}', "application/json")
                return
            if self.path != "/api/decision":
                self._send(b"not found", "text/plain", HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                job_index = int(data["job"])
                job = active_jobs[job_index]
                save_manual_decision(job, data["key"], data["decision"], data.get("note", ""))
                self._send(b'{"ok":true}', "application/json")
            except Exception as exc:
                self._send(json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json", HTTPStatus.BAD_REQUEST)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"\n[人工复审] 已生成异常审核页: {url}")
    if open_browser:
        webbrowser.open(url)
    finished.wait(timeout=max(1, timeout))
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    if not finished.is_set():
        print("[人工复审] 等待超时，已保存现有决定；未处理项保持 pending。")
    else:
        print("[人工复审] 审核结果已保存。")
