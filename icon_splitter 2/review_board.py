#!/usr/bin/env python3
"""Render one shareable PNG containing a city's full candidate review state."""

from __future__ import annotations

import math
import os
import re
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import candidate_manager
import splitter


CANVAS_WIDTH = 1600
MAX_CANVAS_HEIGHT = 2400
COLUMNS = 3
OUTER_MARGIN = 60
COLUMN_GAP = 20
ROW_GAP = 20
HEADER_HEIGHT = 205
FOOTER_HEIGHT = 44
CARD_PADDING = 18
THUMBS_PER_ROW = 5
THUMB_GAP = 6
THUMB_ROW_HEIGHT = 100

BG = "#f2f4f7"
CARD_BG = "#ffffff"
TEXT = "#20242b"
MUTED = "#68707c"
LINE = "#d9dde3"
GREEN = "#18864b"
GREEN_BG = "#e9f7ef"
AMBER = "#a15c00"
AMBER_BG = "#fff4d6"
RED = "#b3261e"
RED_BG = "#fdeceb"
BLUE = "#1769e0"


def _font_candidates(bold: bool) -> list[str]:
    if os.name == "nt":
        return [
            r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\arial.ttf",
        ]
    return [
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def _font(size: int, bold: bool = False):
    for path in _font_candidates(bold):
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _truncate(draw, text: str, font, max_width: int) -> str:
    text = str(text or "")
    if _text_width(draw, text, font) <= max_width:
        return text
    suffix = "..."
    while text and _text_width(draw, text + suffix, font) > max_width:
        text = text[:-1]
    return text + suffix


def _wrap(draw, text: str, font, max_width: int, max_lines: int = 2) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "").strip())
    if not text:
        return []
    lines = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current.rstrip())
            current = char.lstrip()
            if len(lines) == max_lines:
                break
        else:
            current = candidate
    if len(lines) < max_lines and current:
        lines.append(current.rstrip())
    consumed = "".join(lines)
    if len(consumed.replace(" ", "")) < len(text.replace(" ", "")) and lines:
        lines[-1] = _truncate(draw, lines[-1] + "...", font, max_width)
    return lines[:max_lines]


def _status_style(decision: str):
    if decision == "accepted":
        return "已选择", GREEN, GREEN_BG
    if decision == "redo":
        return "需重做", RED, RED_BG
    return "未选择", AMBER, AMBER_BG


def _ai_label(status: str) -> tuple[str, str]:
    labels = {
        "PASS": ("通过", GREEN),
        "REVIEW": ("待审", AMBER),
        "FAIL": ("失败", RED),
        "REVIEW_ERROR": ("错误", RED),
        "NOT_RUN": ("未审", MUTED),
    }
    return labels.get(status, (status or "未审核", MUTED))


def _card_height(record: dict) -> int:
    candidate_rows = max(1, math.ceil(len(record.get("candidates", [])) / THUMBS_PER_ROW))
    note_height = 54 if record.get("note") else 0
    return 142 + candidate_rows * THUMB_ROW_HEIGHT + note_height


def _load_candidate(path: str, size: tuple[int, int]):
    try:
        with Image.open(path) as source:
            image = source.convert("RGBA")
            image.thumbnail(size, Image.Resampling.LANCZOS)
            return image, False
    except Exception:
        return None, True


def _draw_check(draw: ImageDraw.ImageDraw, center_x: int, center_y: int, radius: int = 12):
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill=GREEN,
    )
    draw.line(
        [(center_x - 6, center_y), (center_x - 1, center_y + 5), (center_x + 7, center_y - 6)],
        fill="white", width=3, joint="curve",
    )


def _draw_candidate(draw, canvas, candidate, x, y, width, selected, fonts) -> bool:
    box_height = 92
    border = GREEN if selected else LINE
    draw.rounded_rectangle((x, y, x + width, y + box_height), radius=5, fill="#fafbfc", outline=border, width=3 if selected else 1)
    image, broken = _load_candidate(candidate.get("output", ""), (width - 12, 62))
    image_top = y + 5
    if image:
        px = x + (width - image.width) // 2
        py = image_top + (62 - image.height) // 2
        canvas.alpha_composite(image, (px, py))
    else:
        draw.rectangle((x + 6, image_top, x + width - 6, image_top + 62), fill="#eceff3")
        draw.line((x + 16, image_top + 14, x + width - 16, image_top + 48), fill=RED, width=3)
        draw.line((x + width - 16, image_top + 14, x + 16, image_top + 48), fill=RED, width=3)
    if selected:
        _draw_check(draw, x + width - 10, y + 10, 10)
    ai_text, ai_color = _ai_label(candidate.get("ai_status", "NOT_RUN"))
    label = f"G{int(candidate.get('group', 0)):02d} · {ai_text}"
    label = _truncate(draw, label, fonts["tiny"], width - 8)
    draw.text((x + 4, y + 72), label, font=fonts["tiny"], fill=ai_color)
    return broken


