#!/usr/bin/env python3
"""Deterministic page prompts for external 4x4 POI image generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List


BATCH_SIZE = 16

WATER_KEYWORDS = (
    "beach", "bay", "sea", "ocean", "river", "lake", "waterfall", "pool",
    "harbor", "harbour", "canal", "coast", "island", "waterpark", "water park",
)
TERRAIN_KEYWORDS = (
    "mountain", "mount ", "volcano", "cliff", "hill", "terrace", "canyon",
    "valley", "cave", "forest", "park", "garden", "rice field", "rice terrace",
)
ARCHITECTURE_KEYWORDS = (
    "temple", "palace", "tower", "museum", "church", "cathedral", "mosque",
    "shrine", "pagoda", "building", "hall", "gate", "bridge", "monument",
    "statue", "airport", "market", "chapel", "fort", "castle", "memorial",
)


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


def _base_free_category(spec: dict) -> str:
    text = f"{spec.get('name', '')} {spec.get('description', '')}".casefold()
    if any(keyword in text for keyword in WATER_KEYWORDS):
        return "water"
    if any(keyword in text for keyword in TERRAIN_KEYWORDS):
        return "terrain"
    if any(keyword in text for keyword in ARCHITECTURE_KEYWORDS):
        return "architecture"
    return "scene"


def _base_free_description(spec: dict) -> str:
    supplied = str(spec.get("description", "")).strip()
    name = spec["name"]
    category = _base_free_category(spec)
    if supplied:
        subject = supplied.rstrip(" .")
    elif category == "water":
        subject = f"A recognizable freestanding matte-clay icon of {name} using its iconic coastal or water features"
    elif category == "terrain":
        subject = f"A recognizable freestanding matte-clay icon of {name} using its iconic natural silhouette and vegetation"
    elif category == "architecture":
        subject = f"A recognizable freestanding matte-clay icon of {name} using its most iconic architectural silhouette"
    else:
        subject = f"A recognizable freestanding matte-clay icon cluster of {name} using its most iconic visible objects"

    suffixes = {
        "water": (
            "water, sand, and shoreline accents have irregular organic edges with zero visible thickness; "
            "no beach tile, water slab, vertical sidewall, or terrain block"
        ),
        "terrain": (
            "the natural form ends in an irregular subject silhouette; no flat underside, cutaway soil, "
            "vertical terrain wall, or land platform"
        ),
        "architecture": (
            "the structure ends directly at its architectural footprint; no shared ground plate, lawn slab, "
            "display plinth, or presentation base"
        ),
        "scene": (
            "all objects stand independently as one borderless cluster; no shared floor patch, ground tile, "
            "platform, pedestal, or diorama base"
        ),
    }
    return f"{subject}; {suffixes[category]}"


def _prompt_rows(specs: List[dict], description_fn) -> str:
    rows = []
    for row_index in range(4):
        row_specs = specs[row_index * 4:(row_index + 1) * 4]
        if not row_specs:
            continue
        rows.append(f"**ROW {row_index + 1} (Left to Right):**")
        for item_index, spec in enumerate(row_specs, 1):
            rows.append(f"{item_index}. **{spec['name']}** ({description_fn(spec)})")
        rows.append("")
    return chr(10).join(rows).rstrip()


def generate_page_prompt(city: str, specs: List[dict], page: int) -> str:
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

{_prompt_rows(specs, _description)}

[技术参数]
8k, 3D render, octane render, soft lighting --ar 1:1 --stylize 50 --no base, platform, podium, stand, pedestal, ground tile, glossy, shiny, reflection, noise, grain, dirt, high contrast, black shadows

[技术参数 - 负面词拉满]
8k, 3D render, octane render --ar 1:1 --stylize 100 --no long shadows, cast shadows, sunset, low light, text, font, letters, words, signage, logo, brand, base, stand, pedestal, podium, platform, slab, tile, ground block, diorama, island
"""


