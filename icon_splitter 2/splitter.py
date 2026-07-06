#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=========================================================
  4×4 图标批量切分器（独立离线版）
=========================================================
适用场景：
  你已经在外部用 AI（例如 Nanobanana / Gemini Image）生成了
  一张或多张 4×4 大图，需要：
    - 自动去除图标下方的英文/中文标签文字
    - 按图标外形抠图（白底变透明）
    - 按你提供的 POI 名称命名为单独 PNG

工作流：
  1) 把每个目的地的 3 张大图 + 1 个 pois.json 放到
     inputs/<目的地名>/ 下
       - batch1.png / batch2.png / ...
       - pois.json   { "pois": ["POI 1", ...] }
       注：第 1~16 个 POI 对应 batch1.png；
           第 17~32 个对应 batch2.png；
           第 33~48 个对应 batch3.png，依此类推。
  2) 双击 run.command（或在 Terminal 跑 python3 splitter.py）。
  3) 切分结果输出到 outputs/<目的地名>/cropped/<POI>.png。

依赖：
  Python 3.9+，自动从 requirements.txt 安装。
  首次运行 OCR 会下载约 100MB 模型到 ~/.EasyOCR/，请保持网络畅通。

普通切图无需联网（除首次下载 OCR 模型外）。可选 --review 需要联网和已登录的 Codex CLI。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Callable, Dict, List, Optional, Tuple

# ──────────────────────────────────────────────────────────
#                      用户路径配置
# ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUTS_DIR = os.path.join(BASE_DIR, "inputs")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

# 单批最大图标数（4×4 网格）
BATCH_SIZE = 16
# 每个目的地总图标数（3 批）
DEFAULT_TOTAL = 48
# 输出图标最大边长（px）：等比缩放使 max(w, h) ≤ MAX_OUTPUT_SIZE。设为 None 关闭缩放。
MAX_OUTPUT_SIZE = 100

# ──────────────────────────────────────────────────────────
#                      切分核心参数
# ──────────────────────────────────────────────────────────
BG_TOLERANCE = 30          # 背景色容差
REMOVE_TEXT = True         # 默认开启 OCR 去文字

OCR_READER = None  # 懒加载


# ──────────────────────────────────────────────────────────
#                      OCR 文字去除
# ──────────────────────────────────────────────────────────
def get_ocr_reader():
    """懒加载 EasyOCR Reader，只初始化一次。"""
    global OCR_READER
    if OCR_READER is not None:
        return OCR_READER
    try:
        import easyocr  # type: ignore
        print("  [OCR] 加载 easyocr 模型中（首次下载约 100MB，请耐心等待）...")
        OCR_READER = easyocr.Reader(['en', 'ch_sim'], gpu=False, verbose=False)
        print("  [OCR] 模型加载完成")
        return OCR_READER
    except ImportError:
        print("  [警告] 未安装 easyocr，跳过文字去除。")
        print("         手动安装：pip3 install easyocr")
        return None


def remove_text(img_arr):
    """检测并修复图中的文字区域。"""
    if not REMOVE_TEXT:
        return img_arr

    import numpy as np
    import cv2  # type: ignore

    reader = get_ocr_reader()
    if reader is None:
        return img_arr

    img_bgr = cv2.cvtColor(img_arr[:, :, :3], cv2.COLOR_RGB2BGR)
    results = reader.readtext(img_bgr)

    if not results:
        print("  [OCR] 未检测到文字")
        return img_arr

    mask = np.zeros(img_bgr.shape[:2], dtype=np.uint8)
    text_found = False
    for (bbox, text, prob) in results:
        if prob < 0.3:
            continue
        text_found = True
        pts = np.array(bbox, dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)
        print(f"  [OCR] 去除文字: '{text}' (置信度: {prob:.2f})")

    if not text_found:
        print("  [OCR] 未检测到高置信度文字")
        return img_arr

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)
    img_inpainted = cv2.inpaint(img_bgr, mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)
    img_rgb = cv2.cvtColor(img_inpainted, cv2.COLOR_BGR2RGB)
    return np.dstack([img_rgb, img_arr[:, :, 3]])


