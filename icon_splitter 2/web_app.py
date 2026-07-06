#!/usr/bin/env python3
"""Local browser workspace for POI icon splitting and human evaluation."""

from __future__ import annotations

import contextlib
import cgi
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import reviewer
import candidate_manager
import prompt_generator
import review_board
import sheet_importer
import splitter


APP_NAME = "POI Icon Studio"
SOURCE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def search_real_images(query: str, limit: int = 8) -> dict:
    query = " ".join(str(query or "").split())[:180]
    limit = max(1, min(int(limit or 8), 12))
    if not query:
        return {"query": "", "images": [], "error": "搜索关键词为空"}
    url = "https://www.bing.com/images/search?q=" + urllib.parse.quote(query)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            html = response.read(900000).decode("utf-8", "ignore")
    except Exception as exc:
        return {"query": query, "images": [], "error": f"真实图片搜索失败：{exc}"}

    candidates = []
    for pattern in (r'"murl"\s*:\s*"([^"]+)"', r'&quot;murl&quot;\s*:\s*&quot;([^&]+)&quot;'):
        for match in re.finditer(pattern, html):
            value = match.group(1)
            try:
                value = json.loads(f'"{value}"')
            except Exception:
                value = value.replace("\\/", "/")
            value = urllib.parse.unquote(value).replace("&amp;", "&")
            if value.startswith(("http://", "https://")) and value not in candidates:
                candidates.append(value)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    return {"query": query, "images": candidates[:limit], "error": "" if candidates else "没有解析到可展示图片"}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class LogWriter(io.TextIOBase):
    def __init__(self, state: "StudioState"):
        self.state = state

    def write(self, value):
        if value:
            with self.state.lock:
                self.state.logs += value
                self.state.logs = self.state.logs[-100000:]
        return len(value)

    def flush(self):
        return None