def _draw_card(draw, canvas, record: dict, box: tuple[int, int, int, int], fonts) -> int:
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=8, fill=CARD_BG, outline=LINE, width=1)
    x = left + CARD_PADDING
    content_width = right - left - CARD_PADDING * 2
    y = top + 15

    name = _truncate(draw, record.get("poi", ""), fonts["card_title"], content_width - 88)
    draw.text((x, y), name, font=fonts["card_title"], fill=TEXT)
    status_text, status_color, status_bg = _status_style(record.get("decision", "pending"))
    status_width = max(68, int(_text_width(draw, status_text, fonts["small"]) + 20))
    draw.rounded_rectangle((right - CARD_PADDING - status_width, y, right - CARD_PADDING, y + 27), radius=5, fill=status_bg)
    draw.text((right - CARD_PADDING - status_width + 10, y + 4), status_text, font=fonts["small"], fill=status_color)
    y += 31

    if record.get("poi_zh"):
        zh = _truncate(draw, record["poi_zh"], fonts["body_bold"], content_width)
        draw.text((x, y), zh, font=fonts["body_bold"], fill=MUTED)
    y += 27
    meta = f"PAGE {record.get('batch', 0)} · 第 {record.get('index', 0)} 格 · {len(record.get('candidates', []))} 个候选"
    draw.text((x, y), meta, font=fonts["small"], fill=MUTED)
    flagged = sum(1 for item in record.get("candidates", []) if item.get("ai_status") not in ("PASS", "NOT_RUN"))
    if flagged:
        flag_text = f"AI异常 {flagged}"
        draw.text((right - CARD_PADDING - _text_width(draw, flag_text, fonts["small"]), y), flag_text, font=fonts["small"], fill=RED)
    y += 31

    candidates = sorted(record.get("candidates", []), key=lambda item: int(item.get("group", 0)))
    thumb_width = (content_width - THUMB_GAP * (THUMBS_PER_ROW - 1)) // THUMBS_PER_ROW
    broken_count = 0
    if candidates:
        for offset, candidate in enumerate(candidates):
            row = offset // THUMBS_PER_ROW
            column = offset % THUMBS_PER_ROW
            thumb_x = x + column * (thumb_width + THUMB_GAP)
            thumb_y = y + row * THUMB_ROW_HEIGHT
            selected = candidate.get("candidate_id") == record.get("selected_candidate")
            broken_count += int(_draw_candidate(draw, canvas, candidate, thumb_x, thumb_y, thumb_width, selected, fonts))
        y += math.ceil(len(candidates) / THUMBS_PER_ROW) * THUMB_ROW_HEIGHT
    else:
        draw.rounded_rectangle((x, y, right - CARD_PADDING, y + 72), radius=5, fill="#f4f5f7", outline=LINE)
        empty = "暂无候选"
        draw.text((x + (content_width - _text_width(draw, empty, fonts["body"])) / 2, y + 24), empty, font=fonts["body"], fill=MUTED)
        y += THUMB_ROW_HEIGHT

    note = record.get("note", "")
    if note:
        draw.text((x, y + 2), "备注：", font=fonts["small_bold"], fill=MUTED)
        lines = _wrap(draw, note, fonts["small"], content_width - 48, 2)
        for line_index, line in enumerate(lines):
            draw.text((x + 46, y + line_index * 20), line, font=fonts["small"], fill=TEXT)
    return broken_count


def _safe_city_name(city: str) -> str:
    parts = [splitter.safe_filename(part.strip()) for part in re.split(r"\s*/\s*", city or "") if part.strip()]
    return "_".join(filter(None, parts)) or "city"


def _build_fonts() -> dict:
    return {
        "title": _font(42, True),
        "subtitle": _font(20),
        "metric": _font(18, True),
        "card_title": _font(21, True),
        "body_bold": _font(17, True),
        "body": _font(16),
        "small_bold": _font(14, True),
        "small": _font(14),
        "tiny": _font(12),
    }


def _draw_header(draw, fonts, city: str, generated: str, summary: dict, page_number: int, page_count: int) -> None:
    draw.text((OUTER_MARGIN, 45), city, font=fonts["title"], fill=TEXT)
    subtitle = f"POI人工审核总览 · 生成时间 {generated}"
    if page_count > 1:
        subtitle += f" · 第 {page_number}/{page_count} 页"
    draw.text((OUTER_MARGIN, 101), subtitle, font=fonts["subtitle"], fill=MUTED)
    metrics = [
        (f"POI {summary.get('total', 0)}", TEXT, "#ffffff"),
        (f"已选择 {summary.get('accepted', 0)}", GREEN, GREEN_BG),
        (f"未选择 {summary.get('pending', 0)}", AMBER, AMBER_BG),
        (f"需重做 {summary.get('redo', 0)}", RED, RED_BG),
    ]
    metric_x = OUTER_MARGIN
    for label, color, fill in metrics:
        width = int(_text_width(draw, label, fonts["metric"]) + 28)
        draw.rounded_rectangle((metric_x, 143, metric_x + width, 178), radius=6, fill=fill, outline=LINE)
        draw.text((metric_x + 14, 150), label, font=fonts["metric"], fill=color)
        metric_x += width + 10
    draw.text((CANVAS_WIDTH - OUTER_MARGIN - 410, 151), "绿色描边与对勾 = 当前最终选择", font=fonts["small"], fill=GREEN)