# ──────────────────────────────────────────────────────────
#                      图标检测算法
# ──────────────────────────────────────────────────────────
def detect_background_color(img_arr):
    """采样四边浅色像素，估算背景色（默认白色）。"""
    import numpy as np
    h, w = img_arr.shape[:2]
    r = img_arr[:, :, 0].astype(int)
    g = img_arr[:, :, 1].astype(int)
    b = img_arr[:, :, 2].astype(int)

    edge_pixels = []
    edge_pixels.extend([(r[0, x], g[0, x], b[0, x]) for x in range(w)])
    edge_pixels.extend([(r[h - 1, x], g[h - 1, x], b[h - 1, x]) for x in range(w)])
    edge_pixels.extend([(r[y, 0], g[y, 0], b[y, 0]) for y in range(h)])
    edge_pixels.extend([(r[y, w - 1], g[y, w - 1], b[y, w - 1]) for y in range(h)])

    bright_pixels = [(pr, pg, pb) for pr, pg, pb in edge_pixels
                     if (pr + pg + pb) / 3 > 180]
    if len(bright_pixels) > len(edge_pixels) * 0.3:
        bg_r = int(np.median([p[0] for p in bright_pixels]))
        bg_g = int(np.median([p[1] for p in bright_pixels]))
        bg_b = int(np.median([p[2] for p in bright_pixels]))
    else:
        bg_r, bg_g, bg_b = 255, 255, 255
    return bg_r, bg_g, bg_b


def _dist_point_to_bbox(px, py, bbox):
    left, top, right, bottom = bbox
    cx = max(left, min(px, right))
    cy = max(top, min(py, bottom))
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def auto_detect_icons(img_arr, bg_color, tolerance=BG_TOLERANCE, expected_count=BATCH_SIZE):
    """检测前景独立连通区，小区域合并到最近的大图标。"""
    import numpy as np
    from scipy import ndimage  # type: ignore

    h, w = img_arr.shape[:2]
    r = img_arr[:, :, 0].astype(int)
    g = img_arr[:, :, 1].astype(int)
    b = img_arr[:, :, 2].astype(int)
    bg_r, bg_g, bg_b = bg_color

    diff = np.abs(r - bg_r) + np.abs(g - bg_g) + np.abs(b - bg_b)
    foreground = diff > tolerance
    foreground = ndimage.binary_closing(foreground, iterations=3)
    foreground = ndimage.binary_opening(foreground, iterations=2)

    labeled, num_features = ndimage.label(foreground)

    all_regions = []
    for i in range(1, num_features + 1):
        ys, xs = np.where(labeled == i)
        area = len(ys)
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        all_regions.append({
            'label': i, 'bbox': bbox, 'area': area,
            'center': (cx, cy), 'merged_labels': [i],
        })
    all_regions.sort(key=lambda r: r['area'], reverse=True)

    total_fg = sum(r['area'] for r in all_regions)
    avg_icon_area = total_fg / max(expected_count, 1)
    min_area = int(avg_icon_area * 0.05)

    cell_w = w / 4
    max_merge_dist = cell_w * 1.5

    large_regions, small_regions = [], []
    for reg in all_regions:
        if reg['area'] < min_area:
            small_regions.append(reg)
        elif len(large_regions) < expected_count:
            large_regions.append(reg)
        else:
            small_regions.append(reg)

    for small in small_regions:
        sx, sy = small['center']
        min_dist, nearest = float('inf'), None
        for large in large_regions:
            d = _dist_point_to_bbox(sx, sy, large['bbox'])
            if d < min_dist:
                min_dist, nearest = d, large
        if nearest and min_dist <= max_merge_dist:
            sl, st, sr, sb = small['bbox']
            ll, lt, lr, lb = nearest['bbox']
            nearest['bbox'] = (min(sl, ll), min(st, lt), max(sr, lr), max(sb, lb))
            nearest['merged_labels'].append(small['label'])
            print(f"  [合并] 小区域(area={small['area']}) → 最近图标(dist={min_dist:.0f}px)")
        else:
            reason = f"距离过远({min_dist:.0f}>{max_merge_dist:.0f})" if nearest else "无候选"
            print(f"  [丢弃] 噪点(area={small['area']}, {reason})")

    return large_regions, labeled