class StudioState:
    def __init__(self):
        self.lock = threading.RLock()
        self.workspace = self._initial_workspace()
        self.running = False
        self.logs = ""
        self.last_error = ""
        self.last_results = []
        self._apply_workspace(self.workspace)

    def _initial_workspace(self) -> Path:
        try:
            if CONFIG_PATH.is_file():
                configured = Path(json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("workspace", ""))
                if configured.is_dir():
                    return configured
        except Exception:
            pass
        if (SOURCE_DIR / "inputs").is_dir():
            return SOURCE_DIR
        return Path.home() / "Documents" / APP_NAME

    def _apply_workspace(self, workspace: Path):
        workspace = workspace.expanduser().resolve()
        (workspace / "inputs").mkdir(parents=True, exist_ok=True)
        (workspace / "outputs").mkdir(parents=True, exist_ok=True)
        self.workspace = workspace
        splitter.INPUTS_DIR = str(workspace / "inputs")
        splitter.OUTPUTS_DIR = str(workspace / "outputs")
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps({"workspace": str(workspace)}, indent=2), encoding="utf-8")
        except Exception:
            pass

    def set_workspace(self, path: str):
        if self.running:
            raise RuntimeError("任务运行中，暂时不能切换工作目录")
        if not path.strip():
            raise ValueError("工作目录不能为空")
        self._apply_workspace(Path(path))

    def destinations(self):
        return [name for name, _ in splitter.list_destinations()]

    def snapshot(self):
        with self.lock:
            return {
                "workspace": str(self.workspace),
                "destinations": self.destinations(),
                "running": self.running,
                "logs": self.logs,
                "error": self.last_error,
                "results": self.last_results,
            }

    def destination_data(self, name: str):
        if name not in self.destinations():
            raise ValueError(f"找不到城市：{name}")
        input_dir = Path(splitter.INPUTS_DIR) / name
        specs = splitter.load_pois_json(str(input_dir))
        batches = splitter.find_batch_files(str(input_dir))
        project = prompt_generator.load_city_project(input_dir)
        existing_batches = {Path(path).stem.lower(): path for path in splitter.find_batch_files(str(input_dir))}
        project_pages = []
        for page in project.get("pages", []):
            batch_key = f"batch{page['page']}"
            batch_path = existing_batches.get(batch_key, "")
            prompt_path = Path(page["prompt"])
            iconic_path = Path(page.get("prompt_iconic", ""))
            identity_path = Path(page.get("prompt_identity", ""))
            original_text = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
            iconic_text = iconic_path.read_text(encoding="utf-8") if iconic_path.is_file() else ""
            identity_text = identity_path.read_text(encoding="utf-8") if identity_path.is_file() else ""
            project_pages.append({
                **page,
                "prompt_text": original_text,
                "prompt_iconic_text": iconic_text,
                "prompt_identity_text": identity_text,
                "prompt_variants": {
                    "original": original_text,
                    "iconic": iconic_text,
                    "identity": identity_text,
                },
                "batch_path": os.path.abspath(batch_path) if batch_path else "",
                "batch_present": bool(batch_path),
            })
        output_dir = Path(splitter.OUTPUTS_DIR) / name
        candidate_data = candidate_manager.build_candidate_data(
            name, input_dir, output_dir, project
        )
        for page in project_pages:
            page["candidate_groups"] = candidate_data["pages"].get(int(page["page"]), [])
        result = {
            "name": name,
            "display_name": project.get("city", name),
            "input": {
                "batch_count": len(batches),
                "poi_count": len(specs),
                "described_count": sum(1 for x in specs if x.get("description")),
                "batches": [os.path.basename(x) for x in batches],
            },
            "project": {
                **project,
                "pages": project_pages,
                "ready_to_split": candidate_data["ready_to_process"],
                "ready_to_process": candidate_data["ready_to_process"],
                "ready_to_export": candidate_data["ready_to_export"],
                "workflow_status": candidate_data["workflow_status"],
            },
            "records": candidate_data["records"],
            "summary": candidate_data["summary"],
            "candidate": {
                "pending_groups": candidate_data["pending_groups"],
                "estimated_ai_calls": candidate_data["estimated_ai_calls"],
                "max_groups_per_page": candidate_manager.MAX_GROUPS_PER_PAGE,
            },
        }
        return result

    def run(self, destinations: list[str], ocr: bool, ai_review: bool):
        with self.lock:
            if self.running:
                raise RuntimeError("已有任务正在运行")
            available = set(self.destinations())
            if not destinations or any(x not in available for x in destinations):
                raise ValueError("请选择有效城市")
            self.running = True
            self.logs = ""
            self.last_error = ""
            self.last_results = []
        thread = threading.Thread(
            target=self._run_worker,
            args=(destinations, bool(ocr), bool(ai_review)),
            daemon=True,
        )
        thread.start()

    def _run_worker(self, destinations: list[str], ocr: bool, ai_review: bool):
        writer = LogWriter(self)
        results = []
        try:
            splitter.REMOVE_TEXT = ocr
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                print(f"[配置] OCR 去文字：{'开启' if ocr else '关闭'}")
                print(f"[配置] AI 整图初审：{'开启' if ai_review else '关闭'}")
                for name in destinations:
                    input_dir = Path(splitter.INPUTS_DIR) / name
                    output_dir = Path(splitter.OUTPUTS_DIR) / name
                    project = prompt_generator.load_city_project(input_dir)
                    result = candidate_manager.process_pending_groups(
                        name, input_dir, output_dir, project,
                        ai_review=ai_review, log=print,
                    )
                    results.append({
                        "destination": name,
                        "success": result.get("success", False),
                        "error": result.get("error", ""),
                        "processed": result.get("processed", 0),
                        "failed": result.get("failed", 0),
                        "skipped": result.get("skipped", 0),
                    })
        except Exception:
            with self.lock:
                self.last_error = traceback.format_exc()
                self.logs += "\n" + self.last_error
        finally:
            with self.lock:
                self.last_results = results
                self.running = False

    def save_decision(self, destination: str, key: str, decision: str, note: str):
        output_dir = Path(splitter.OUTPUTS_DIR) / destination
        if decision == "redo":
            candidate_manager.mark_redo(output_dir, destination, key, note)
        else:
            candidate_manager.save_note(output_dir, destination, key, note)

    def select_candidate(self, destination: str, key: str, candidate_id: str, note: str):
        if destination not in self.destinations():
            raise ValueError("请选择有效城市")
        return candidate_manager.select_candidate(
            Path(splitter.OUTPUTS_DIR) / destination, destination, key, candidate_id, note
        )

    def delete_candidate_group(self, destination: str, candidate_id: str):
        if self.running:
            raise RuntimeError("任务运行中，暂时不能删除候选组")
        if destination not in self.destinations():
            raise ValueError("请选择有效城市")
        input_dir = Path(splitter.INPUTS_DIR) / destination
        project = prompt_generator.load_city_project(input_dir)
        return candidate_manager.delete_group(
            input_dir, Path(splitter.OUTPUTS_DIR) / destination,
            project, destination, candidate_id,
        )

    def delete_candidates(self, destination: str, key: str, candidate_ids: list[str]):
        if self.running:
            raise RuntimeError("任务运行中，暂时不能删除候选图")
        if destination not in self.destinations():
            raise ValueError("请选择有效城市")
        return candidate_manager.delete_candidates(
            Path(splitter.OUTPUTS_DIR) / destination,
            destination, key, candidate_ids,
        )

    def export_selected_candidates(self, destination: str, key: str, candidate_ids: list[str], export_dir: str = ""):
        if self.running:
            raise RuntimeError("任务运行中，暂时不能单独导出")
        if destination not in self.destinations():
            raise ValueError("请选择有效城市")
        input_dir = Path(splitter.INPUTS_DIR) / destination
        output_dir = Path(splitter.OUTPUTS_DIR) / destination
        project = prompt_generator.load_city_project(input_dir)
        return candidate_manager.export_selected_candidates(
            destination, input_dir, output_dir, project, key, candidate_ids, export_dir
        )

    def choose_folder(self, default_dir: str = ""):
        default_path = Path(default_dir or (self.workspace / "outputs")).expanduser()
        if not default_path.is_absolute():
            default_path = self.workspace / default_path
        default_path.mkdir(parents=True, exist_ok=True)
        default_path = default_path.resolve()
        if sys.platform == "darwin":
            prompt = '选择单独导出的保存文件夹'
            escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"')
            escaped_path = str(default_path).replace("\\", "\\\\").replace('"', '\\"')
            script = (
                f'POSIX path of (choose folder with prompt "{escaped_prompt}" '
                f'default location POSIX file "{escaped_path}")'
            )
            completed = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if completed.returncode != 0:
                error = (completed.stderr or "").strip()
                if "User canceled" in error or "用户已取消" in error:
                    return {"canceled": True, "path": ""}
                raise RuntimeError(error or "系统选择文件夹弹窗打开失败")
            selected = completed.stdout.strip()
            return {"canceled": not bool(selected), "path": str(Path(selected).expanduser().resolve()) if selected else ""}
        try:
            import tkinter
            from tkinter import filedialog
        except Exception as exc:
            raise RuntimeError(f"当前系统不支持原生选择文件夹弹窗：{exc}") from exc
        root = tkinter.Tk()
        root.withdraw()
        try:
            selected = filedialog.askdirectory(
                title="选择单独导出的保存文件夹",
                initialdir=str(default_path),
                mustexist=True,
            )
        finally:
            root.destroy()
        return {"canceled": not bool(selected), "path": str(Path(selected).expanduser().resolve()) if selected else ""}

    def export_final(self, destination: str):
        if destination not in self.destinations():
            raise ValueError("请选择有效城市")
        input_dir = Path(splitter.INPUTS_DIR) / destination
        output_dir = Path(splitter.OUTPUTS_DIR) / destination
        project = prompt_generator.load_city_project(input_dir)
        return candidate_manager.export_final(destination, input_dir, output_dir, project)

    def export_review_board(self, destination: str):
        if destination not in self.destinations():
            raise ValueError("请选择有效城市")
        input_dir = Path(splitter.INPUTS_DIR) / destination
        output_dir = Path(splitter.OUTPUTS_DIR) / destination
        project = prompt_generator.load_city_project(input_dir)
        return review_board.export_review_board(
            destination, input_dir, output_dir, project
        )

    def open_output(self, destination: Optional[str]):
        path = Path(splitter.OUTPUTS_DIR)
        if destination and (path / destination).is_dir():
            path = path / destination
        subprocess.Popen(["open", str(path)])

    def import_assets(self, city: str, table_upload, image_uploads: list, replace: bool = False):
        if self.running:
            raise RuntimeError("任务运行中，暂时不能导入素材")
        city = city.strip()
        if not city:
            raise ValueError("请填写城市名称")
        if table_upload is None or not getattr(table_upload, "filename", ""):
            raise ValueError("请选择一份 XLSX 或 CSV 表格")
        if not image_uploads:
            raise ValueError("请至少选择一张网格图片")

        table_name = os.path.basename(table_upload.filename)
        table_suffix = Path(table_name).suffix.lower()
        if table_suffix not in (".xlsx", ".csv"):
            raise ValueError("表格只支持 .xlsx 或 .csv")
        allowed_images = {".png", ".jpg", ".jpeg"}
        for upload in image_uploads:
            if Path(os.path.basename(upload.filename)).suffix.lower() not in allowed_images:
                raise ValueError(f"不支持的图片格式：{upload.filename}")

        with tempfile.TemporaryDirectory(prefix="poi-import-") as temp_dir:
            temp_table = Path(temp_dir) / ("source" + table_suffix)
            with open(temp_table, "wb") as output:
                shutil.copyfileobj(table_upload.file, output)
            matched_city, pois = sheet_importer.extract_pois(temp_table, city)
            expected_batches = math.ceil(len(pois) / splitter.BATCH_SIZE)
            if expected_batches > 10:
                raise ValueError("单个城市最多支持 160 个 POI（10 张4×4网格图）")
            ordered_images = sorted(image_uploads, key=lambda item: sheet_importer.natural_key(item.filename))
            if len(ordered_images) != expected_batches:
                raise ValueError(
                    f"表格读取到 {len(pois)} 个 POI，需要 {expected_batches} 张网格图，"
                    f"当前选择了 {len(ordered_images)} 张"
                )

            folder_name = splitter.safe_filename(city)
            if not folder_name:
                raise ValueError("城市名称无法作为文件夹名称")
            target = Path(splitter.INPUTS_DIR) / folder_name
            backup = None
            if target.exists() and any(target.iterdir()):
                if not replace:
                    raise FileExistsError("同名城市已存在；如需替换，请勾选“备份并替换”")
                backup_root = Path(splitter.INPUTS_DIR) / "_backups"
                backup_root.mkdir(parents=True, exist_ok=True)
                backup = backup_root / f"{folder_name}_{time.strftime('%Y%m%d_%H%M%S')}"
                shutil.move(str(target), str(backup))

            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(temp_table, target / ("source_table" + table_suffix))
            for index, upload in enumerate(ordered_images, 1):
                suffix = Path(os.path.basename(upload.filename)).suffix.lower()
                with open(target / f"batch{index}{suffix}", "wb") as output:
                    shutil.copyfileobj(upload.file, output)
            with open(target / "pois.json", "w", encoding="utf-8") as output:
                poi_specs = []
                for poi in pois:
                    prompt_name = prompt_generator.english_prompt_name(poi)
                    poi_specs.append({
                        "name": poi,
                        "name_zh": poi if prompt_name != poi else "",
                        "prompt_name": prompt_name,
                        "description": "",
                    })
                json.dump({"city": matched_city, "pois": poi_specs}, output, ensure_ascii=False, indent=2)

        return {
            "city": folder_name,
            "source_city": matched_city,
            "poi_count": len(pois),
            "batch_count": expected_batches,
            "backup": str(backup) if backup else None,
        }

    def import_table(self, table_upload, replace: bool = False):
        """Import one full spreadsheet and create a prompt-ready project for every city."""
        if self.running:
            raise RuntimeError("任务运行中，暂时不能导入表格")
        if table_upload is None or not getattr(table_upload, "filename", ""):
            raise ValueError("请选择一份 XLSX 或 CSV 表格")
        filename = os.path.basename(table_upload.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in (".xlsx", ".csv"):
            raise ValueError("表格只支持 .xlsx 或 .csv")

        with tempfile.TemporaryDirectory(prefix="poi-table-import-") as temp_dir:
            temp_table = Path(temp_dir) / ("source" + suffix)
            with open(temp_table, "wb") as output:
                shutil.copyfileobj(table_upload.file, output)
            grouped = sheet_importer.extract_all_cities(temp_table)
            oversized = [city for city, specs in grouped.items() if len(specs) > 160]
            if oversized:
                raise ValueError("以下城市超过160个POI：" + "、".join(oversized))

            created = []
            skipped = []
            backups = []
            for city, specs in grouped.items():
                folder_name = splitter.safe_filename(city)
                target = Path(splitter.INPUTS_DIR) / folder_name
                if target.exists() and any(target.iterdir()):
                    if not replace:
                        skipped.append(folder_name)
                        continue
                    backup_root = Path(splitter.INPUTS_DIR) / "_backups"
                    backup_root.mkdir(parents=True, exist_ok=True)
                    backup = backup_root / f"{folder_name}_{time.strftime('%Y%m%d_%H%M%S')}"
                    counter = 1
                    while backup.exists():
                        backup = backup_root / f"{folder_name}_{time.strftime('%Y%m%d_%H%M%S')}_{counter}"
                        counter += 1
                    shutil.move(str(target), str(backup))
                    backups.append(str(backup))
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(temp_table, target / ("source_table" + suffix))
                with open(target / "pois.json", "w", encoding="utf-8") as output:
                    json.dump({"city": city, "pois": specs}, output, ensure_ascii=False, indent=2)
                project = prompt_generator.write_city_project(target, city, specs)
                created.append({
                    "id": folder_name,
                    "city": city,
                    "poi_count": len(specs),
                    "page_count": project["page_count"],
                })
        return {
            "created": created,
            "skipped": skipped,
            "backups": backups,
            "city_count": len(created),
            "total_pois": sum(item["poi_count"] for item in created),
        }

    def upload_city_images(self, city_id: str, page: int, image_uploads: list):
        """Add up to ten candidate sprite sheets to one PAGE."""
        if self.running:
            raise RuntimeError("任务运行中，暂时不能上传图片")
        if city_id not in self.destinations():
            raise ValueError(f"找不到城市：{city_id}")
        if not image_uploads:
            raise ValueError("请至少选择一张网格图片")
        city_dir = Path(splitter.INPUTS_DIR) / city_id
        project = prompt_generator.load_city_project(city_dir)
        if not int(project.get("page_count", 0)):
            raise ValueError("该城市没有Prompt页面")
        uploads = sorted(image_uploads, key=lambda item: sheet_importer.natural_key(item.filename))
        saved = candidate_manager.add_uploads(city_dir, project, int(page), uploads)
        return {"city": city_id, "page": int(page), "saved": saved}

    def asset(self, path: str) -> Path:
        target = Path(path).expanduser().resolve()
        allowed_roots = [(self.workspace / "outputs").resolve(), (self.workspace / "inputs").resolve()]
        if not any(_is_relative_to(target, root) for root in allowed_roots):
            raise PermissionError("asset path is outside workspace inputs/outputs")
        if not target.is_file():
            raise FileNotFoundError(path)
        return target


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>POI Icon Studio</title><style>
:root{--bg:#f4f5f7;--panel:#fff;--sidebar:#20242b;--text:#20242b;--muted:#68707c;--line:#d9dde3;--accent:#1769e0;--green:#18794e;--amber:#9a6700;--red:#b3261e}*{box-sizing:border-box}body{margin:0;font:14px -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif;color:var(--text);background:var(--bg);height:100vh;overflow:hidden}button,input,textarea{font:inherit}.app{display:grid;grid-template-columns:248px 1fr;height:100vh;min-height:0}.sidebar{background:var(--sidebar);color:#f7f8fa;padding:22px 14px;display:flex;flex-direction:column;min-width:0;min-height:0}.brand{font-size:20px;font-weight:750;line-height:1.1;padding:0 8px 20px}.label{font-size:11px;font-weight:700;color:#aeb5c0;text-transform:uppercase;padding:8px}.workspace{display:flex;gap:6px;padding:0 6px 12px}.workspace input{min-width:0;flex:1;background:#343a44;color:#fff;border:1px solid #4b535f;border-radius:5px;padding:8px}.iconbtn{border:0;border-radius:5px;background:#343a44;color:#fff;padding:8px 10px;cursor:pointer}.cities{list-style:none;margin:0;padding:0;overflow:auto;flex:1;min-height:0}.cities button{width:100%;text-align:left;border:0;background:transparent;color:#e7eaf0;padding:11px 12px;border-radius:5px;cursor:pointer}.cities button:hover{background:#2c323b}.cities button.active{background:var(--accent);color:#fff;font-weight:650}.sidefoot{font-size:11px;color:#89919d;padding:12px 8px 0;overflow-wrap:anywhere}.main{min-width:0;min-height:0;height:100vh;display:grid;grid-template-rows:62px 46px minmax(0,1fr);overflow:hidden}.topbar{display:flex;align-items:center;justify-content:space-between;padding:0 22px;background:#fff;border-bottom:1px solid var(--line)}.topbar h1{font-size:16px;margin:0}.top-actions{display:flex;gap:8px}.button{border:1px solid #aeb4bd;background:#fff;border-radius:5px;padding:8px 13px;cursor:pointer}.button:hover{background:#f2f4f7}.button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:650}.button.danger{background:var(--red);border-color:var(--red);color:#fff;font-weight:650}.button:disabled{opacity:.45;cursor:not-allowed}.tabs{display:flex;align-items:end;padding:0 20px;background:#fff;border-bottom:1px solid var(--line)}.tab{border:0;background:transparent;padding:12px 16px 10px;cursor:pointer;border-bottom:3px solid transparent}.tab.active{border-color:var(--accent);color:var(--accent);font-weight:700}.view{display:none;padding:16px 20px;min-height:0;overflow:auto}.view.active{display:block}.band{background:#fff;border:1px solid var(--line);padding:14px 16px}.prompt-summary{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.prompt-layout{display:grid;grid-template-columns:210px minmax(0,1fr);height:calc(100vh - 216px);min-height:0;background:#fff;border:1px solid var(--line);overflow:hidden}.page-list{padding:10px;border-right:1px solid var(--line);overflow:auto;min-height:0}.page-list button{display:block;width:100%;border:0;background:transparent;text-align:left;padding:11px;border-radius:5px;cursor:pointer}.page-list button.active{background:#e8f1ff;color:#1155b6;font-weight:700}.prompt-panel{display:grid;grid-template-rows:auto minmax(0,1fr);padding:16px;min-width:0;min-height:0}.prompt-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}.prompt-text{width:100%;height:100%;resize:none;border:1px solid var(--line);background:#fbfcfd;padding:14px;font:12px Menlo,monospace;line-height:1.55}.run-layout{display:grid;grid-template-rows:auto auto minmax(220px,1fr);gap:12px;height:100%;min-height:0}.options{display:flex;align-items:center;gap:22px}.options strong{font-size:15px;margin-right:8px}.switch{display:flex;align-items:center;gap:8px}.run-actions{margin-left:auto;display:flex;gap:8px}.summary{color:var(--muted);line-height:1.6}.slots{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin-top:10px}.slot{border:1px solid var(--line);padding:10px;min-height:94px;display:grid;grid-template-columns:64px 1fr;gap:10px;align-items:center}.slot img{width:64px;height:64px;object-fit:contain;background:#fafbfc}.slot strong{display:block}.slot small{color:var(--muted)}.source-thumb{border:1px solid var(--line);background:#fafbfc;padding:0;width:54px;height:54px;cursor:zoom-in}.source-thumb:hover{border-color:var(--accent);box-shadow:0 0 0 2px #dce9fc}.source-thumb img{width:100%;height:100%;object-fit:contain;display:block}.source-preview{width:min(1180px,calc(100vw - 32px));max-height:calc(100vh - 40px)}.source-preview .modal-body{padding:14px;background:#f6f7f9}.source-preview-frame{height:min(72vh,760px);display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid var(--line);overflow:auto;position:relative}.source-preview-frame img{max-width:100%;max-height:100%;object-fit:contain}.source-nav{position:absolute;top:50%;transform:translateY(-50%);width:42px;height:56px;border:1px solid #aeb4bd;background:#ffffffe8;color:#20242b;border-radius:5px;font-size:28px;line-height:1;cursor:pointer}.source-nav:hover{background:#fff}.source-nav:disabled{opacity:.35;cursor:not-allowed}.source-nav.prev{left:12px}.source-nav.next{right:12px}.source-preview-meta{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.log{margin:0;background:#171a1f;color:#dce2eb;padding:14px;overflow:auto;white-space:pre-wrap;font:12px Menlo,monospace;min-height:0}.review-toolbar{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid var(--line);padding:10px 14px;margin-bottom:12px;min-width:0;overflow-x:auto;flex:0 0 auto}.stats{font-weight:700;margin-right:12px;white-space:nowrap}.filter{border:0;background:#f0f2f5;border-radius:5px;padding:7px 10px;cursor:pointer;white-space:nowrap}.filter.active{background:#dce9fc;color:#1155b6;font-weight:650}#review.active{display:grid;grid-template-rows:auto minmax(0,1fr);overflow:hidden}.review-layout{display:grid;grid-template-columns:minmax(480px,1.35fr) minmax(330px,.65fr);height:auto;min-height:0;background:#fff;border:1px solid var(--line);overflow:hidden}.table-wrap{overflow:auto;min-height:0;border-right:1px solid var(--line)}table{border-collapse:collapse;width:100%}th{position:sticky;top:0;z-index:2;background:#f7f8fa;text-align:left;padding:9px;border-bottom:1px solid var(--line);font-size:12px}td{padding:8px;border-bottom:1px solid #eceef1}tr.record{cursor:pointer}tr.record:hover{background:#f6f9fd}tr.record.active{background:#e8f1ff}.thumb{width:46px;height:46px;object-fit:contain;background:#fff;border:1px solid #eee}.pill{font-size:11px;font-weight:700}.PASS,.accepted,.ready,.completed{color:var(--green)}.REVIEW,.redo,.waiting{color:var(--amber)}.FAIL,.REVIEW_ERROR,.rejected{color:var(--red)}.NOT_RUN,.pending{color:var(--muted)}.detail{padding:20px;overflow:auto;min-height:0}.preview{display:flex;align-items:center;justify-content:center;width:100%;height:310px;background:#fafbfc;border:1px solid var(--line)}.preview img{max-width:100%;max-height:100%;image-rendering:auto}.detail h2{font-size:19px;margin:16px 0 6px;overflow-wrap:anywhere}.meta{color:var(--muted);line-height:1.55;white-space:pre-wrap}.decision{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:12px 0}.decision button{border:1px solid #aeb4bd;background:#fff;padding:9px 4px;border-radius:5px;cursor:pointer}.decision button.active{background:#dce9fc;border-color:var(--accent);color:#1155b6;font-weight:700}.detail textarea{width:100%;min-height:82px;resize:vertical;border:1px solid #aeb4bd;padding:8px;border-radius:5px;margin:6px 0 10px}.empty{padding:50px;text-align:center;color:var(--muted)}dialog{border:1px solid var(--line);border-radius:7px;padding:0;width:min(560px,calc(100vw - 32px));box-shadow:0 18px 60px #0005}dialog::backdrop{background:#0007}.modal-head{padding:16px 20px;border-bottom:1px solid var(--line);font-size:17px;font-weight:750}.modal-body{padding:18px 20px}.field{display:block;margin-bottom:15px}.field span{display:block;font-weight:650;margin-bottom:6px}.field input[type=text],.field input[type=file]{width:100%;border:1px solid #aeb4bd;border-radius:5px;padding:9px}.hint{font-size:12px;color:var(--muted);line-height:1.5}.modal-actions{display:flex;justify-content:flex-end;gap:8px;padding:12px 20px;border-top:1px solid var(--line)}.toast{position:fixed;right:20px;bottom:20px;background:#20242b;color:#fff;padding:10px 14px;border-radius:5px;opacity:0;pointer-events:none;transition:.2s}.toast.show{opacity:1}@media(max-width:900px){.app{grid-template-columns:200px 1fr}.review-layout{grid-template-columns:1fr}.detail{display:none}.options{flex-wrap:wrap}.run-actions{margin-left:0}.prompt-layout{grid-template-columns:150px minmax(0,1fr)}}
</style></head><body><div class="app"><aside class="sidebar"><div class="brand">POI ICON<br>STUDIO</div><div class="label">工作目录</div><div class="workspace"><input id="workspace"><button class="iconbtn" id="set-workspace" title="应用目录">设置</button></div><div class="label">城市项目</div><ul class="cities" id="cities"></ul><div class="sidefoot" id="sidefoot"></div></aside><main class="main"><header class="topbar"><h1 id="title">请先导入整张POI表格</h1><div class="top-actions"><button class="button primary" id="open-import">导入整张表</button><button class="button" id="open-output">打开输出目录</button></div></header><nav class="tabs"><button class="tab active" data-tab="prompt">城市与Prompt</button><button class="tab" data-tab="run">大图与切图</button><button class="tab" data-tab="review">人工评估</button></nav><section class="view active" id="prompt"><div class="prompt-summary band"><div><strong id="project-title">暂无城市项目</strong><div class="summary" id="project-summary">上传表格后会自动建立全部城市及分页Prompt。</div></div><button class="button" id="copy-prompt">复制当前Prompt</button></div><div class="prompt-layout"><aside class="page-list" id="page-list"></aside><div class="prompt-panel"><div class="prompt-head"><strong id="prompt-title">请选择PAGE</strong><span class="summary" id="prompt-meta"></span></div><textarea class="prompt-text" id="prompt-text" readonly placeholder="导入表格后，Prompt会显示在这里。"></textarea></div></div></section><section class="view" id="run"><div class="run-layout"><div class="band"><div class="options"><strong>外部生成大图回填</strong><span class="summary" id="slot-summary">请选择城市</span><div class="run-actions"><button class="button primary" id="open-upload-images">上传当前城市大图</button></div></div><div class="slots" id="batch-slots"></div></div><div class="band options"><strong>切图选项</strong><label class="switch"><input type="checkbox" id="ocr" checked> OCR 去文字</label><label class="switch"><input type="checkbox" id="ai-review"> AI 整图初审（使用 Plus 额度）</label><div class="run-actions"><button class="button" id="run-all">切图全部就绪城市</button><button class="button primary" id="run-current">切图当前城市</button></div></div><pre class="log" id="log">等待大图上传…</pre></div></section><section class="view" id="review"><div class="review-toolbar"><span class="stats" id="stats">暂无评估数据</span><button class="filter" data-filter="all">全部</button><button class="filter active" data-filter="pending">待处理</button><button class="filter" data-filter="ai_flags">AI异常</button><button class="filter" data-filter="accepted">已通过</button><button class="filter" data-filter="redo">需重做</button><button class="filter" data-filter="rejected">已驳回</button></div><div class="review-layout"><div class="table-wrap"><table><thead><tr><th>预览</th><th>POI</th><th>AI</th><th>人工结论</th></tr></thead><tbody id="records"></tbody></table></div><aside class="detail" id="detail"><div class="empty">切图后选择一张图片开始评估</div></aside></div></section></main></div><dialog id="import-modal"><form id="import-form"><div class="modal-head">导入完整POI表格</div><div class="modal-body"><label class="field"><span>POI总表</span><input type="file" name="table" accept=".xlsx,.csv" required></label><p class="hint">应用会读取表格中的全部城市，按城市建立项目，并每16个POI生成一个PAGE Prompt。表格必须同时包含城市列和POI列。</p><label class="switch"><input type="checkbox" name="replace"> 同名城市存在时，备份旧项目并重新建立</label></div><div class="modal-actions"><button type="button" class="button" id="cancel-import">取消</button><button type="submit" class="button primary" id="submit-import">导入并生成Prompt</button></div></form></dialog><dialog id="upload-modal"><form id="upload-form"><div class="modal-head">上传当前城市大图</div><div class="modal-body"><input type="hidden" name="city" id="upload-city"><label class="field"><span>外部生成的4×4网格图片</span><input type="file" name="images" accept="image/png,image/jpeg" multiple required></label><p class="hint">文件名含 batch1/page1 时会放入指定PAGE；普通文件按自然顺序填入空槽位。可以每生成一张就上传一张。</p><label class="switch"><input type="checkbox" name="replace"> 允许替换已有PAGE图片（旧图会备份）</label></div><div class="modal-actions"><button type="button" class="button" id="cancel-upload">取消</button><button type="submit" class="button primary" id="submit-upload">上传图片</button></div></form></dialog><dialog id="source-preview-modal" class="source-preview"><div class="modal-head" id="source-preview-title">候选大图预览</div><div class="modal-body"><div class="source-preview-frame"><button type="button" class="source-nav prev" id="source-preview-prev" title="上一张">‹</button><img id="source-preview-image" alt="候选大图预览"><button type="button" class="source-nav next" id="source-preview-next" title="下一张">›</button></div><p class="source-preview-meta" id="source-preview-meta"></p></div><div class="modal-actions"><button type="button" class="button danger" id="delete-source-preview">删除当前大图</button><button type="button" class="button" id="close-source-preview">关闭</button></div></dialog><div class="toast" id="toast"></div>
<script>
const S={state:null,city:null,data:null,page:1,promptVariant:'original',filter:'pending',current:null,decision:'pending',deleteMode:false,deleteTargets:[],exportMode:false,exportTargets:[],sourcePreviewIndex:0,realImageKey:''};const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const aiLabel=s=>({PASS:'通过',REVIEW:'待人工确认',FAIL:'图片不合格',REVIEW_ERROR:'系统错误',NOT_RUN:'未运行'})[s]||s;const promptVariantLabel=()=>({original:'原版 Prompt',iconic:'Prompt_图标化',identity:'Prompt_本体强化'})[S.promptVariant]||'原版 Prompt';const promptVariantText=p=>({original:p.prompt_text,iconic:p.prompt_iconic_text,identity:p.prompt_identity_text})[S.promptVariant]||p.prompt_text;const api=async(path,opt={})=>{const r=await fetch(path,opt);const j=await r.json();if(!r.ok)throw Error(j.error||'请求失败');return j};const post=(path,data)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});function toast(t){const e=$('#toast');e.textContent=t;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),1800)}function asset(path){return path?'/asset?path='+encodeURIComponent(path):''}
async function refresh(){S.state=await api('/api/state');$('#workspace').value=S.state.workspace;$('#sidefoot').textContent=S.state.workspace;const list=$('#cities');list.innerHTML=S.state.destinations.map(x=>`<li><button class="${x===S.city?'active':''}" data-city="${esc(x)}">${esc(x.replaceAll('_',' '))}</button></li>`).join('');list.querySelectorAll('button').forEach(b=>b.onclick=()=>selectCity(b.dataset.city));if(!S.city&&S.state.destinations.length)await selectCity(S.state.destinations[0]);$('#log').textContent=S.state.logs||'等待大图上传…';$('#log').scrollTop=$('#log').scrollHeight;if(S.state.running)setTimeout(refresh,1000);else if(S._wasRunning){S._wasRunning=false;await loadCity();toast('切图处理完成')}S._wasRunning=S.state.running;updateRunButtons()}
async function selectCity(name){S.city=name;S.page=1;S.current=null;document.querySelectorAll('#cities button').forEach(b=>b.classList.toggle('active',b.dataset.city===name));await loadCity()}
async function loadCity(){if(!S.city)return;try{S.data=await api('/api/destination?name='+encodeURIComponent(S.city));$('#title').textContent=S.data.display_name;renderProject();renderRecords()}catch(e){S.data=null;$('#title').textContent=S.city;$('#project-summary').textContent='项目读取失败：'+e.message;renderProject();renderRecords()}updateRunButtons()}
function renderProject(){const p=S.data?.project;if(!p){$('#project-title').textContent='暂无城市项目';$('#project-summary').textContent='导入整张POI表格后自动建立。';$('#page-list').innerHTML='';$('#prompt-text').value='';$('#batch-slots').innerHTML='';$('#copy-prompt').disabled=true;return}$('#project-title').textContent=p.city;$('#project-summary').textContent=`${p.total_pois} 个 POI · ${p.page_count} 个PAGE · ${S.data.input.described_count} 个含视觉描述 · 状态 ${p.workflow_status}`;$('#page-list').innerHTML=p.pages.map(x=>`<button data-page="${x.page}" class="${x.page===S.page?'active':''}">PAGE ${x.page}<br><small>${x.start_index}-${x.end_index} · ${x.batch_present?'图片已上传':'等待图片'}</small></button>`).join('');document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>showPage(Number(b.dataset.page)));showPage(Math.min(S.page,p.page_count));renderSlots()}
function showPage(page){const p=S.data?.project?.pages.find(x=>x.page===page);if(!p)return;S.page=page;document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',Number(b.dataset.page)===page));document.querySelectorAll('[data-prompt-variant]').forEach(b=>b.classList.toggle('active',b.dataset.promptVariant===S.promptVariant));$('#prompt-title').textContent=`PAGE ${page} · ${p.poi_count} 个POI`;$('#prompt-meta').textContent=p.described_count===p.poi_count?'全部含视觉描述':`${p.described_count}/${p.poi_count} 含视觉描述`;$('#prompt-text').value=promptVariantText(p);$('#copy-prompt').textContent=`复制 PAGE ${page} ${promptVariantLabel()}`;$('#copy-prompt').disabled=!$('#prompt-text').value}
function setPromptVariant(variant){S.promptVariant=variant;showPage(S.page)}
function renderSlots(){const p=S.data?.project;if(!p)return;const total=p.pages.reduce((n,x)=>n+x.candidate_groups.length,0),pending=S.data?.candidate?.pending_groups||0;$('#slot-summary').textContent=`共 ${total} 组候选 · 待切 ${pending} 组 · 每PAGE最多10组`;$('#batch-slots').innerHTML=p.pages.map(x=>`<div style="grid-column:1/-1;border-bottom:1px solid var(--line);padding:10px 0"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><div><strong>PAGE ${x.page}</strong> <span class="summary">${x.poi_count} 个POI · ${x.candidate_groups.length}/10组</span></div><button class="button" data-upload-page="${x.page}" ${x.candidate_groups.length>=10?'disabled':''}>上传候选</button></div><div style="display:flex;gap:8px;overflow:auto">${x.candidate_groups.length?x.candidate_groups.map(g=>`<div style="flex:0 0 150px;border:1px solid var(--line);padding:8px;display:grid;grid-template-columns:54px 1fr;gap:8px"><button type="button" class="source-thumb" data-source-preview-id="${g.id}" title="查看候选大图"><img src="${asset(g.source)}" alt="候选大图缩略图"></button><div><strong>组${String(g.group).padStart(2,'0')}</strong><br><small class="${g.status}">${({pending:'待切图',processed:'已切图',failed:'失败'})[g.status]||g.status}</small><br><button class="iconbtn" style="margin-top:4px;padding:3px 6px;background:#eef0f3;color:#333" data-delete-group="${g.id}" title="删除候选组">删除</button></div></div>`).join(''):'<span class="summary">尚未上传候选大图</span>'}</div></div>`).join('');document.querySelectorAll('[data-upload-page]').forEach(b=>b.onclick=()=>openUpload(Number(b.dataset.uploadPage)));document.querySelectorAll('[data-delete-group]').forEach(b=>b.onclick=()=>deleteGroup(b.dataset.deleteGroup));document.querySelectorAll('[data-source-preview-id]').forEach(b=>b.onclick=()=>openSourcePreview(b.dataset.sourcePreviewId))}
function updateRunButtons(){const running=!!S.state?.running,ready=!!S.data?.project?.ready_to_process;$('#run-current').disabled=running||!ready;$('#run-all').disabled=running;$('#open-upload-images').disabled=!S.city||running;const exportButton=$('#export-final');if(exportButton)exportButton.disabled=running||!S.data?.project?.ready_to_export;const boardButton=$('#export-review-board');if(boardButton)boardButton.disabled=running||!(S.data?.records?.length)}
function filtered(){if(!S.data)return[];const r=S.data.records||[];if(S.filter==='all')return r;if(S.filter==='ai_flags')return r.filter(x=>x.has_ai_flags);return r.filter(x=>(x.decision||'pending')===S.filter)}
function renderRecords(){const d=S.data?.summary||{total:0,pending:0,accepted:0,redo:0};$('#stats').textContent=`共 ${d.total} 个POI · 未选择 ${d.pending} · 已选择 ${d.accepted} · 重做 ${d.redo}`;const rows=filtered();$('#records').innerHTML=rows.length?rows.map(x=>`<tr class="record ${S.current?.key===x.key?'active':''}" data-key="${x.key}"><td><div style="display:flex;gap:5px;max-width:450px;overflow-x:auto;padding:2px">${x.candidates.length?x.candidates.map(c=>{const selected=c.candidate_id===x.selected_candidate;return `<button data-select-candidate="${c.candidate_id}" data-record-key="${x.key}" title="点击设为最终版本" style="position:relative;flex:0 0 50px;width:50px;height:50px;padding:1px;border:2px solid ${selected?'#18864b':'#d9dde3'};background:#fff;cursor:pointer"><img src="${asset(c.output)}" style="width:100%;height:100%;object-fit:contain">${selected?'<span style="position:absolute;right:-4px;top:-6px;width:18px;height:18px;border-radius:50%;background:#18864b;color:#fff;font-size:12px;line-height:18px;text-align:center;font-weight:800">✓</span>':''}</button>`}).join(''):'-'}</div></td><td><strong>${esc(x.poi)}</strong>${x.poi_zh?`<br><small class="summary">${esc(x.poi_zh)}</small>`:''}<br><small>${x.candidates.length} 个候选</small></td><td><span class="pill ${x.ai_status}">${esc(aiLabel(x.ai_status))}</span></td><td><span class="pill ${x.decision||'pending'}">${({pending:'未选择',accepted:'已选择',redo:'需重做'})[x.decision||'pending']}</span></td></tr>`).join(''):'<tr><td colspan="4"><div class="empty">当前筛选没有POI。</div></td></tr>';document.querySelectorAll('tr.record').forEach(r=>r.onclick=()=>showRecord(rows.find(x=>x.key===r.dataset.key)));document.querySelectorAll('#records [data-select-candidate]').forEach(b=>b.onclick=e=>{e.stopPropagation();S.current=rows.find(x=>x.key===b.dataset.recordKey);selectCandidate(b.dataset.selectCandidate)});if(rows.length&&!S.current)showRecord(rows[0])}
function showRecord(x){if(S.current?.key!==x.key){S.deleteMode=false;S.deleteTargets=[];S.exportMode=false;S.exportTargets=[]}S.current=x;renderRecords();const searchQuery=[S.data?.display_name,x.poi,x.poi_zh,'真实照片'].filter(Boolean).join(' ');const searchUrl='https://www.bing.com/images/search?q='+encodeURIComponent(searchQuery);const deleting=S.deleteMode,exporting=S.exportMode;const gallery=x.candidates.length?x.candidates.map(c=>{const selected=c.candidate_id===x.selected_candidate;const marked=S.deleteTargets.includes(c.candidate_id);const exportMarked=S.exportTargets.includes(c.candidate_id);const border=deleting?(marked?'#b3261e':'var(--line)'):(exporting?(exportMarked?'#1769e0':'var(--line)'):(selected?'#18864b':'var(--line)'));const title=deleting?'点击标记删除':exporting?'点击选择导出':'点击设为最终版本';return `<button ${deleting?`data-delete-candidate="${c.candidate_id}"`:exporting?`data-export-candidate="${c.candidate_id}"`:`data-select-candidate="${c.candidate_id}"`} title="${title}" style="position:relative;border:3px solid ${border};padding:8px;min-width:0;background:#fff;text-align:left;cursor:pointer">${selected&&!deleting&&!exporting?'<span style="position:absolute;right:7px;top:7px;width:24px;height:24px;border-radius:50%;background:#18864b;color:#fff;font-size:16px;line-height:24px;text-align:center;font-weight:800;z-index:1">✓</span>':''}${marked?'<span style="position:absolute;right:7px;top:7px;width:24px;height:24px;border-radius:50%;background:#b3261e;color:#fff;font-size:17px;line-height:22px;text-align:center;font-weight:900;z-index:1">×</span>':''}${exportMarked?'<span style="position:absolute;right:7px;top:7px;width:24px;height:24px;border-radius:50%;background:#1769e0;color:#fff;font-size:14px;line-height:24px;text-align:center;font-weight:900;z-index:1">↓</span>':''}<div style="height:150px;display:flex;align-items:center;justify-content:center;background:#fafbfc"><img src="${asset(c.output)}" style="max-width:100%;max-height:100%;${marked?'opacity:.58;filter:saturate(.4)':''}"></div><div style="display:flex;justify-content:space-between;align-items:center;margin-top:7px"><strong>组${String(c.group).padStart(2,'0')}</strong><span class="pill ${c.ai_status}">${esc(aiLabel(c.ai_status))}</span></div>${c.reason?`<div class="meta" style="font-size:11px;margin-top:5px">${esc(c.reason)}</div>`:''}<div style="margin-top:6px;color:${marked?'#b3261e':exportMarked?'#1769e0':selected?'#18864b':'var(--muted)'};font-weight:700">${marked?'将删除':exportMarked?'将导出':selected&&!deleting&&!exporting?'已选择':deleting?'点击标记删除':exporting?'点击选择导出':'点击图片设为最终'}</div></button>`}).join(''):'<div class="empty" style="grid-column:1/-1">请先上传并切分候选大图</div>';const deleteControls=deleting?`<div style="padding:10px 12px;background:#fff5f5;border:1px solid #f0b8b3;color:#7f1d1d;margin:10px 0">删除模式：点击候选图标记删除，红色描边和叉表示已选中。删除后这些PNG会从候选文件夹中移除。</div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px"><button class="button" id="cancel-delete">取消</button><button class="button primary" id="confirm-delete" ${S.deleteTargets.length?'':'disabled'} style="background:#b3261e;border-color:#b3261e">确定删除 ${S.deleteTargets.length} 张</button></div>`:'';const exportControls=exporting?`<div style="padding:10px 12px;background:#f2f7ff;border:1px solid #b6cdf5;color:#174ea6;margin:10px 0">单独导出模式：点击候选图标记导出，蓝色描边和箭头表示已选中。导出不会改变最终选择或原候选文件。</div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px"><button class="button" id="cancel-export-single">取消</button><button class="button primary" id="confirm-export-single" ${S.exportTargets.length?'':'disabled'}>确定导出 ${S.exportTargets.length} 张</button></div>`:'';$('#detail').innerHTML=`<h2 style="margin-top:0">${esc(x.poi)}</h2>${x.poi_zh?`<div style="font-size:15px;font-weight:650;color:var(--muted);margin-bottom:10px">${esc(x.poi_zh)}</div>`:''}${deleteControls}${exportControls}<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px">${gallery}</div><div style="margin-top:14px;border-top:1px solid var(--line);padding-top:12px"><div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px"><strong>真实图片参考</strong><button class="button" id="refresh-real-images" style="padding:5px 9px">刷新</button></div><div id="real-images" class="summary">正在获取真实图片…</div></div><label style="display:block;margin-top:14px"><strong>备注</strong><textarea id="note">${esc(x.note||'')}</textarea></label><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="button" id="save-note">保存备注</button><button class="button" id="mark-redo">全部不合适，需要重做</button><button class="button" id="search-real">搜索真实图片</button><button class="button" id="start-export-single" ${x.candidates.length?'':'disabled'}>单独导出</button><button class="button" id="start-delete" ${x.candidates.length?'':'disabled'}>删除</button></div>`;document.querySelectorAll('#detail [data-select-candidate]').forEach(b=>b.onclick=()=>selectCandidate(b.dataset.selectCandidate));document.querySelectorAll('#detail [data-delete-candidate]').forEach(b=>b.onclick=()=>toggleDeleteCandidate(b.dataset.deleteCandidate));document.querySelectorAll('#detail [data-export-candidate]').forEach(b=>b.onclick=()=>toggleExportCandidate(b.dataset.exportCandidate));$('#save-note').onclick=saveNote;$('#mark-redo').onclick=markRedo;$('#search-real').onclick=()=>window.open(searchUrl,'_blank','noopener');$('#refresh-real-images').onclick=()=>loadRealImages(x,searchQuery,searchUrl);$('#start-delete').onclick=startDeleteMode;$('#start-export-single').onclick=startExportMode;const cancel=$('#cancel-delete');if(cancel)cancel.onclick=cancelDeleteMode;const confirm=$('#confirm-delete');if(confirm)confirm.onclick=confirmDeleteCandidates;const cancelExport=$('#cancel-export-single');if(cancelExport)cancelExport.onclick=cancelExportMode;const confirmExport=$('#confirm-export-single');if(confirmExport)confirmExport.onclick=confirmExportCandidates;loadRealImages(x,searchQuery,searchUrl)}
async function reloadRecord(key,message){S.current=null;await loadCity();const record=S.data?.records.find(x=>x.key===key);if(record)showRecord(record);if(message)toast(message)}
async function loadRealImages(record,query,searchUrl){const target=$('#real-images');if(!target)return;const key=record.key;S.realImageKey=key;target.innerHTML='<span class="summary">正在获取真实图片…</span>';try{const result=await api('/api/real-images?q='+encodeURIComponent(query)+'&limit=8');if(S.realImageKey!==key)return;if(!result.images?.length){target.innerHTML=`<div class="summary">${esc(result.error||'没有找到可展示图片')} · <a href="${searchUrl}" target="_blank" rel="noopener">打开搜索页</a></div>`;return}target.innerHTML=`<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px">${result.images.map((url,i)=>`<a href="${esc(url)}" target="_blank" rel="noopener" title="真实图片 ${i+1}" style="height:96px;border:1px solid var(--line);background:#fafbfc;display:flex;align-items:center;justify-content:center;overflow:hidden"><img src="${esc(url)}" loading="lazy" referrerpolicy="no-referrer" style="width:100%;height:100%;object-fit:cover" onerror="this.closest('a').style.display='none'"></a>`).join('')}</div>`}catch(error){if(S.realImageKey!==key)return;target.innerHTML=`<div class="summary">真实图片加载失败：${esc(error.message)} · <a href="${searchUrl}" target="_blank" rel="noopener">打开搜索页</a></div>`}}
async function selectCandidate(candidateId){const key=S.current.key;const result=await post('/api/select-candidate',{destination:S.city,key,candidate_id:candidateId,note:$('#note').value});await reloadRecord(key,result.selected?'已设为最终版本':'已取消选择')}
function startDeleteMode(){S.deleteMode=true;S.deleteTargets=[];showRecord(S.current)}
function cancelDeleteMode(){S.deleteMode=false;S.deleteTargets=[];showRecord(S.current)}
function toggleDeleteCandidate(candidateId){S.deleteTargets=S.deleteTargets.includes(candidateId)?S.deleteTargets.filter(x=>x!==candidateId):[...S.deleteTargets,candidateId];showRecord(S.current)}
async function confirmDeleteCandidates(){if(!S.deleteTargets.length)return;if(!confirm(`确定删除选中的 ${S.deleteTargets.length} 张候选图？这些PNG会从候选文件夹中删除。`))return;const key=S.current.key;const result=await post('/api/delete-candidates',{destination:S.city,key,candidate_ids:S.deleteTargets});S.deleteMode=false;S.deleteTargets=[];await reloadRecord(key,`已删除 ${result.deleted_count} 张候选图`)}
function startExportMode(){S.exportMode=true;S.exportTargets=[];S.deleteMode=false;S.deleteTargets=[];showRecord(S.current)}
function cancelExportMode(){S.exportMode=false;S.exportTargets=[];showRecord(S.current)}
function toggleExportCandidate(candidateId){S.exportTargets=S.exportTargets.includes(candidateId)?S.exportTargets.filter(x=>x!==candidateId):[...S.exportTargets,candidateId];showRecord(S.current)}
async function confirmExportCandidates(){if(!S.exportTargets.length)return;const key=S.current.key;const defaultDir=[S.state?.workspace,'outputs',S.city,'single_exports'].filter(Boolean).join('/');let picked;try{picked=await post('/api/choose-folder',{default_dir:defaultDir})}catch(error){alert('选择保存位置失败：'+error.message);return}if(picked.canceled||!picked.path)return;const result=await post('/api/export-selected-candidates',{destination:S.city,key,candidate_ids:S.exportTargets,export_dir:picked.path});S.exportMode=false;S.exportTargets=[];alert(`已导出 ${result.count} 张图片。\\n保存位置：\\n${result.export_dir}`);await reloadRecord(key,`已单独导出 ${result.count} 张图片`)}
async function markRedo(){const key=S.current.key;await post('/api/mark-redo',{destination:S.city,key,note:$('#note').value});await reloadRecord(key,'已标记需要重做')}
async function saveNote(){const key=S.current.key;await post('/api/decision',{destination:S.city,key,decision:S.current.decision,note:$('#note').value});await reloadRecord(key,'备注已保存')}
async function run(all){let destinations=[S.city],estimated=S.data?.candidate?.estimated_ai_calls||0;if(all){const data=await Promise.all(S.state.destinations.map(x=>api('/api/destination?name='+encodeURIComponent(x))));const ready=data.filter(x=>x.project.ready_to_process);destinations=ready.map(x=>x.name);estimated=ready.reduce((sum,x)=>sum+(x.candidate?.estimated_ai_calls||0),0);if(!destinations.length){alert('目前没有待切分候选组');return}}const ai=$('#ai-review').checked;if(ai&&!confirm(`本次预计调用AI审核 ${estimated} 张大图，是否继续？`))return;await post('/api/run',{destinations,ocr:$('#ocr').checked,ai_review:ai});S._wasRunning=true;await refresh()}
function openUpload(page){if(!S.city)return;S.uploadPage=page;$('#upload-city').value=S.city;$('#upload-modal .modal-head').textContent=`上传 PAGE ${page} 候选大图`;$('#upload-modal').showModal()}
function sourcePreviewItems(){return (S.data?.project?.pages||[]).flatMap(page=>(page.candidate_groups||[]).map(g=>({...g,title:`PAGE ${page.page} · 组${String(g.group).padStart(2,'0')}`}))).sort((a,b)=>a.page-b.page||a.group-b.group)}
function renderSourcePreview(){const items=sourcePreviewItems(),item=items[S.sourcePreviewIndex];if(!item){$('#source-preview-modal').close();$('#source-preview-image').removeAttribute('src');return}$('#source-preview-title').textContent=`候选大图预览 · ${item.title}`;$('#source-preview-image').src=asset(item.source);$('#source-preview-meta').textContent=`${S.sourcePreviewIndex+1}/${items.length} · ${item.source}`;$('#source-preview-prev').disabled=S.sourcePreviewIndex<=0;$('#source-preview-next').disabled=S.sourcePreviewIndex>=items.length-1;$('#delete-source-preview').disabled=!!S.state?.running}
function openSourcePreview(id){const items=sourcePreviewItems();const index=items.findIndex(x=>x.id===id||x.source===id);S.sourcePreviewIndex=Math.max(0,index);renderSourcePreview();$('#source-preview-modal').showModal()}
function moveSourcePreview(delta){const items=sourcePreviewItems();S.sourcePreviewIndex=Math.max(0,Math.min(items.length-1,S.sourcePreviewIndex+delta));renderSourcePreview()}
async function deleteSourcePreview(){const items=sourcePreviewItems(),item=items[S.sourcePreviewIndex];if(!item)return;if(!confirm(`删除 ${item.title}？已引用它的最终选择会被清除。`))return;await post('/api/delete-candidate-group',{destination:S.city,candidate_id:item.id});await loadCity();const updated=sourcePreviewItems();if(!updated.length){$('#source-preview-modal').close();$('#source-preview-image').removeAttribute('src');toast('候选大图已删除');return}S.sourcePreviewIndex=Math.min(S.sourcePreviewIndex,updated.length-1);renderSourcePreview();toast('候选大图已删除')}
async function deleteGroup(id){if(!confirm('删除该候选组？已引用它的最终选择会被清除。'))return;await post('/api/delete-candidate-group',{destination:S.city,candidate_id:id});await loadCity();toast('候选组已移入备份')}
async function exportFinal(){try{const result=await post('/api/export-final',{destination:S.city});await loadCity();toast(`已导出 ${result.count} 张最终图片`)}catch(error){alert(error.message)}}
async function exportReviewBoard(){const preview=window.open('about:blank','_blank');try{const result=await post('/api/export-review-board',{destination:S.city});if(preview)preview.location.href=asset(result.path);toast(`已生成 ${result.poi_count} 个POI的审核总览图，共 ${result.page_count||1} 张`)}catch(error){if(preview)preview.close();alert(error.message)}}
const reviewLabels={all:'全部',pending:'未选择',ai_flags:'AI异常',accepted:'已选择',redo:'需重做'};document.querySelectorAll('.review-toolbar [data-filter]').forEach(b=>{if(b.dataset.filter==='rejected')b.remove();else b.textContent=reviewLabels[b.dataset.filter]||b.textContent});const boardButton=document.createElement('button');boardButton.id='export-review-board';boardButton.className='button';boardButton.textContent='导出审核总览图';boardButton.style.marginLeft='auto';boardButton.onclick=exportReviewBoard;$('.review-toolbar').appendChild(boardButton);const exportButton=document.createElement('button');exportButton.id='export-final';exportButton.className='button primary';exportButton.textContent='导出最终图片';exportButton.onclick=exportFinal;$('.review-toolbar').appendChild(exportButton);$('#open-upload-images').textContent='上传当前PAGE候选';const replaceControl=document.querySelector('#upload-form [name=replace]');if(replaceControl)replaceControl.closest('label').remove();const uploadHint=document.querySelector('#upload-form .hint');if(uploadHint)uploadHint.textContent='所选图片全部加入当前PAGE，自动分配候选组号；每个PAGE最多10组。';$('#copy-prompt').remove();const promptActions=document.createElement('div');promptActions.style.cssText='display:flex;align-items:center;gap:8px;flex-wrap:wrap';promptActions.innerHTML='<div style="display:flex;gap:2px;background:#f0f2f5;padding:2px;border-radius:5px"><button class="filter prompt-mode active" data-prompt-variant="original">原版 Prompt</button><button class="filter prompt-mode" data-prompt-variant="iconic">Prompt_图标化</button><button class="filter prompt-mode" data-prompt-variant="identity">Prompt_本体强化</button></div>';const copyPrompt=document.createElement('button');copyPrompt.id='copy-prompt';copyPrompt.className='button primary';copyPrompt.disabled=true;copyPrompt.textContent='复制 PAGE Prompt';promptActions.appendChild(copyPrompt);$('.prompt-head').appendChild(promptActions);document.querySelectorAll('[data-prompt-variant]').forEach(b=>b.onclick=()=>setPromptVariant(b.dataset.promptVariant));document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===b.dataset.tab))});document.querySelectorAll('.filter:not(.prompt-mode)').forEach(b=>b.onclick=()=>{S.filter=b.dataset.filter;S.current=null;document.querySelectorAll('.filter:not(.prompt-mode)').forEach(x=>x.classList.toggle('active',x===b));renderRecords()});$('#set-workspace').onclick=async()=>{await post('/api/workspace',{path:$('#workspace').value});S.city=null;await refresh()};$('#run-current').onclick=()=>run(false);$('#run-all').onclick=()=>run(true);$('#open-output').onclick=()=>post('/api/open-output',{destination:S.city});$('#copy-prompt').onclick=async()=>{const text=$('#prompt-text').value;if(!text)return;await navigator.clipboard.writeText(text);toast(`PAGE ${S.page} ${promptVariantLabel()} 已复制`)};
$('#open-import').onclick=()=>$('#import-modal').showModal();$('#cancel-import').onclick=()=>$('#import-modal').close();$('#close-source-preview').onclick=()=>{$('#source-preview-modal').close();$('#source-preview-image').removeAttribute('src')};$('#source-preview-prev').onclick=()=>moveSourcePreview(-1);$('#source-preview-next').onclick=()=>moveSourcePreview(1);$('#delete-source-preview').onclick=deleteSourcePreview;document.addEventListener('keydown',e=>{if(!$('#source-preview-modal').open)return;if(e.key==='ArrowLeft')moveSourcePreview(-1);if(e.key==='ArrowRight')moveSourcePreview(1)});$('#import-form').onsubmit=async e=>{e.preventDefault();const button=$('#submit-import');button.disabled=true;button.textContent='正在建立城市项目…';try{const response=await fetch('/api/import-table',{method:'POST',body:new FormData(e.target)});const result=await response.json();if(!response.ok)throw Error(result.error||'导入失败');$('#import-modal').close();e.target.reset();S.city=result.created[0]?.id||S.city;await refresh();if(S.city)await selectCity(S.city);toast(`已建立 ${result.city_count} 个城市、${result.total_pois} 个POI`);if(result.skipped.length)alert(`以下同名城市已跳过：${result.skipped.join('、')}`)}catch(error){alert(error.message)}finally{button.disabled=false;button.textContent='导入并生成Prompt'}};
$('#open-upload-images').onclick=()=>openUpload(S.page);$('#cancel-upload').onclick=()=>$('#upload-modal').close();$('#upload-form').onsubmit=async e=>{e.preventDefault();const button=$('#submit-upload');button.disabled=true;button.textContent='正在上传…';try{const form=new FormData(e.target);form.append('page',String(S.uploadPage||S.page));const response=await fetch('/api/upload-images',{method:'POST',body:form});const result=await response.json();if(!response.ok)throw Error(result.error||'上传失败');$('#upload-modal').close();e.target.reset();await loadCity();toast(`PAGE ${result.page} 已加入 ${result.saved.length} 组候选`)}catch(error){alert(error.message)}finally{button.disabled=false;button.textContent='上传图片'}};refresh();setInterval(()=>{if(S.state?.running)refresh()},1200);
</script></body></html>"""


def create_server(state: StudioState, host="127.0.0.1", port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def send_body(self, body: bytes, content_type: str, status=HTTPStatus.OK):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, value, status=HTTPStatus.OK):
            self.send_body(_json_bytes(value), "application/json; charset=utf-8", status)

        def read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        def read_form(self):
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 600 * 1024 * 1024:
                raise ValueError("上传内容超过 600MB 限制")
            return cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": str(content_length),
                },
                keep_blank_values=True,
            )

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            try:
                if parsed.path == "/":
                    self.send_body(HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif parsed.path == "/api/state":
                    self.send_json(state.snapshot())
                elif parsed.path == "/api/destination":
                    self.send_json(state.destination_data(query.get("name", [""])[0]))
                elif parsed.path == "/api/real-images":
                    self.send_json(search_real_images(
                        query.get("q", [""])[0],
                        int(query.get("limit", ["8"])[0] or 8),
                    ))
                elif parsed.path == "/asset":
                    asset = state.asset(query.get("path", [""])[0])
                    mime = "image/png" if asset.suffix.lower() == ".png" else "image/jpeg"
                    self.send_body(asset.read_bytes(), mime)
                else:
                    self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

        def do_POST(self):
            try:
                if self.path == "/api/import-table":
                    form = self.read_form()
                    table_upload = form["table"] if "table" in form else None
                    result = state.import_table(
                        table_upload,
                        str(form.getfirst("replace", "")).lower() in ("1", "true", "yes", "on"),
                    )
                    self.send_json({"ok": True, **result})
                    return
                if self.path == "/api/upload-images":
                    form = self.read_form()
                    image_field = form["images"] if "images" in form else []
                    image_uploads = image_field if isinstance(image_field, list) else [image_field]
                    result = state.upload_city_images(
                        str(form.getfirst("city", "")),
                        int(form.getfirst("page", "0") or 0),
                        image_uploads,
                    )
                    self.send_json({"ok": True, **result})
                    return
                if self.path == "/api/import":
                    form = self.read_form()
                    table_upload = form["table"] if "table" in form else None
                    image_field = form["images"] if "images" in form else []
                    image_uploads = image_field if isinstance(image_field, list) else [image_field]
                    result = state.import_assets(
                        str(form.getfirst("city", "")),
                        table_upload,
                        image_uploads,
                        str(form.getfirst("replace", "")).lower() in ("1", "true", "yes", "on"),
                    )
                    self.send_json({"ok": True, **result})
                    return
                data = self.read_json()
                if self.path == "/api/workspace":
                    state.set_workspace(str(data.get("path", "")))
                elif self.path == "/api/run":
                    state.run(data.get("destinations", []), data.get("ocr", True), data.get("ai_review", False))
                elif self.path == "/api/decision":
                    state.save_decision(
                        str(data.get("destination", "")), str(data.get("key", "")),
                        str(data.get("decision", "pending")), str(data.get("note", "")),
                    )
                elif self.path == "/api/select-candidate":
                    result = state.select_candidate(
                        str(data.get("destination", "")), str(data.get("key", "")),
                        str(data.get("candidate_id", "")), str(data.get("note", "")),
                    )
                    self.send_json({"ok": True, **result})
                    return
                elif self.path == "/api/mark-redo":
                    result = candidate_manager.mark_redo(
                        Path(splitter.OUTPUTS_DIR) / str(data.get("destination", "")),
                        str(data.get("destination", "")), str(data.get("key", "")),
                        str(data.get("note", "")),
                    )
                    self.send_json({"ok": True, **result})
                    return
                elif self.path == "/api/delete-candidate-group":
                    result = state.delete_candidate_group(
                        str(data.get("destination", "")), str(data.get("candidate_id", "")),
                    )
                    self.send_json({"ok": True, **result})
                    return
                elif self.path == "/api/delete-candidates":
                    result = state.delete_candidates(
                        str(data.get("destination", "")),
                        str(data.get("key", "")),
                        data.get("candidate_ids", []),
                    )
                    self.send_json({"ok": True, **result})
                    return
                elif self.path == "/api/export-selected-candidates":
                    result = state.export_selected_candidates(
                        str(data.get("destination", "")),
                        str(data.get("key", "")),
                        data.get("candidate_ids", []),
                        str(data.get("export_dir", "")),
                    )
                    self.send_json({"ok": True, **result})
                    return
                elif self.path == "/api/choose-folder":
                    result = state.choose_folder(str(data.get("default_dir", "")))
                    self.send_json({"ok": True, **result})
                    return
                elif self.path == "/api/export-final":
                    result = state.export_final(str(data.get("destination", "")))
                    self.send_json({"ok": True, **result})
                    return
                elif self.path == "/api/export-review-board":
                    result = state.export_review_board(str(data.get("destination", "")))
                    self.send_json({"ok": True, **result})
                    return
                elif self.path == "/api/open-output":
                    state.open_output(data.get("destination"))
                else:
                    self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json({"ok": True})
            except Exception as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    return ThreadingHTTPServer((host, port), Handler)


def main(open_browser: bool = True):
    state = StudioState()
    server = create_server(state)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"{APP_NAME}: {url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
