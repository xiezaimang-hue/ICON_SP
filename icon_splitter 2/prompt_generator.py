#!/usr/bin/env python3
"""Deterministic page prompts for external 4x4 POI image generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List


BATCH_SIZE = 16


def chunk_specs(specs: List[dict], size: int = BATCH_SIZE):
    return [specs[index:index + size] for index in range(0, len(specs), size)]


def _description(spec: dict) -> str:
    supplied = str(spec.get("description", "")).strip()
    if supplied:
        return supplied
    name = spec["name"]
    return (
        f"A recognizable miniature 3D icon interpretation of {name}, "
        "simplified around its most iconic visible architectural, natural, food, or activity features"
    )


def generate_page_prompt(city: str, specs: List[dict], page: int) -> str:
    rows = []
    for row_index in range(4):
        row_specs = specs[row_index * 4:(row_index + 1) * 4]
        if not row_specs:
            continue
        rows.append(f"**ROW {row_index + 1} (Left to Right):**")
        for item_index, spec in enumerate(row_specs, 1):
            rows.append(f"{item_index}. **{spec['name']}** ({_description(spec)})")
        rows.append("")

    poi_names = ", ".join(spec["name"] for spec in specs)
    return f"""CITY: {city}
PAGE: {page}
POIS IN ORDER: {poi_names}

[核心布局 - 4x4 网格]
**LAYOUT:** **4x4 Grid Sprite Sheet (16 distinct items).**
**VIEW:** **Isometric view (45 degrees).**
**BACKGROUND:** **Solid White (#FFFFFF).**

[核心修正 - 杀底座 & 杀文字]
**COMPOSITION:** **ISOLATED DIE-CUT 3D ICONS.**
1. **Ground:** **Objects sit DIRECTLY on the white floor.**
2. **Negative:** **NO base, NO platform, NO podium, NO tile, NO ground block.**
3. **Text:** **ABSOLUTELY NO TEXT.** All signs, billboards, and logos must be **BLANK** colored geometry. No letters, no scribbles.

[核心修正 - 无投影 (关键)]
**LIGHTING:** **HIGH ANGLE SOFTBOX LIGHTING.**
Positioned **high above (80 degrees)**, **NO shadows.**
**Style:** Clean, studio product photography.

[材质与风格 - 哑光粘土]
**STYLE:** **Nanobanana Style + Matte Clay.**
- **Texture:** Smooth, dry, unglazed ceramic. **NO reflection.**
- **Vibe:** Cute, chunky, simplified shapes.

[核心内容 - 16 个指定地标]

{chr(10).join(rows).rstrip()}

[技术参数]
8k, 3D render, octane render, soft lighting --ar 1:1 --stylize 50 --no base, platform, podium, stand, pedestal, ground tile, glossy, shiny, reflection, noise, grain, dirt, high contrast, black shadows

[技术参数 - 负面词拉满]
8k, 3D render, octane render --ar 1:1 --stylize 100 --no long shadows, cast shadows, sunset, low light, text, font, letters, words, signage, logo, brand, base, stand, pedestal, podium, platform, slab, tile, ground block, diorama, island
"""


def write_city_project(city_dir: Path, city: str, specs: List[dict]) -> dict:
    prompts_dir = city_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for page_index, page_specs in enumerate(chunk_specs(specs), 1):
        prompt_path = prompts_dir / f"page_{page_index:02d}.txt"
        prompt_path.write_text(generate_page_prompt(city, page_specs, page_index), encoding="utf-8")
        pages.append({
            "page": page_index,
            "start_index": (page_index - 1) * BATCH_SIZE + 1,
            "end_index": (page_index - 1) * BATCH_SIZE + len(page_specs),
            "poi_count": len(page_specs),
            "pois": [spec["name"] for spec in page_specs],
            "poi_specs": [
                {
                    "name": spec["name"],
                    "name_zh": str(spec.get("name_zh", "")).strip(),
                    "description": str(spec.get("description", "")).strip(),
                }
                for spec in page_specs
            ],
            "described_count": sum(1 for spec in page_specs if spec.get("description")),
            "prompt": str(prompt_path.resolve()),
            "expected_batch": f"batch{page_index}.png",
        })
    project = {
        "version": 1,
        "city": city,
        "total_pois": len(specs),
        "page_count": len(pages),
        "pages": pages,
    }
    (city_dir / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return project


def load_city_project(city_dir: Path) -> dict:
    path = city_dir / "project.json"
    if path.is_file():
        project = json.loads(path.read_text(encoding="utf-8"))
        if all("poi_specs" in page for page in project.get("pages", [])):
            return project
        # Migrate projects created before bilingual POI metadata was added.
        pois_path = city_dir / "pois.json"
        if not pois_path.is_file():
            return project
        data = json.loads(pois_path.read_text(encoding="utf-8"))
        specs = [
            item if isinstance(item, dict)
            else {"name": str(item), "name_zh": "", "description": ""}
            for item in data.get("pois", [])
        ]
        return write_city_project(city_dir, project.get("city") or city_dir.name, specs)
    pois_path = city_dir / "pois.json"
    if not pois_path.is_file():
        raise FileNotFoundError(f"找不到 {pois_path}")
    data = json.loads(pois_path.read_text(encoding="utf-8"))
    specs = []
    for item in data.get("pois", []):
        specs.append(
            item if isinstance(item, dict)
            else {"name": str(item), "name_zh": "", "description": ""}
        )
    return write_city_project(city_dir, data.get("city") or city_dir.name, specs)