def sort_regions_grid(regions, expected_cols=4):
    """按 4×4 网格顺序排序（行优先）。"""
    if not regions:
        return regions
    expected_rows = (len(regions) + expected_cols - 1) // expected_cols
    by_y = sorted(regions, key=lambda r: r['center'][1])
    if len(by_y) <= 1:
        return by_y
    y_coords = [r['center'][1] for r in by_y]
    y_gaps = [(y_coords[i + 1] - y_coords[i], i) for i in range(len(y_coords) - 1)]
    y_gaps_sorted = sorted(y_gaps, key=lambda x: x[0], reverse=True)
    split_indices = sorted([gap[1] for gap in y_gaps_sorted[:expected_rows - 1]])

    rows = []
    start = 0
    for split_idx in split_indices:
        rows.append(by_y[start:split_idx + 1])
        start = split_idx + 1
    rows.append(by_y[start:])

    sorted_regions = []
    for row_idx, row in enumerate(rows):
        row_sorted = sorted(row, key=lambda r: r['center'][0])
        sorted_regions.extend(row_sorted)
        print(f"  [排序] 第 {row_idx + 1} 行: {len(row_sorted)} 个图标")
    return sorted_regions


def extract_icon(img, region, labeled, bg_color):
    """提取单个图标并去除背景（白底变透明）。"""
    import numpy as np
    from PIL import Image

    left, top, right, bottom = region['bbox']
    merged_labels = region['merged_labels']
    padding = 5
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(img.width, right + padding)
    bottom = min(img.height, bottom + padding)

    cell = img.crop((left, top, right, bottom))
    ca = np.array(cell.convert("RGBA"))
    label_crop = labeled[top:bottom, left:right]

    r = ca[:, :, 0].astype(int)
    g = ca[:, :, 1].astype(int)
    b = ca[:, :, 2].astype(int)
    bg_r, bg_g, bg_b = bg_color

    is_bg_color = (np.abs(r - bg_r) + np.abs(g - bg_g) + np.abs(b - bg_b)) < BG_TOLERANCE
    is_this_icon = np.isin(label_crop, merged_labels)
    ca[is_bg_color & ~is_this_icon, 3] = 0

    cell = Image.fromarray(ca)
    bb = cell.getbbox()
    if bb:
        cell = cell.crop(bb)
    return cell


# ──────────────────────────────────────────────────────────
#                      文件名工具
# ──────────────────────────────────────────────────────────
def safe_filename(name: str) -> str:
    """与原流水线一致的安全文件名规则。"""
    return re.sub(r"[^\w\-]", "_", str(name).strip()).strip("_")[:100]