def _paginate_rows(rows: list[list[dict]], row_heights: list[int]) -> list[tuple[list[list[dict]], list[int]]]:
    max_body_height = MAX_CANVAS_HEIGHT - HEADER_HEIGHT - FOOTER_HEIGHT - OUTER_MARGIN
    pages = []
    current_rows = []
    current_heights = []
    current_height = 0
    for row, row_height in zip(rows, row_heights):
        added_gap = ROW_GAP if current_rows else 0
        if current_rows and current_height + added_gap + row_height > max_body_height:
            pages.append((current_rows, current_heights))
            current_rows = []
            current_heights = []
            current_height = 0
            added_gap = 0
        current_rows.append(row)
        current_heights.append(row_height)
        current_height += added_gap + row_height
    if current_rows:
        pages.append((current_rows, current_heights))
    return pages


def export_review_board(
    destination: str,
    input_dir: Path,
    output_dir: Path,
    project: dict,
) -> dict:
    data = candidate_manager.build_candidate_data(destination, input_dir, output_dir, project)
    records = data.get("records", [])
    if not records:
        raise ValueError("当前城市没有可导出的POI")

    card_width = (CANVAS_WIDTH - OUTER_MARGIN * 2 - COLUMN_GAP * (COLUMNS - 1)) // COLUMNS
    rows = [records[index:index + COLUMNS] for index in range(0, len(records), COLUMNS)]
    row_heights = [max(_card_height(record) for record in row) for row in rows]
    city = project.get("city") or destination
    generated = time.strftime("%Y-%m-%d %H:%M")
    summary = data.get("summary", {})
    fonts = _build_fonts()
    pages = _paginate_rows(rows, row_heights)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    city_name = _safe_city_name(city)
    target_dir = output_dir / "review_boards" / f"{city_name}_POI审核总览_{stamp}"
    target_dir.mkdir(parents=True, exist_ok=False)
    saved_pages = []
    total_broken_count = 0
    total_candidate_count = sum(len(record.get("candidates", [])) for record in records)
    for page_index, (page_rows, page_row_heights) in enumerate(pages, 1):
        body_height = sum(page_row_heights) + ROW_GAP * max(0, len(page_rows) - 1)
        canvas_height = HEADER_HEIGHT + body_height + FOOTER_HEIGHT + OUTER_MARGIN
        canvas = Image.new("RGBA", (CANVAS_WIDTH, canvas_height), BG)
        draw = ImageDraw.Draw(canvas)
        _draw_header(draw, fonts, city, generated, summary, page_index, len(pages))

        y = HEADER_HEIGHT
        page_broken_count = 0
        for row, row_height in zip(page_rows, page_row_heights):
            for column, record in enumerate(row):
                left = OUTER_MARGIN + column * (card_width + COLUMN_GAP)
                box = (left, y, left + card_width, y + row_height)
                page_broken_count += _draw_card(draw, canvas, record, box, fonts)
            y += row_height + ROW_GAP
        total_broken_count += page_broken_count

        footer = f"候选图 {total_candidate_count} 张"
        if total_broken_count or page_broken_count:
            footer += f" · 缺失/损坏候选图使用占位图"
        if len(pages) > 1:
            footer += f" · 第 {page_index}/{len(pages)} 页"
        draw.text((OUTER_MARGIN, canvas_height - FOOTER_HEIGHT), footer, font=fonts["small"], fill=MUTED)

        filename = f"part{page_index:02d}.png"
        target = target_dir / filename
        canvas.convert("RGB").save(target, "PNG", optimize=True)
        saved_pages.append({
            "path": str(target.resolve()),
            "width": CANVAS_WIDTH,
            "height": canvas_height,
            "page": page_index,
        })

    first = saved_pages[0]
    return {
        "path": first["path"],
        "dir": str(target_dir.resolve()),
        "pages": saved_pages,
        "page_count": len(saved_pages),
        "width": CANVAS_WIDTH,
        "height": first["height"],
        "max_height": MAX_CANVAS_HEIGHT,
        "poi_count": len(records),
        "candidate_count": total_candidate_count,
        "broken_candidate_count": total_broken_count,
    }
