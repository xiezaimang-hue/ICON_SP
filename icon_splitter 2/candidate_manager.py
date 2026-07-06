#!/usr/bin/env python3
"""Candidate-sheet storage, processing, selection, and final export."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import reviewer
import splitter


MAX_GROUPS_PER_PAGE = 10


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except Exception:
        return default


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _group_id(page: int, group: int) -> str:
    return f"p{page:02d}_g{group:02d}"


def source_index_path(input_dir: Path) -> Path:
    return input_dir / "candidates.json"


def candidate_manifest_path(output_dir: Path) -> Path:
    return output_dir / "candidate_manifest.json"


def selections_path(output_dir: Path) -> Path:
    return output_dir / "selections.json"


def ensure_source_index(input_dir: Path, project: dict) -> dict:
    """Load source groups and register legacy batchN files as group 1."""
    path = source_index_path(input_dir)
    index = _read_json(path, {"version": 1, "pages": {}})
    pages = index.setdefault("pages", {})
    changed = False
    for page in project.get("pages", []):
        page_number = int(page["page"])
        key = str(page_number)
        groups = pages.setdefault(key, [])
        known_sources = {str(Path(x.get("source", "")).resolve()) for x in groups}
        legacy = next(
            (
                candidate
                for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG")
                if (candidate := input_dir / f"batch{page_number}{ext}").is_file()
            ),
            None,
        )
        if legacy and str(legacy.resolve()) not in known_sources:
            used = {int(x.get("group", 0)) for x in groups}
            group_number = 1 if 1 not in used else next(
                (number for number in range(2, MAX_GROUPS_PER_PAGE + 1) if number not in used),
                0,
            )
            if group_number:
                groups.append({
                    "id": _group_id(page_number, group_number),
                    "page": page_number,
                    "group": group_number,
                    "source": str(legacy.resolve()),
                    "original_name": legacy.name,
                    "uploaded_at": "",
                    "legacy": True,
                })
                groups.sort(key=lambda item: int(item["group"]))
                changed = True
    if changed or not path.is_file():
        _write_json(path, index)
    return index


def add_uploads(input_dir: Path, project: dict, page: int, uploads: list) -> list[dict]:
    valid_pages = {int(item["page"]) for item in project.get("pages", [])}
    if page not in valid_pages:
        raise ValueError("请选择有效PAGE")
    if not uploads:
        raise ValueError("请选择至少一张候选大图")
    index = ensure_source_index(input_dir, project)
    groups = index["pages"].setdefault(str(page), [])
    if len(groups) + len(uploads) > MAX_GROUPS_PER_PAGE:
        remaining = MAX_GROUPS_PER_PAGE - len(groups)
        raise ValueError(f"PAGE {page} 最多10组，当前还可上传 {remaining} 组")
    allowed = {".png", ".jpg", ".jpeg"}
    used = {int(item["group"]) for item in groups}
    available = [number for number in range(1, MAX_GROUPS_PER_PAGE + 1) if number not in used]
    saved = []
    target_dir = input_dir / "candidate_sources" / f"page_{page:02d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    for upload, group_number in zip(uploads, available):
        filename = os.path.basename(getattr(upload, "filename", ""))
        suffix = Path(filename).suffix.lower()
        if suffix not in allowed:
            raise ValueError(f"不支持的图片格式：{filename}")
        target = target_dir / f"group_{group_number:02d}{suffix}"
        with open(target, "wb") as output:
            shutil.copyfileobj(upload.file, output)
        item = {
            "id": _group_id(page, group_number),
            "page": page,
            "group": group_number,
            "source": str(target.resolve()),
            "original_name": filename,
            "uploaded_at": _now(),
            "legacy": False,
        }
        groups.append(item)
        saved.append(item)
    groups.sort(key=lambda item: int(item["group"]))
    _write_json(source_index_path(input_dir), index)
    return saved


def load_manifest(output_dir: Path, destination: str) -> dict:
    return _read_json(candidate_manifest_path(output_dir), {
        "version": 1,
        "destination": destination,
        "updated_at": "",
        "groups": {},
    })


def load_selections(output_dir: Path, destination: str) -> dict:
    return _read_json(selections_path(output_dir), {
        "version": 1,
        "destination": destination,
        "updated_at": "",
        "items": {},
    })


def pending_groups(input_dir: Path, output_dir: Path, project: dict, destination: str) -> list[dict]:
    index = ensure_source_index(input_dir, project)
    manifest = load_manifest(output_dir, destination)
    result = []
    for groups in index.get("pages", {}).values():
        for group in groups:
            state = manifest.get("groups", {}).get(group["id"], {})
            if state.get("status") != "processed":
                result.append(group)
    return sorted(result, key=lambda item: (int(item["page"]), int(item["group"])))


def process_pending_groups(
    destination: str,
    input_dir: Path,
    output_dir: Path,
    project: dict,
    *,
    ai_review: bool = False,
    log: Callable[[str], None] = print,
) -> dict:
    index = ensure_source_index(input_dir, project)
    manifest = load_manifest(output_dir, destination)
    pages = {int(item["page"]): item for item in project.get("pages", [])}
    pending = pending_groups(input_dir, output_dir, project, destination)
    all_source_groups = [
        group
        for groups in index.get("pages", {}).values()
        for group in groups
    ]
    skipped = sum(
        1
        for group in all_source_groups
        if manifest.get("groups", {}).get(group["id"], {}).get("status") == "processed"
    )
    if not pending:
        if skipped:
            log(f"[候选切图] 已有 {skipped} 组完成切图，本次无新增待切组。")
        return {"success": True, "processed": 0, "failed": 0, "skipped": skipped}

    processed = 0
    failed = 0
    if skipped:
        log(f"[候选切图] 跳过 {skipped} 组已切候选，仅处理 {len(pending)} 组新增/失败候选。")
    for group in pending:
        page_number = int(group["page"])
        page = pages.get(page_number)
        if not page:
            continue
        specs = page.get("poi_specs", [])
        group_id = group["id"]
        source = group["source"]
        target_dir = output_dir / "candidates" / f"page_{page_number:02d}" / f"group_{int(group['group']):02d}"
        labels = [f"cell_{index:02d}" for index in range(1, len(specs) + 1)]
        log(f"\n[候选切图] PAGE {page_number} · 组{int(group['group']):02d}")
        ok, error, mapping = splitter.split_one_grid(
            source, labels, str(target_dir), max_output_size=0, log=log
        )
        record = {
            **group,
            "status": "processed" if ok else "failed",
            "processed_at": _now(),
            "error": error,
            "ai_status": "NOT_RUN",
            "ai_summary": "",
            "items": [],
        }
        if ok:
            ai_items = {}
            if ai_review:
                ai_result = reviewer.review_batch_with_codex(
                    source, destination, page_number, specs, log=log
                )
                record["ai_status"] = ai_result["status"]
                record["ai_summary"] = ai_result.get("summary", "")
                record["ai_reviewed_at"] = _now()
                ai_items = {int(item["index"]): item for item in ai_result.get("items", [])}
            for item_index, spec in enumerate(specs, 1):
                ai_item = ai_items.get(item_index, {})
                record["items"].append({
                    "key": f"{page_number}:{item_index}",
                    "index": item_index,
                    "poi": spec["name"],
                    "poi_zh": spec.get("name_zh", ""),
                    "output": mapping.get(f"cell_{item_index:02d}", ""),
                    "ai_status": ai_item.get("status", "NOT_RUN"),
                    "confidence": ai_item.get("confidence"),
                    "issues": ai_item.get("issues", []),
                    "reason": ai_item.get("reason", ""),
                })
            processed += 1
        else:
            failed += 1
        manifest.setdefault("groups", {})[group_id] = record
        manifest["updated_at"] = _now()
        _write_json(candidate_manifest_path(output_dir), manifest)
    return {"success": failed == 0, "processed": processed, "failed": failed, "skipped": skipped}


def build_candidate_data(
    destination: str,
    input_dir: Path,
    output_dir: Path,
    project: dict,
) -> dict:
    index = ensure_source_index(input_dir, project)
    manifest = load_manifest(output_dir, destination)
    selections = load_selections(output_dir, destination)
    source_groups = {
        item["id"]: item
        for groups in index.get("pages", {}).values()
        for item in groups
    }
    page_groups = {}
    for page in project.get("pages", []):
        page_number = int(page["page"])
        groups = []
        for source in index.get("pages", {}).get(str(page_number), []):
            processed = manifest.get("groups", {}).get(source["id"], {})
            groups.append({
                **source,
                "status": processed.get("status", "pending"),
                "error": processed.get("error", ""),
                "candidate_count": len(processed.get("items", [])),
            })
        page_groups[page_number] = groups

    candidates_by_key: dict[str, list] = {}
    for group_id, group in manifest.get("groups", {}).items():
        if group_id not in source_groups or group.get("status") != "processed":
            continue
        for item in group.get("items", []):
            candidates_by_key.setdefault(item["key"], []).append({
                "candidate_id": group_id,
                "page": group["page"],
                "group": group["group"],
                "source": group["source"],
                **item,
            })
    records = []
    selected_count = 0
    redo_count = 0
    for page in project.get("pages", []):
        page_number = int(page["page"])
        for index_number, spec in enumerate(page.get("poi_specs", []), 1):
            key = f"{page_number}:{index_number}"
            candidates = sorted(
                candidates_by_key.get(key, []), key=lambda item: int(item["group"])
            )
            selection = selections.get("items", {}).get(key, {})
            selected_id = selection.get("candidate_id")
            selected = next((item for item in candidates if item["candidate_id"] == selected_id), None)
            decision = "accepted" if selected else selection.get("decision", "pending")
            if selected:
                selected_count += 1
            elif decision == "redo":
                redo_count += 1
            reference = selected or (candidates[0] if candidates else {})
            records.append({
                "key": key,
                "batch": page_number,
                "index": index_number,
                "poi": spec["name"],
                "poi_zh": spec.get("name_zh", ""),
                "candidates": candidates,
                "selected_candidate": selected_id or "",
                "output": reference.get("output", ""),
                "ai_status": reference.get("ai_status", "NOT_RUN"),
                "confidence": reference.get("confidence"),
                "reason": reference.get("reason", ""),
                "has_ai_flags": any(
                    item.get("ai_status") not in ("PASS", "NOT_RUN") for item in candidates
                ),
                "decision": decision,
                "note": selection.get("note", ""),
                "selected_at": selection.get("selected_at", ""),
            })
    total = len(records)
    pending_count = total - selected_count - redo_count
    pending_source_count = len(pending_groups(input_dir, output_dir, project, destination))
    if not any(page_groups.values()):
        workflow_status = "awaiting_candidates"
    elif pending_source_count:
        workflow_status = "ready_to_process"
    elif selected_count == total and total:
        final_manifest = output_dir / "final" / "manifest.json"
        workflow_status = "exported" if final_manifest.is_file() else "ready_to_export"
    else:
        workflow_status = "selecting"
    return {
        "pages": page_groups,
        "records": records,
        "summary": {
            "total": total,
            "pending": pending_count,
            "accepted": selected_count,
            "redo": redo_count,
            "rejected": 0,
        },
        "pending_groups": pending_source_count,
        "estimated_ai_calls": pending_source_count,
        "ready_to_process": pending_source_count > 0,
        "ready_to_export": total > 0 and selected_count == total,
        "workflow_status": workflow_status,
    }


def select_candidate(output_dir: Path, destination: str, key: str, candidate_id: str, note: str = "") -> dict:
    manifest = load_manifest(output_dir, destination)
    group = manifest.get("groups", {}).get(candidate_id)
    if not group or group.get("status") != "processed":
        raise ValueError("候选组不存在或尚未切图")
    if not any(item.get("key") == key and item.get("output") for item in group.get("items", [])):
        raise ValueError("该候选与POI不匹配")
    selections = load_selections(output_dir, destination)
    items = selections.setdefault("items", {})
    previous = items.get(key, {})
    selected = previous.get("candidate_id") != candidate_id
    items[key] = {
        "candidate_id": candidate_id if selected else "",
        "decision": "accepted" if selected else "pending",
        "note": note.strip(),
        "selected_at": _now() if selected else "",
    }
    selections["updated_at"] = _now()
    _write_json(selections_path(output_dir), selections)
    return {**items[key], "selected": selected}


def mark_redo(output_dir: Path, destination: str, key: str, note: str = "") -> dict:
    selections = load_selections(output_dir, destination)
    selections.setdefault("items", {})[key] = {
        "candidate_id": "",
        "decision": "redo",
        "note": note.strip(),
        "selected_at": _now(),
    }
    selections["updated_at"] = _now()
    _write_json(selections_path(output_dir), selections)
    return selections["items"][key]


def save_note(output_dir: Path, destination: str, key: str, note: str) -> dict:
    selections = load_selections(output_dir, destination)
    item = selections.setdefault("items", {}).setdefault(key, {
        "candidate_id": "", "decision": "pending", "selected_at": "",
    })
    item["note"] = note.strip()
    selections["updated_at"] = _now()
    _write_json(selections_path(output_dir), selections)
    return item


def _backup_path(root: Path, stem: str) -> Path:
    backup_root = root / "_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    base = backup_root / f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}"
    candidate = base
    counter = 1
    while candidate.exists():
        candidate = Path(f"{base}_{counter}")
        counter += 1
    return candidate


def delete_group(
    input_dir: Path,
    output_dir: Path,
    project: dict,
    destination: str,
    candidate_id: str,
) -> dict:
    index = ensure_source_index(input_dir, project)
    target = None
    for groups in index.get("pages", {}).values():
        for item in groups:
            if item["id"] == candidate_id:
                target = item
                groups.remove(item)
                break
        if target:
            break
    if not target:
        raise ValueError("候选组不存在")
    source = Path(target["source"])
    if source.is_file():
        backup = _backup_path(input_dir, f"candidate_{candidate_id}{source.suffix.lower()}")
        shutil.move(str(source), str(backup))
    _write_json(source_index_path(input_dir), index)

    manifest = load_manifest(output_dir, destination)
    record = manifest.get("groups", {}).pop(candidate_id, None)
    if record:
        candidate_dir = output_dir / "candidates" / f"page_{int(record['page']):02d}" / f"group_{int(record['group']):02d}"
        if candidate_dir.exists():
            shutil.move(str(candidate_dir), str(_backup_path(output_dir, f"candidate_{candidate_id}")))
        manifest["updated_at"] = _now()
        _write_json(candidate_manifest_path(output_dir), manifest)

    selections = load_selections(output_dir, destination)
    cleared = []
    for key, item in list(selections.get("items", {}).items()):
        if item.get("candidate_id") == candidate_id:
            selections["items"][key] = {
                "candidate_id": "", "decision": "pending", "note": item.get("note", ""),
                "selected_at": "",
            }
            cleared.append(key)
    if cleared:
        selections["updated_at"] = _now()
        _write_json(selections_path(output_dir), selections)
    return {"deleted": candidate_id, "cleared_selections": cleared}


def delete_candidates(
    output_dir: Path,
    destination: str,
    key: str,
    candidate_ids: list[str],
) -> dict:
    ids = [str(item).strip() for item in candidate_ids if str(item).strip()]
    if not key:
        raise ValueError("请选择有效POI")
    if not ids:
        raise ValueError("请选择要删除的候选图")

    manifest = load_manifest(output_dir, destination)
    deleted = []
    missing = []
    for candidate_id in ids:
        group = manifest.get("groups", {}).get(candidate_id)
        if not group or group.get("status") != "processed":
            missing.append(candidate_id)
            continue
        kept = []
        removed_any = False
        for item in group.get("items", []):
            if item.get("key") == key:
                output = Path(str(item.get("output", "")))
                if output.is_file():
                    output.unlink()
                deleted.append({
                    "candidate_id": candidate_id,
                    "key": key,
                    "output": str(output) if str(output) else "",
                })
                removed_any = True
            else:
                kept.append(item)
        if removed_any:
            group["items"] = kept
            group["updated_at"] = _now()
        else:
            missing.append(candidate_id)

    if deleted:
        manifest["updated_at"] = _now()
        _write_json(candidate_manifest_path(output_dir), manifest)

    selections = load_selections(output_dir, destination)
    cleared = []
    item = selections.get("items", {}).get(key)
    if item and item.get("candidate_id") in ids:
        selections["items"][key] = {
            "candidate_id": "",
            "decision": "pending",
            "note": item.get("note", ""),
            "selected_at": "",
        }
        selections["updated_at"] = _now()
        _write_json(selections_path(output_dir), selections)
        cleared.append(key)

    return {
        "deleted_count": len(deleted),
        "deleted": deleted,
        "missing": missing,
        "cleared_selections": cleared,
    }


def _filename_part(value: str) -> str:
    parts = [part.strip() for part in re.split(r"\s*/\s*", value or "") if part.strip()]
    return "_".join(filter(None, (splitter.safe_filename(part) for part in parts)))


def export_final(destination: str, input_dir: Path, output_dir: Path, project: dict) -> dict:
    data = build_candidate_data(destination, input_dir, output_dir, project)
    if not data["ready_to_export"]:
        missing = [item["poi"] for item in data["records"] if not item["selected_candidate"]]
        raise ValueError(f"还有 {len(missing)} 个POI未选定：" + "、".join(missing[:12]))
    temp_dir = output_dir / f".final_tmp_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True)
    city_part = _filename_part(project.get("city", destination)) or splitter.safe_filename(destination)
    used = {}
    exported = []
    try:
        from PIL import Image

        for ordinal, record in enumerate(data["records"], 1):
            selected = next(
                item for item in record["candidates"]
                if item["candidate_id"] == record["selected_candidate"]
            )
            poi_parts = [record["poi"]]
            if record.get("poi_zh"):
                poi_parts.append(record["poi_zh"])
            base = "_".join(filter(None, [city_part] + [splitter.safe_filename(x) for x in poi_parts]))
            count = used.get(base, 0) + 1
            used[base] = count
            filename = f"{base}{f'_{count:02d}' if count > 1 else ''}.png"
            target = temp_dir / filename
            with Image.open(selected["output"]) as image:
                image = image.convert("RGBA")
                if max(image.size) > splitter.MAX_OUTPUT_SIZE:
                    image.thumbnail((splitter.MAX_OUTPUT_SIZE, splitter.MAX_OUTPUT_SIZE), Image.LANCZOS)
                image.save(target, "PNG")
            exported.append({
                "key": record["key"],
                "poi": record["poi"],
                "poi_zh": record.get("poi_zh", ""),
                "file": str((output_dir / "final" / filename).resolve()),
                "candidate_id": selected["candidate_id"],
                "page": selected["page"],
                "group": selected["group"],
                "source": selected["source"],
                "selected_at": record.get("selected_at", ""),
            })
        _write_json(temp_dir / "manifest.json", {
            "version": 1,
            "destination": destination,
            "exported_at": _now(),
            "count": len(exported),
            "items": exported,
        })
        final_dir = output_dir / "final"
        backup = None
        if final_dir.exists() and any(final_dir.iterdir()):
            backup = _backup_path(output_dir, "final")
            shutil.move(str(final_dir), str(backup))
        elif final_dir.exists():
            final_dir.rmdir()
        os.replace(temp_dir, final_dir)
        return {"count": len(exported), "final_dir": str(final_dir.resolve()), "backup": str(backup) if backup else None}
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise


def export_selected_candidates(
    destination: str,
    input_dir: Path,
    output_dir: Path,
    project: dict,
    key: str,
    candidate_ids: list[str],
    export_dir: str = "",
) -> dict:
    ids = [str(item).strip() for item in candidate_ids if str(item).strip()]
    if not key:
        raise ValueError("请选择有效POI")
    if not ids:
        raise ValueError("请选择要单独导出的候选图")

    data = build_candidate_data(destination, input_dir, output_dir, project)
    record = next((item for item in data["records"] if item["key"] == key), None)
    if not record:
        raise ValueError("找不到对应POI")
    candidates = [
        item for item in record["candidates"]
        if item.get("candidate_id") in ids and item.get("output")
    ]
    if not candidates:
        raise ValueError("选中的候选图不存在或尚未切图")

    base_dir = Path(export_dir).expanduser() if str(export_dir or "").strip() else output_dir / "single_exports"
    folder_stem = f"{_filename_part(project.get('city', destination)) or splitter.safe_filename(destination)}_单独导出_{time.strftime('%Y%m%d_%H%M%S')}"
    export_root = base_dir / folder_stem
    counter = 1
    while export_root.exists():
        export_root = base_dir / f"{folder_stem}_{counter}"
        counter += 1
    export_root.mkdir(parents=True)
    city_part = _filename_part(project.get("city", destination)) or splitter.safe_filename(destination)
    poi_parts = [record["poi"]]
    if record.get("poi_zh"):
        poi_parts.append(record["poi_zh"])
    base = "_".join(filter(None, [city_part] + [splitter.safe_filename(x) for x in poi_parts]))
    exported = []
    try:
        from PIL import Image

        for ordinal, candidate in enumerate(candidates, 1):
            filename = f"{base}_group_{int(candidate['group']):02d}.png"
            if (export_root / filename).exists():
                filename = f"{base}_group_{int(candidate['group']):02d}_{ordinal:02d}.png"
            target = export_root / filename
            with Image.open(candidate["output"]) as image:
                image = image.convert("RGBA")
                if max(image.size) > splitter.MAX_OUTPUT_SIZE:
                    image.thumbnail((splitter.MAX_OUTPUT_SIZE, splitter.MAX_OUTPUT_SIZE), Image.LANCZOS)
                image.save(target, "PNG")
            exported.append({
                "key": key,
                "poi": record["poi"],
                "poi_zh": record.get("poi_zh", ""),
                "file": str(target.resolve()),
                "candidate_id": candidate["candidate_id"],
                "page": candidate["page"],
                "group": candidate["group"],
                "source": candidate["source"],
            })
        _write_json(export_root / "manifest.json", {
            "version": 1,
            "destination": destination,
            "exported_at": _now(),
            "key": key,
            "count": len(exported),
            "items": exported,
        })
        return {"count": len(exported), "export_dir": str(export_root.resolve()), "items": exported}
    except Exception:
        if export_root.exists():
            shutil.rmtree(export_root)
        raise