# ──────────────────────────────────────────────────────────
#                      单张大图切分
# ──────────────────────────────────────────────────────────
def split_one_grid(
    source_path: str,
    pois: List[str],
    out_dir: str,
    *,
    max_output_size: Optional[int] = MAX_OUTPUT_SIZE,
    log: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str, Dict[str, str]]:
    """
    切分一张 4×4 大图。
    pois: 与该大图对应的 POI 名称列表（最多 16 个，可少于 16）。
    out_dir: 切片输出目录（已存在或自动创建）。
    返回 (成功, 错误信息, {poi 原名: 绝对路径})。
    """
    from PIL import Image
    import numpy as np

    _log = log or print

    if not source_path or not os.path.isfile(source_path):
        return False, f"源图不存在: {source_path}", {}
    if not pois:
        return False, "POI 列表为空", {}

    os.makedirs(out_dir, exist_ok=True)

    img = Image.open(source_path).convert("RGBA")
    w, h = img.size
    _log(f"  源图: {os.path.basename(source_path)} · 尺寸 {w}×{h}")

    arr = np.array(img)
    _log("  去文字（依赖 easyocr，可关闭：--no-ocr）...")
    arr = remove_text(arr)
    img = Image.fromarray(arr)

    bg_color = detect_background_color(arr)
    _log(f"  背景色: RGB{bg_color}")

    n_pois = len(pois)
    regions, labeled = auto_detect_icons(arr, bg_color, expected_count=n_pois)
    _log(f"  检测到 {len(regions)} 个主图标区域（期望 {n_pois} 个）")
    if not regions:
        return False, "未检测到任何图标区域（请检查源图或依赖）", {}
    if len(regions) != n_pois:
        _log(f"  [警告] 检测数 {len(regions)} ≠ POI 数 {n_pois}，按较小者切分")

    regions = sort_regions_grid(regions)
    n_need = min(n_pois, len(regions))

    mapping: Dict[str, str] = {}
    for idx in range(n_need):
        region = regions[idx]
        cell = extract_icon(img, region, labeled, bg_color)
        orig_w, orig_h = cell.size

        # 等比缩放：max(w, h) ≤ MAX_OUTPUT_SIZE。Image.thumbnail 原地修改，自动保持比例。
        if max_output_size and max(orig_w, orig_h) > max_output_size:
            cell.thumbnail((max_output_size, max_output_size), Image.LANCZOS)

        poi = pois[idx]
        fname = safe_filename(poi) + ".png"
        out_path = os.path.join(out_dir, fname)
        cell.save(out_path, "PNG")
        mapping[poi] = os.path.abspath(out_path)
        if (orig_w, orig_h) != cell.size:
            _log(f"  [{idx + 1:2d}] {fname:50s}  {orig_w:4d}×{orig_h:<4d} → {cell.size[0]:3d}×{cell.size[1]:<3d}")
        else:
            _log(f"  [{idx + 1:2d}] {fname:50s}  {cell.size[0]:4d}×{cell.size[1]:4d}")

    return True, "", mapping


# ──────────────────────────────────────────────────────────
#                  目的地批量处理（多张大图）
# ──────────────────────────────────────────────────────────
def find_batch_files(dest_dir: str) -> List[str]:
    """按 batch1.png / batch2.png / ... 顺序查找源大图。
    支持 png/jpg/jpeg（大小写不敏感）。"""
    found = []
    for n in range(1, 11):  # 最多支持 10 批，足够覆盖 160 个 POI
        for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
            p = os.path.join(dest_dir, f"batch{n}{ext}")
            if os.path.isfile(p):
                found.append(p)
                break
    return found