def generate_base_free_prompt(city: str, specs: List[dict], page: int) -> str:
    poi_names = ", ".join(spec["name"] for spec in specs)
    return f"""CITY: {city}
PAGE: {page}
PROMPT VERSION: Prompt_无底座
POIS IN ORDER: {poi_names}

[核心布局 - 4x4 网格]
**LAYOUT:** **4x4 Grid Sprite Sheet (up to 16 distinct items).**
**VIEW:** **Isometric view (45 degrees).**
**BACKGROUND:** **Solid Pure White (#FFFFFF).**
- Exactly one centered icon cluster per occupied cell.
- Keep generous white space between cells.
- NO grid lines, borders, frames, labels, or separators.

[核心构图 - 无底座]
**COMPOSITION:** **BORDERLESS FREESTANDING 3D ICON CLUSTERS.**
1. There is **NO visible ground plane** and **NO shared supporting geometry**.
2. The lower contour of every icon must belong naturally to the depicted subject.
3. Buildings end directly at their architectural footprint.
4. Mountains and cliffs use irregular natural silhouettes with no flat underside or cutaway soil.
5. Water, sand, grass, and garden accents use irregular organic edges with zero visible thickness.
6. Objects in a scene stand independently without a shared patch beneath them.

**ABSOLUTELY FORBIDDEN GEOMETRY:**
- square, rectangular, circular, or rounded ground plates
- display bases, platforms, podiums, pedestals, plinths, slabs, or tiles
- thick grass patches, raised beach tiles, or extruded water tiles
- cutaway terrain, visible soil layers, vertical terrain sidewalls, or floating land chunks
- diorama blocks, uniform footprints, or presentation foundations beneath the subject

[核心修正 - 无文字]
**TEXT:** **ABSOLUTELY NO TEXT.**
- No letters, words, numbers, signage, logos, brand marks, or text-like scribbles.
- Any unavoidable sign or billboard must be blank colored geometry.

[核心修正 - 无投影]
**LIGHTING:** Bright, even, high-angle ambient lighting.
- Nearly shadowless, with NO cast shadows and NO dark contact shadows.
- NO visible horizon and NO dramatic contrast.

[材质与风格 - 哑光粘土]
**STYLE:** **Nanobanana Style + Matte Clay.**
- Smooth, dry, unglazed ceramic texture.
- Cute, chunky, simplified geometry with recognizable silhouettes.
- NO gloss, reflection, metallic shine, noise, grain, or dirt.
- Consistent scale, camera angle, material, and lighting across all icons.
- Isolated catalog icons, never diorama scenes.

[核心内容 - 16 个指定地标]

{_prompt_rows(specs, _base_free_description)}

[FINAL VALIDATION]
Before rendering, verify every occupied cell:
1. The correct POI is present in the correct row-major position.
2. No text or logo is visible.
3. No square, rectangular, circular, or rounded support shape exists.
4. No terrain has visible thickness, cutaway soil, or vertical sidewalls.
5. No shared ground plate appears beneath any composition.
6. Natural scenery uses irregular zero-thickness accents instead of diorama blocks.
7. The background remains pure white and lighting remains nearly shadowless.
8. All icons share the same matte-clay style and isometric camera angle.

Square image, high-resolution 3D render, clean edges, pure white background.
"""


def write_city_project(city_dir: Path, city: str, specs: List[dict]) -> dict:
    prompts_dir = city_dir / "prompts"
    no_base_dir = prompts_dir / "Prompt_无底座"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    no_base_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for page_index, page_specs in enumerate(chunk_specs(specs), 1):
        prompt_path = prompts_dir / f"page_{page_index:02d}.txt"
        no_base_path = no_base_dir / f"page_{page_index:02d}.txt"
        prompt_path.write_text(generate_page_prompt(city, page_specs, page_index), encoding="utf-8")
        no_base_path.write_text(
            generate_base_free_prompt(city, page_specs, page_index), encoding="utf-8"
        )
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
            "prompt_no_base": str(no_base_path.resolve()),
            "expected_batch": f"batch{page_index}.png",
        })
    project = {
        "version": 2,
        "city": city,
        "total_pois": len(specs),
        "page_count": len(pages),
        "pages": pages,
    }
    (city_dir / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return project


def _upgrade_prompt_variants(city_dir: Path, project: dict) -> dict:
    """Add the no-base variant to an existing bilingual project without rewriting the original."""
    changed = False
    no_base_dir = city_dir / "prompts" / "Prompt_无底座"
    no_base_dir.mkdir(parents=True, exist_ok=True)
    city = project.get("city") or city_dir.name
    for page in project.get("pages", []):
        specs = page.get("poi_specs", [])
        if not specs:
            continue
        page_index = int(page["page"])
        original_path = Path(page.get("prompt", ""))
        if not original_path.is_file():
            original_path = city_dir / "prompts" / f"page_{page_index:02d}.txt"
            original_path.write_text(
                generate_page_prompt(city, specs, page_index), encoding="utf-8"
            )
            page["prompt"] = str(original_path.resolve())
            changed = True
        no_base_path = no_base_dir / f"page_{page_index:02d}.txt"
        if not no_base_path.is_file():
            no_base_path.write_text(
                generate_base_free_prompt(city, specs, page_index), encoding="utf-8"
            )
        resolved = str(no_base_path.resolve())
        if page.get("prompt_no_base") != resolved:
            page["prompt_no_base"] = resolved
            changed = True
    if project.get("version", 1) < 2:
        project["version"] = 2
        changed = True
    if changed:
        (city_dir / "project.json").write_text(
            json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return project


def load_city_project(city_dir: Path) -> dict:
    path = city_dir / "project.json"
    if path.is_file():
        project = json.loads(path.read_text(encoding="utf-8"))
        if all("poi_specs" in page for page in project.get("pages", [])):
            return _upgrade_prompt_variants(city_dir, project)
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
