#!/usr/bin/env python3
"""Local browser workspace for POI icon splitting and human evaluation."""

from __future__ import annotations

import contextlib
import cgi
import io
import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import reviewer
import sheet_importer
import splitter


APP_NAME = "POI Icon Studio"
SOURCE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


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
        result = {
            "name": name,
            "input": {
                "batch_count": len(batches),
                "poi_count": len(specs),
                "described_count": sum(1 for x in specs if x.get("description")),
                "batches": [os.path.basename(x) for x in batches],
            },
            "records": [],
            "summary": {"total": 0, "pending": 0, "accepted": 0, "rejected": 0, "redo": 0},
        }

        manifest_path = Path(splitter.OUTPUTS_DIR) / name / "manifest.json"
        if not manifest_path.is_file():
            return result
        manual, manual_path = reviewer.ensure_full_manual_review(str(manifest_path))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ai_details = {}
        ai_path = manifest.get("review", {}).get("ai_review")
        if ai_path and Path(ai_path).is_file():
            ai_report = json.loads(Path(ai_path).read_text(encoding="utf-8"))
            for batch in ai_report.get("batches", []):
                for item in batch.get("items", []):
                    ai_details[f"{batch['batch']}:{item['index']}"] = item

        for item in manual.get("items", []):
            detail = ai_details.get(item["key"], {})
            record = {
                **item,
                "description": detail.get("description", ""),
                "reason": detail.get("reason", ""),
                "candidate": detail.get("candidate", ""),
            }
            result["records"].append(record)
        decisions = [x.get("decision", "pending") for x in result["records"]]
        result["summary"] = {
            "total": len(decisions),
            "pending": decisions.count("pending"),
            "accepted": decisions.count("accepted"),
            "rejected": decisions.count("rejected"),
            "redo": decisions.count("redo"),
        }
        result["manual_path"] = manual_path
        result["manifest_path"] = str(manifest_path)
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
                    result = splitter.process_destination(
                        name,
                        os.path.join(splitter.INPUTS_DIR, name),
                        splitter.OUTPUTS_DIR,
                        review_enabled=ai_review,
                    )
                    results.append({
                        "destination": name,
                        "success": result.get("success", False),
                        "error": result.get("error", ""),
                    })
                    if result.get("success"):
                        reviewer.ensure_full_manual_review(result["manifest"])
        except Exception:
            with self.lock:
                self.last_error = traceback.format_exc()
                self.logs += "\n" + self.last_error
        finally:
            with self.lock:
                self.last_results = results
                self.running = False

    def save_decision(self, destination: str, key: str, decision: str, note: str):
        data = self.destination_data(destination)
        manual_path = data.get("manual_path")
        manifest_path = data.get("manifest_path")
        if not manual_path or not manifest_path:
            raise ValueError("该城市尚未生成切图结果")
        with open(manual_path, "r", encoding="utf-8") as f:
            manual = json.load(f)
        job = {"manual": manual, "manual_path": manual_path, "manifest_path": manifest_path}
        reviewer.save_manual_decision(job, key, decision, note)

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
                json.dump({"city": matched_city, "pois": pois}, output, ensure_ascii=False, indent=2)

        return {
            "city": folder_name,
            "source_city": matched_city,
            "poi_count": len(pois),
            "batch_count": expected_batches,
            "backup": str(backup) if backup else None,
        }

    def asset(self, path: str) -> Path:
        target = Path(path).expanduser().resolve()
        allowed = (self.workspace / "outputs").resolve()
        try:
            target.relative_to(allowed)
        except ValueError as exc:
            raise PermissionError("asset path is outside outputs") from exc
        if not target.is_file():
            raise FileNotFoundError(path)
        return target


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>POI Icon Studio</title><style>
:root{--bg:#f4f5f7;--panel:#fff;--sidebar:#20242b;--text:#20242b;--muted:#68707c;--line:#d9dde3;--accent:#1769e0;--green:#18794e;--amber:#9a6700;--red:#b3261e}*{box-sizing:border-box}body{margin:0;font:14px -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif;color:var(--text);background:var(--bg);height:100vh;overflow:hidden}button,input,textarea{font:inherit}.app{display:grid;grid-template-columns:248px 1fr;height:100vh}.sidebar{background:var(--sidebar);color:#f7f8fa;padding:22px 14px;display:flex;flex-direction:column;min-width:0}.brand{font-size:20px;font-weight:750;line-height:1.1;padding:0 8px 20px}.label{font-size:11px;font-weight:700;color:#aeb5c0;text-transform:uppercase;padding:8px}.workspace{display:flex;gap:6px;padding:0 6px 12px}.workspace input{min-width:0;flex:1;background:#343a44;color:#fff;border:1px solid #4b535f;border-radius:5px;padding:8px}.iconbtn{border:0;border-radius:5px;background:#343a44;color:#fff;padding:8px 10px;cursor:pointer}.cities{list-style:none;margin:0;padding:0;overflow:auto;flex:1}.cities button{width:100%;text-align:left;border:0;background:transparent;color:#e7eaf0;padding:11px 12px;border-radius:5px;cursor:pointer}.cities button:hover{background:#2c323b}.cities button.active{background:var(--accent);color:#fff;font-weight:650}.sidefoot{font-size:11px;color:#89919d;padding:12px 8px 0;overflow-wrap:anywhere}.main{min-width:0;display:grid;grid-template-rows:62px 46px 1fr}.topbar{display:flex;align-items:center;justify-content:space-between;padding:0 22px;background:#fff;border-bottom:1px solid var(--line)}.topbar h1{font-size:16px;margin:0}.top-actions{display:flex;gap:8px}.button{border:1px solid #aeb4bd;background:#fff;border-radius:5px;padding:8px 13px;cursor:pointer}.button:hover{background:#f2f4f7}.button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:650}.button:disabled{opacity:.45;cursor:not-allowed}.tabs{display:flex;align-items:end;padding:0 20px;background:#fff;border-bottom:1px solid var(--line)}.tab{border:0;background:transparent;padding:12px 16px 10px;cursor:pointer;border-bottom:3px solid transparent}.tab.active{border-color:var(--accent);color:var(--accent);font-weight:700}.view{display:none;padding:16px 20px;min-height:0;overflow:auto}.view.active{display:block}.run-layout{display:grid;grid-template-rows:auto auto minmax(280px,1fr);gap:12px;height:100%}.band{background:#fff;border:1px solid var(--line);padding:14px 16px}.options{display:flex;align-items:center;gap:22px}.options strong{font-size:15px;margin-right:8px}.switch{display:flex;align-items:center;gap:8px}.run-actions{margin-left:auto;display:flex;gap:8px}.summary{color:var(--muted);line-height:1.6}.log{margin:0;background:#171a1f;color:#dce2eb;padding:14px;overflow:auto;white-space:pre-wrap;font:12px Menlo,monospace;min-height:280px}.review-toolbar{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid var(--line);padding:10px 14px;margin-bottom:12px}.stats{font-weight:700;margin-right:12px}.filter{border:0;background:#f0f2f5;border-radius:5px;padding:7px 10px;cursor:pointer}.filter.active{background:#dce9fc;color:#1155b6;font-weight:650}.review-layout{display:grid;grid-template-columns:minmax(480px,1.35fr) minmax(330px,.65fr);height:calc(100vh - 198px);background:#fff;border:1px solid var(--line)}.table-wrap{overflow:auto;border-right:1px solid var(--line)}table{border-collapse:collapse;width:100%}th{position:sticky;top:0;background:#f7f8fa;text-align:left;padding:9px;border-bottom:1px solid var(--line);font-size:12px}td{padding:8px;border-bottom:1px solid #eceef1}tr.record{cursor:pointer}tr.record:hover{background:#f6f9fd}tr.record.active{background:#e8f1ff}.thumb{width:46px;height:46px;object-fit:contain;background:#fff;border:1px solid #eee}.pill{font-size:11px;font-weight:700}.PASS,.accepted{color:var(--green)}.REVIEW,.redo{color:var(--amber)}.FAIL,.REVIEW_ERROR,.rejected{color:var(--red)}.NOT_RUN,.pending{color:var(--muted)}.detail{padding:20px;overflow:auto}.preview{display:flex;align-items:center;justify-content:center;width:100%;height:310px;background:#fafbfc;border:1px solid var(--line)}.preview img{max-width:100%;max-height:100%;image-rendering:auto}.detail h2{font-size:19px;margin:16px 0 6px;overflow-wrap:anywhere}.meta{color:var(--muted);line-height:1.55;white-space:pre-wrap}.decision{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:12px 0}.decision button{border:1px solid #aeb4bd;background:#fff;padding:9px 4px;border-radius:5px;cursor:pointer}.decision button.active{background:#dce9fc;border-color:var(--accent);color:#1155b6;font-weight:700}.detail textarea{width:100%;min-height:82px;resize:vertical;border:1px solid #aeb4bd;padding:8px;border-radius:5px;margin:6px 0 10px}.empty{padding:50px;text-align:center;color:var(--muted)}dialog{border:1px solid var(--line);border-radius:7px;padding:0;width:min(560px,calc(100vw - 32px));box-shadow:0 18px 60px #0005}dialog::backdrop{background:#0007}.modal-head{padding:16px 20px;border-bottom:1px solid var(--line);font-size:17px;font-weight:750}.modal-body{padding:18px 20px}.field{display:block;margin-bottom:15px}.field span{display:block;font-weight:650;margin-bottom:6px}.field input[type=text],.field input[type=file]{width:100%;border:1px solid #aeb4bd;border-radius:5px;padding:9px}.hint{font-size:12px;color:var(--muted);line-height:1.5}.modal-actions{display:flex;justify-content:flex-end;gap:8px;padding:12px 20px;border-top:1px solid var(--line)}.toast{position:fixed;right:20px;bottom:20px;background:#20242b;color:#fff;padding:10px 14px;border-radius:5px;opacity:0;pointer-events:none;transition:.2s}.toast.show{opacity:1}@media(max-width:900px){.app{grid-template-columns:200px 1fr}.review-layout{grid-template-columns:1fr}.detail{display:none}.options{flex-wrap:wrap}.run-actions{margin-left:0}}
</style></head><body><div class="app"><aside class="sidebar"><div class="brand">POI ICON<br>STUDIO</div><div class="label">工作目录</div><div class="workspace"><input id="workspace"><button class="iconbtn" id="set-workspace" title="应用目录">设置</button></div><div class="label">城市</div><ul class="cities" id="cities"></ul><div class="sidefoot" id="sidefoot"></div></aside><main class="main"><header class="topbar"><h1 id="title">请选择城市</h1><div class="top-actions"><button class="button primary" id="open-import">导入素材</button><button class="button" id="open-output">打开输出目录</button></div></header><nav class="tabs"><button class="tab active" data-tab="run">运行与日志</button><button class="tab" data-tab="review">人工评估</button></nav><section class="view active" id="run"><div class="run-layout"><div class="band options"><strong>处理选项</strong><label class="switch"><input type="checkbox" id="ocr" checked> OCR 去文字</label><label class="switch"><input type="checkbox" id="ai-review"> AI 整图初审（使用 Plus 额度）</label><div class="run-actions"><button class="button" id="run-all">运行全部</button><button class="button primary" id="run-current">运行当前城市</button></div></div><div class="band"><strong>输入检查</strong><div class="summary" id="input-summary">请选择城市</div></div><pre class="log" id="log">等待任务…</pre></div></section><section class="view" id="review"><div class="review-toolbar"><span class="stats" id="stats">暂无评估数据</span><button class="filter" data-filter="all">全部</button><button class="filter active" data-filter="pending">待处理</button><button class="filter" data-filter="ai_flags">AI异常</button><button class="filter" data-filter="accepted">已通过</button><button class="filter" data-filter="redo">需重做</button><button class="filter" data-filter="rejected">已驳回</button></div><div class="review-layout"><div class="table-wrap"><table><thead><tr><th>预览</th><th>POI</th><th>AI</th><th>人工结论</th></tr></thead><tbody id="records"></tbody></table></div><aside class="detail" id="detail"><div class="empty">选择一张图片开始评估</div></aside></div></section></main></div><dialog id="import-modal"><form id="import-form"><div class="modal-head">导入外部素材</div><div class="modal-body"><label class="field"><span>城市名称</span><input type="text" name="city" required placeholder="例如 Seoul 或 首尔"></label><label class="field"><span>POI 表格</span><input type="file" name="table" accept=".xlsx,.csv" required></label><label class="field"><span>4×4 网格图片</span><input type="file" name="images" accept="image/png,image/jpeg" multiple required></label><p class="hint">图片按文件名自然顺序保存为 batch1、batch2……系统会校验图片数量与POI页数是否一致。</p><label class="switch"><input type="checkbox" name="replace"> 同名城市存在时，备份旧输入并替换</label></div><div class="modal-actions"><button type="button" class="button" id="cancel-import">取消</button><button type="submit" class="button primary" id="submit-import">上传并导入</button></div></form></dialog><div class="toast" id="toast"></div>
<script>
const S={state:null,city:null,data:null,filter:'pending',current:null,decision:'pending'};const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const api=async(path,opt={})=>{const r=await fetch(path,opt);const j=await r.json();if(!r.ok)throw Error(j.error||'请求失败');return j};const post=(path,data)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});function toast(t){const e=$('#toast');e.textContent=t;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),1600)}function asset(path){return path?'/asset?path='+encodeURIComponent(path):''}
async function refresh(){S.state=await api('/api/state');$('#workspace').value=S.state.workspace;$('#sidefoot').textContent=S.state.workspace;const list=$('#cities');list.innerHTML=S.state.destinations.map(x=>`<li><button class="${x===S.city?'active':''}" data-city="${esc(x)}">${esc(x)}</button></li>`).join('');list.querySelectorAll('button').forEach(b=>b.onclick=()=>selectCity(b.dataset.city));if(!S.city&&S.state.destinations.length)await selectCity(S.state.destinations[0]);$('#log').textContent=S.state.logs||'等待任务…';$('#log').scrollTop=$('#log').scrollHeight;document.querySelectorAll('#run-current,#run-all').forEach(b=>b.disabled=S.state.running);if(S.state.running)setTimeout(refresh,1000);else if(S._wasRunning){S._wasRunning=false;await loadCity();toast('处理完成');}S._wasRunning=S.state.running}
async function selectCity(name){S.city=name;document.querySelectorAll('#cities button').forEach(b=>b.classList.toggle('active',b.dataset.city===name));$('#title').textContent=name;await loadCity()}
async function loadCity(){if(!S.city)return;try{S.data=await api('/api/destination?name='+encodeURIComponent(S.city));const i=S.data.input;$('#input-summary').textContent=`${i.batch_count} 张网格大图 · ${i.poi_count} 个 POI · ${i.described_count} 个包含视觉描述`;renderRecords()}catch(e){$('#input-summary').textContent='输入有误：'+e.message;S.data=null;renderRecords()}}
function filtered(){if(!S.data)return[];const r=S.data.records||[];if(S.filter==='all')return r;if(S.filter==='ai_flags')return r.filter(x=>!['PASS','NOT_RUN'].includes(x.ai_status));return r.filter(x=>(x.decision||'pending')===S.filter)}
function renderRecords(){const d=S.data?.summary||{total:0,pending:0,accepted:0,redo:0,rejected:0};$('#stats').textContent=`共 ${d.total} 张 · 待处理 ${d.pending} · 通过 ${d.accepted} · 重做 ${d.redo} · 驳回 ${d.rejected}`;const rows=filtered();$('#records').innerHTML=rows.length?rows.map(x=>`<tr class="record ${S.current?.key===x.key?'active':''}" data-key="${x.key}"><td><img class="thumb" src="${asset(x.output)}"></td><td>${esc(x.poi)}</td><td><span class="pill ${x.ai_status}">${esc(x.ai_status)}</span></td><td><span class="pill ${x.decision||'pending'}">${({pending:'待处理',accepted:'通过',rejected:'驳回',redo:'重做'})[x.decision||'pending']}</span></td></tr>`).join(''):'<tr><td colspan="4"><div class="empty">当前筛选条件下没有图片</div></td></tr>';document.querySelectorAll('tr.record').forEach(r=>r.onclick=()=>showRecord(rows.find(x=>x.key===r.dataset.key)));if(rows.length&&!S.current)showRecord(rows[0])}
function showRecord(x){S.current=x;S.decision=x.decision||'pending';renderRecords();const conf=x.confidence==null?'-':Math.round(x.confidence*100)+'%';$('#detail').innerHTML=`<div class="preview">${x.output?`<img src="${asset(x.output)}">`:'图片不存在'}</div><h2>${esc(x.poi)}</h2><div class="meta">batch${x.batch} · 第 ${x.index} 格\nAI：${esc(x.ai_status)} · 置信度 ${conf}${x.reason?'\n'+esc(x.reason):''}${x.description?'\n预期特征：'+esc(x.description):''}</div><div class="decision">${[['accepted','通过'],['rejected','驳回'],['redo','重做'],['pending','待定']].map(v=>`<button data-decision="${v[0]}" class="${S.decision===v[0]?'active':''}">${v[1]}</button>`).join('')}</div><label><strong>备注</strong><textarea id="note">${esc(x.note||'')}</textarea></label><button class="button primary" id="save">保存并查看下一张</button>`;document.querySelectorAll('[data-decision]').forEach(b=>b.onclick=()=>{S.decision=b.dataset.decision;document.querySelectorAll('[data-decision]').forEach(v=>v.classList.toggle('active',v===b))});$('#save').onclick=saveDecision}
async function saveDecision(){if(!S.current)return;await post('/api/decision',{destination:S.city,key:S.current.key,decision:S.decision,note:$('#note').value});const old=filtered(),idx=old.findIndex(x=>x.key===S.current.key);S.current=null;await loadCity();const next=filtered();if(next.length)showRecord(next[Math.min(idx,next.length-1)]);toast('评估已保存')}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===b.dataset.tab))});document.querySelectorAll('.filter').forEach(b=>b.onclick=()=>{S.filter=b.dataset.filter;S.current=null;document.querySelectorAll('.filter').forEach(x=>x.classList.toggle('active',x===b));renderRecords()});$('#set-workspace').onclick=async()=>{await post('/api/workspace',{path:$('#workspace').value});S.city=null;await refresh()};$('#run-current').onclick=()=>run(false);$('#run-all').onclick=()=>run(true);async function run(all){if(!S.city&&!all)return;await post('/api/run',{destinations:all?S.state.destinations:[S.city],ocr:$('#ocr').checked,ai_review:$('#ai-review').checked});S._wasRunning=true;await refresh()}$('#open-output').onclick=()=>post('/api/open-output',{destination:S.city});$('#open-import').onclick=()=>$('#import-modal').showModal();$('#cancel-import').onclick=()=>$('#import-modal').close();$('#import-form').onsubmit=async e=>{e.preventDefault();const button=$('#submit-import');button.disabled=true;button.textContent='正在导入…';try{const response=await fetch('/api/import',{method:'POST',body:new FormData(e.target)});const result=await response.json();if(!response.ok)throw Error(result.error||'导入失败');$('#import-modal').close();e.target.reset();S.city=result.city;await refresh();await selectCity(result.city);toast(`已导入 ${result.poi_count} 个 POI 和 ${result.batch_count} 张图片`)}catch(error){alert(error.message)}finally{button.disabled=false;button.textContent='上传并导入'}};refresh();setInterval(()=>{if(S.state?.running)refresh()},1200);
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
                if self.path == "/api/import":
                    content_length = int(self.headers.get("Content-Length", "0"))
                    if content_length > 600 * 1024 * 1024:
                        raise ValueError("上传内容超过 600MB 限制")
                    form = cgi.FieldStorage(
                        fp=self.rfile,
                        headers=self.headers,
                        environ={
                            "REQUEST_METHOD": "POST",
                            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                            "CONTENT_LENGTH": str(content_length),
                        },
                        keep_blank_values=True,
                    )
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