def load_pois_json(dest_dir: str) -> List[dict]:
    """读取 pois.json，兼容字符串及带中英文名称、描述的 POI 对象。"""
    path = os.path.join(dest_dir, "pois.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到 {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "pois" not in data:
        raise ValueError(f'{path} 必须是 {{"pois": [...]}} 格式')
    pois = data["pois"]
    if not isinstance(pois, list) or not pois:
        raise ValueError(f"{path} 中 pois 必须是非空数组")
    normalized = []
    for index, poi in enumerate(pois, 1):
        if isinstance(poi, str) and poi.strip():
            normalized.append({"name": poi.strip(), "name_zh": "", "prompt_name": "", "description": ""})
            continue
        if isinstance(poi, dict):
            name = poi.get("name")
            name_zh = poi.get("name_zh", "")
            prompt_name = poi.get("prompt_name", "")
            description = poi.get("description", "")
            if (
                isinstance(name, str) and name.strip()
                and isinstance(name_zh, str) and isinstance(prompt_name, str) and isinstance(description, str)
            ):
                normalized.append({
                    "name": name.strip(),
                    "name_zh": name_zh.strip(),
                    "prompt_name": prompt_name.strip(),
                    "description": description.strip(),
                })
                continue
        raise ValueError(
            f"{path} 中第 {index} 个 POI 必须是非空字符串，"
            '或 {"name": "...", "name_zh": "...", "prompt_name": "...", "description": "..."}'
        )
    return normalized


def process_destination(dest_name: str, dest_dir: str, out_root: str, *, review_enabled: bool = False) -> dict:
    """处理单个目的地：扁平 POI → 按 16 切分给 batch1/2/3 → 智能切分。"""
    print(f"\n{'═' * 60}")
    print(f"  目的地: {dest_name}")
    print(f"  输入目录: {dest_dir}")
    print(f"{'═' * 60}")

    try:
        poi_specs_all = load_pois_json(dest_dir)
    except Exception as e:
        msg = f"读取 pois.json 失败: {e}"
        print(f"  [错误] {msg}")
        return {"success": False, "destination": dest_name, "error": msg}

    batch_paths = find_batch_files(dest_dir)
    if not batch_paths:
        msg = "未找到任何 batch{N}.png 大图"
        print(f"  [错误] {msg}")
        return {"success": False, "destination": dest_name, "error": msg}

    pois_all = [p["name"] for p in poi_specs_all]
    n_total = len(poi_specs_all)
    n_batches = len(batch_paths)
    print(f"  POI 总数: {n_total}  ·  大图张数: {n_batches}")

    # 分组：每张大图对应连续 16 个 POI
    out_dir = os.path.join(out_root, dest_name, "cropped")
    os.makedirs(out_dir, exist_ok=True)

    mapping_all: Dict[str, str] = {}
    batch_records = []
    review_batches = []

    for i, src in enumerate(batch_paths):
        start = i * BATCH_SIZE
        end = min(start + BATCH_SIZE, n_total)
        if start >= n_total:
            print(f"  [跳过] batch{i + 1}：POI 已用完（总 {n_total} 个）")
            continue
        batch_pois = pois_all[start:end]
        batch_specs = poi_specs_all[start:end]
        print(f"\n  ▶ 切分 batch{i + 1}: {len(batch_pois)} 个 POI（POI {start + 1}~{end}）")
        ok, err, mapping = split_one_grid(src, batch_pois, out_dir)
        if not ok:
            msg = f"batch{i + 1} 切分失败: {err}"
            print(f"  [错误] {msg}")
            return {"success": False, "destination": dest_name, "error": msg, "mapping": mapping_all}
        mapping_all.update(mapping)
        batch_records.append({
            "index": i + 1,
            "source": os.path.abspath(src),
            "pois": batch_pois,
            "count": len(mapping),
        })

        if review_enabled:
            from reviewer import review_batch_with_codex
            review_batches.append(
                review_batch_with_codex(src, dest_name, i + 1, batch_specs)
            )

    review_payload = {"enabled": False}
    review_job = None
    if review_enabled:
        from reviewer import build_ai_review, review_manifest_payload
        review_dir = os.path.join(out_root, dest_name, "review")
        ai_report = build_ai_review(dest_name, review_batches, review_dir)
        ai_path = os.path.join(review_dir, "ai_review.json")
        manual_path = os.path.join(review_dir, "manual_review.json")
        review_payload = review_manifest_payload(ai_report, ai_path, manual_path)

    # 落库 manifest 方便后续核对
    manifest_path = os.path.join(out_root, dest_name, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "destination": dest_name,
            "total_pois": n_total,
            "n_batches": len(batch_records),
            "out_dir": os.path.abspath(out_dir),
            "batches": batch_records,
            "mapping": mapping_all,
            "review": review_payload,
        }, f, ensure_ascii=False, indent=2)

    if review_enabled:
        review_job = {
            "ai_report": ai_report,
            "manual_path": manual_path,
            "manifest_path": manifest_path,
        }

    print(f"\n  ✅ {dest_name}: 共切分 {len(mapping_all)} 个图标")
    print(f"  📁 输出: {out_dir}")
    print(f"  📄 清单: {manifest_path}")

    return {
        "success": True,
        "destination": dest_name,
        "out_dir": os.path.abspath(out_dir),
        "mapping": mapping_all,
        "manifest": manifest_path,
        "review_job": review_job,
    }


def list_destinations() -> List[Tuple[str, str]]:
    """扫描 inputs/ 下的所有目的地文件夹（跳过下划线开头）。"""
    if not os.path.isdir(INPUTS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(INPUTS_DIR)):
        if name.startswith(".") or name.startswith("_"):
            continue
        full = os.path.join(INPUTS_DIR, name)
        if os.path.isdir(full):
            out.append((name, full))
    return out


# ──────────────────────────────────────────────────────────
#                          CLI
# ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="4×4 图标批量切分器（独立离线版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 splitter.py                    # 处理 inputs/ 下所有目的地
  python3 splitter.py Bangkok            # 只处理 Bangkok
  python3 splitter.py Bangkok Tokyo      # 处理多个
  python3 splitter.py --no-ocr           # 不去文字（速度快）
  python3 splitter.py Bangkok --review   # 切图后启用 AI 整图初审
""",
    )
    parser.add_argument("destinations", nargs="*",
                        help="要处理的目的地（不填 = 处理 inputs/ 下所有）")
    parser.add_argument("--no-ocr", action="store_true", help="禁用 OCR 文字去除")
    parser.add_argument("--review", action="store_true",
                        help="启用可选 AI 整图初审（会使用当前 Codex Plus 额度）")
    parser.add_argument("--interactive-review", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--review-timeout", type=int, default=1800,
                        help="人工复审网页最长等待秒数（默认 1800）")
    parser.add_argument("--no-open-review", action="store_true",
                        help="不自动打开人工复审浏览器（仍会打印本地网址）")
    args = parser.parse_args()

    if args.interactive_review and not args.review:
        try:
            answer = input("\n是否启用 AI 图片审核？会使用 Codex Plus 额度 [y/N]: ").strip().lower()
            args.review = answer in ("y", "yes", "1", "是")
        except (EOFError, KeyboardInterrupt):
            args.review = False

    global REMOVE_TEXT
    if args.no_ocr:
        REMOVE_TEXT = False
        print("[配置] OCR 文字去除：已关闭")
    else:
        print("[配置] OCR 文字去除：已开启（依赖 easyocr）")
    print(f"[配置] AI 图片审核：{'已开启' if args.review else '已关闭'}")

    # 确定要处理的目的地
    if args.destinations:
        targets = []
        for name in args.destinations:
            d = os.path.join(INPUTS_DIR, name)
            if not os.path.isdir(d):
                print(f"[错误] 找不到目录: {d}")
                sys.exit(1)
            targets.append((name, d))
    else:
        targets = list_destinations()
        if not targets:
            print(f"[提示] {INPUTS_DIR} 下没有任何目的地子目录。")
            print("       请先在 inputs/ 下创建一个目的地文件夹（例如 inputs/Bangkok/），")
            print("       内含 batch1.png / batch2.png / batch3.png 和 pois.json。")
            sys.exit(0)
        print(f"[扫描] inputs/ 下共发现 {len(targets)} 个目的地: "
              + ", ".join(n for n, _ in targets))

    results = []
    for name, dest_dir in targets:
        results.append(process_destination(name, dest_dir, OUTPUTS_DIR, review_enabled=args.review))

    if args.review:
        review_jobs = [r["review_job"] for r in results if r.get("review_job")]
        if review_jobs:
            from reviewer import serve_manual_review
            serve_manual_review(
                review_jobs,
                timeout=max(1, args.review_timeout),
                open_browser=not args.no_open_review,
            )

    # 汇总
    print(f"\n{'━' * 60}")
    print(f"  汇总报告")
    print(f"{'━' * 60}")
    ok_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - ok_count
    print(f"  成功: {ok_count}  ·  失败: {fail_count}")
    for r in results:
        flag = "✅" if r["success"] else "❌"
        if r["success"]:
            print(f"  {flag} {r['destination']}: {len(r['mapping'])} 个图标 → {r['out_dir']}")
        else:
            print(f"  {flag} {r['destination']}: {r.get('error', '?')}")
    print()


if __name__ == "__main__":
    main()
