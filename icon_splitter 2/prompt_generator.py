#!/usr/bin/env python3
"""Deterministic page prompts for external 4x4 POI image generation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List


BATCH_SIZE = 16

WATER_KEYWORDS = (
    "beach", "bay", "sea", "ocean", "river", "lake", "water", "waterfall", "pool",
    "harbor", "harbour", "canal", "coast", "island", "waterpark", "water park",
    "海", "海滩", "海湾", "河", "江", "湖", "水", "瀑布", "港", "岛", "游船", "水上",
)
SCENE_OVERRIDE_KEYWORDS = (
    "theme park", "amusement park", "festival", "shopping", "workshop", "nightlife",
    "khao san", "citywalk", "night market", "food", "shooting", "route", "tour",
    "夜市", "美食", "购物", "商圈", "citywalk", "夜游", "射击", "体验", "路线",
)
TERRAIN_KEYWORDS = (
    "mountain", "mount ", "volcano", "cliff", "hill", "terrace", "canyon",
    "valley", "cave", "forest", "park", "garden", "rice field", "rice terrace",
    "山", "火山", "悬崖", "丘", "洞", "森林", "公园", "花园", "梯田", "自然",
)
ARCHITECTURE_KEYWORDS = (
    "temple", "palace", "tower", "museum", "church", "cathedral", "mosque",
    "shrine", "pagoda", "building", "hall", "gate", "bridge", "monument",
    "statue", "airport", "market", "chapel", "fort", "castle", "memorial",
    "寺", "庙", "宫", "皇宫", "王宫", "塔", "博物馆", "教堂", "清真寺", "神社",
    "佛", "佛寺", "佛塔", "建筑", "大厅", "门", "桥", "纪念", "雕像", "机场",
    "市场", "古迹", "历史", "遗迹", "郑王庙", "玉佛寺", "大皇宫",
)

TRANSLATION_OVERRIDES = {
    "郑王庙": "Wat Arun",
    "大皇宫": "Grand Palace",
    "玉佛寺": "Temple of the Emerald Buddha",
    "湄南河游船": "Chao Phraya River Cruise",
    "曼谷水上市场": "Bangkok Floating Market",
    "美攻": "Maeklong Railway Market",
    "考山": "Khao San Road",
    "是隆": "Silom",
    "暹罗商圈Citywalk": "Siam District Citywalk",
    "曼谷逛寺庙": "Bangkok Temple Tour",
    "曼谷+芭提雅": "Bangkok and Pattaya",
    "曼谷夜游": "Bangkok Night Tour",
    "夜市美食": "Night Market Food",
    "曼谷射击": "Bangkok Shooting Experience",
    "曼谷海军射击场": "Bangkok Navy Shooting Range",
    "曼谷历史古迹": "Bangkok Historical Sites",
    "东京塔": "Tokyo Tower",
    "浅草寺": "Senso-ji Temple",
    "明治神宫": "Meiji Shrine",
    "涩谷": "Shibuya",
    "新宿": "Shinjuku",
    "银座": "Ginza",
    "上野公园": "Ueno Park",
    "皇居": "Tokyo Imperial Palace",
}

PHRASE_TRANSLATIONS = (
    ("曼谷", "Bangkok"),
    ("东京", "Tokyo"),
    ("芭提雅", "Pattaya"),
    ("首尔", "Seoul"),
    ("巴厘岛", "Bali"),
    ("夜市", "Night Market"),
    ("美食", "Food"),
    ("水上市场", "Floating Market"),
    ("商圈", "Shopping District"),
    ("古迹", "Historical Sites"),
    ("历史", "Historical"),
    ("游船", "River Cruise"),
    ("夜游", "Night Tour"),
    ("射击场", "Shooting Range"),
    ("射击", "Shooting Experience"),
    ("逛寺庙", "Temple Tour"),
    ("寺庙", "Temple"),
    ("神社", "Shrine"),
    ("清真寺", "Mosque"),
    ("博物馆", "Museum"),
    ("大皇宫", "Grand Palace"),
    ("皇宫", "Palace"),
    ("王宫", "Palace"),
    ("佛寺", "Buddhist Temple"),
    ("佛塔", "Pagoda"),
    ("教堂", "Church"),
    ("大桥", "Bridge"),
    ("公园", "Park"),
    ("花园", "Garden"),
    ("市场", "Market"),
    ("海滩", "Beach"),
    ("海湾", "Bay"),
    ("火山", "Volcano"),
    ("山", "Mountain"),
    ("河", "River"),
    ("塔", "Tower"),
    ("寺", "Temple"),
    ("庙", "Temple"),
    ("宫", "Palace"),
)


def chunk_specs(specs: List[dict], size: int = BATCH_SIZE):
    return [specs[index:index + size] for index in range(0, len(specs), size)]


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def english_prompt_name(name: str) -> str:
    """Return a deterministic English name for image prompts without network calls."""
    original = str(name or "").strip()
    if not original:
        return ""
    if not _has_cjk(original):
        return original
    if original in TRANSLATION_OVERRIDES:
        return TRANSLATION_OVERRIDES[original]
    translated = original
    for source, target in PHRASE_TRANSLATIONS:
        translated = translated.replace(source, f" {target} ")
    translated = re.sub(r"[+＋/&、，,]+", " and ", translated)
    translated = re.sub(r"[^\w\s'-]", " ", translated)
    translated = re.sub(r"\s+", " ", translated).strip()
    if translated and not _has_cjk(translated):
        return translated
    return original


def _prompt_name(spec: dict) -> str:
    candidate = str(spec.get("prompt_name", "")).strip()
    if candidate:
        return candidate
    return english_prompt_name(str(spec.get("name", "")).strip())


def _normalize_spec(spec: dict) -> dict:
    name = str(spec.get("name", "")).strip()
    name_zh = str(spec.get("name_zh", "")).strip()
    prompt_name = str(spec.get("prompt_name", "")).strip() or english_prompt_name(name)
    if _has_cjk(name) and not name_zh:
        name_zh = name
    item = {
        "name": name,
        "name_zh": name_zh,
        "prompt_name": prompt_name,
        "description": str(spec.get("description", "")).strip(),
    }
    source_id = str(spec.get("id") or spec.get("source_id") or "").strip()
    if source_id:
        item["id"] = source_id
    return item


def _description(spec: dict) -> str:
    supplied = str(spec.get("description", "")).strip()
    if supplied:
        return supplied
    name = _prompt_name(spec)
    return (
        f"A recognizable miniature 3D icon interpretation of {name}, "
        "simplified around its most iconic visible architectural, natural, food, or activity features"
    )


def _iconic_description(spec: dict) -> str:
    supplied = str(spec.get("description", "")).strip()
    name = _prompt_name(spec)
    subject = supplied.rstrip(" .") if supplied else (
        f"A clear icon-like matte-clay interpretation of {name}, using only its most recognizable visual cue"
    )
    return (
        f"{subject}; build it from 2 to 4 oversized primitive volumes only, one dominant silhouette, "
        "very few supporting blocks, no small props, no tiny accessories, no micro-details, "
        "toy-like chunky massing, readable at 50px mobile icon size"
    )


def _base_free_category(spec: dict) -> str:
    text = f"{spec.get('name', '')} {spec.get('prompt_name', '')} {spec.get('description', '')}".casefold()
    if any(keyword in text for keyword in SCENE_OVERRIDE_KEYWORDS):
        return "scene"
    if any(keyword in text for keyword in WATER_KEYWORDS):
        return "water"
    if any(keyword in text for keyword in TERRAIN_KEYWORDS):
        return "terrain"
    if any(keyword in text for keyword in ARCHITECTURE_KEYWORDS):
        return "architecture"
    return "scene"


def _base_free_description(spec: dict) -> str:
    supplied = str(spec.get("description", "")).strip()
    name = _prompt_name(spec)
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
            rows.append(f"{item_index}. **{_prompt_name(spec)}** ({description_fn(spec)})")
        rows.append("")
    return chr(10).join(rows).rstrip()


def _project_spec(spec: dict) -> dict:
    """Keep optional metadata that downstream review/export UI can use."""
    item = {
        "name": spec["name"],
        "name_zh": str(spec.get("name_zh", "")).strip(),
        "prompt_name": _prompt_name(spec),
        "description": str(spec.get("description", "")).strip(),
    }
    source_id = str(spec.get("id") or spec.get("source_id") or "").strip()
    if source_id:
        item["id"] = source_id
    return item


def generate_page_prompt(city: str, specs: List[dict], page: int) -> str:
    specs = [_normalize_spec(spec) for spec in specs]
    poi_names = ", ".join(_prompt_name(spec) for spec in specs)
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


def generate_iconic_prompt(city: str, specs: List[dict], page: int) -> str:
    specs = [_normalize_spec(spec) for spec in specs]
    poi_names = ", ".join(_prompt_name(spec) for spec in specs)
    item_count = len(specs)
    if item_count == BATCH_SIZE:
        layout_rule = (
            "**LAYOUT:** **4x4 Grid Sprite Sheet with EXACTLY 16 distinct icon items.**\n"
            "- Fill all 16 cells. No missing icons, no merged cells, no empty cells.\n"
            "- Arrange exactly four rows and four columns, left-to-right and top-to-bottom."
        )
        validation_scope = "all 16 cells"
    else:
        empty_count = BATCH_SIZE - item_count
        layout_rule = (
            f"**LAYOUT:** **4x4 Grid Sprite Sheet with EXACTLY {item_count} distinct icon items.**\n"
            f"- Draw only the first {item_count} row-major cells, left-to-right and top-to-bottom.\n"
            f"- Leave the remaining {empty_count} cells completely blank pure white.\n"
            "- Do not invent filler icons and do not rearrange the supplied order."
        )
        validation_scope = f"the first {item_count} occupied cells"
    return f"""CITY: {city}
PAGE: {page}
PROMPT VERSION: Prompt_图标化
POIS IN ORDER: {poi_names}

[核心布局 - 4x4 网格]
{layout_rule}
**VIEW:** **Isometric view (45 degrees).**
**BACKGROUND:** **Solid White (#FFFFFF).**
- Exactly one centered icon cluster per occupied cell.
- Keep generous white space between cells.
- NO grid lines, borders, frames, labels, or separators.

[核心方向 - 更像ICON，低细节但高质量]
**STYLE GOAL:** **HIGH-QUALITY SIMPLIFIED ICONS, NOT DETAILED MINIATURE MODELS.**
1. Preserve image quality, clean rendering, 8k-level sharp edges, and polished 3D material.
2. Reduce visual complexity aggressively: use **2 to 4 oversized primitive volumes** per icon whenever possible.
3. Make each icon recognizable by **one dominant big silhouette**; supporting pieces must be large and few.
4. Prefer blocky toy-like massing over miniature scenery. Use big cylinders, rounded cubes, domes, cones, arches, slabs, and simple blobs.
5. Avoid tiny windows, dense decorations, many small props, thin lines, busy textures, realistic clutter, layered trim, railings, fences, repeated panels, and small accessory objects.
6. Prefer chunky geometry, thick proportions, rounded forms, clear color blocking, and large uninterrupted surfaces.
7. Each icon must remain readable when reduced to a **50px mobile icon**.

[核心修正 - 杀底座 & 杀文字]
**COMPOSITION:** **ISOLATED DIE-CUT 3D ICONS.**
1. **Ground:** **Objects sit DIRECTLY on the white floor.**
2. **Negative:** **NO base, NO platform, NO podium, NO tile, NO ground block.**
3. **Text:** **ABSOLUTELY NO TEXT.** All signs, billboards, and logos must be **BLANK** colored geometry. No letters, no scribbles.

[核心修正 - 无投影]
**LIGHTING:** **HIGH ANGLE SOFTBOX LIGHTING.**
Positioned **high above (80 degrees)**, **NO harsh shadows.**
**Style:** Clean, high-quality product icon render.

[材质与风格 - 哑光粘土]
**STYLE:** **Nanobanana Style + Matte Clay.**
- **Texture:** Smooth, dry, unglazed ceramic. **NO reflection.**
- **Vibe:** Cute, chunky, simplified icon shapes.
- Keep colors bright and readable; avoid dark/black-heavy details unless essential.

[核心内容 - 16 个指定地标]

{_prompt_rows(specs, _iconic_description)}

[FINAL VALIDATION]
Before rendering, verify {validation_scope}:
1. Correct POI order, row-major from left to right.
2. Every icon reads as a simple app-style 3D icon, not a highly detailed model.
3. No icon relies on tiny text, tiny parts, thin lines, or dense decoration for recognition.
4. Each icon is built mostly from 2 to 4 large primitive volumes, not many small pieces.
5. All icons remain clear at 50px mobile display size.
6. No text, logos, letters, or number marks are visible.
7. No base, platform, podium, stand, pedestal, ground tile, or ground block.
8. Lighting is clean and high quality, without harsh dark shadows.

[技术参数]
8k, high-quality 3D icon render, octane render, clean edges, soft lighting, chunky primitive volumes, toy-like massing --ar 1:1 --stylize 50 --no tiny details, micro details, dense details, many small objects, small props, tiny accessories, thin lines, railings, fences, repeated panels, photorealistic texture, busy texture, text, font, letters, words, signage, logo, brand, base, platform, podium, stand, pedestal, ground tile, glossy, shiny, reflection, noise, grain, dirt, high contrast, black shadows
"""



def _identity_description(spec: dict) -> str:
    supplied = str(spec.get("description", "")).strip()
    name = _prompt_name(spec)
    subject = supplied.rstrip(" .") if supplied else (
        f"A landmark-faithful simplified 3D icon of {name}, based on its real-world signature silhouette"
    )
    category = _base_free_category(spec)
    if category == "architecture":
        guidance = (
            "preserve the real landmark's main silhouette, roof mass, tower/dome/pagoda mass when present, "
            "simple facade proportion, and recognizable color palette; express it with low-detail blocky planes"
        )
    elif category == "water":
        guidance = (
            "preserve the real place's defining water/coast silhouette, water color, shoreline shape, and one large natural cue"
        )
    elif category == "terrain":
        guidance = (
            "preserve the real place's defining mountain, cliff, cave, garden, or vegetation silhouette and natural color blocks"
        )
    else:
        guidance = (
            "preserve the POI's most recognizable object type, dominant shape, key color blocks, and iconic visual cue"
        )
    return (
        f"{subject}; {guidance}; simplify into 3 to 5 chunky matte-clay volumes, "
        "large readable shapes, flat broad surfaces, faithful landmark colors, no invented generic replacement, no text, no tiny details"
    )


def generate_identity_prompt(city: str, specs: List[dict], page: int) -> str:
    specs = [_normalize_spec(spec) for spec in specs]
    poi_names = ", ".join(_prompt_name(spec) for spec in specs)
    item_count = len(specs)
    if item_count == BATCH_SIZE:
        layout_rule = (
            "**LAYOUT:** **4x4 Grid Sprite Sheet with EXACTLY 16 distinct icon items.**\n"
            "- Fill all 16 cells. No missing icons, no merged cells, no empty cells.\n"
            "- Arrange exactly four rows and four columns, left-to-right and top-to-bottom."
        )
        validation_scope = "all 16 cells"
    else:
        empty_count = BATCH_SIZE - item_count
        layout_rule = (
            f"**LAYOUT:** **4x4 Grid Sprite Sheet with EXACTLY {item_count} distinct icon items.**\n"
            f"- Draw only the first {item_count} row-major cells, left-to-right and top-to-bottom.\n"
            f"- Leave the remaining {empty_count} cells completely blank pure white.\n"
            "- Do not invent filler icons and do not rearrange the supplied order."
        )
        validation_scope = f"the first {item_count} occupied cells"
    return f"""CITY: {city}
PAGE: {page}
PROMPT VERSION: Prompt_本体强化
POIS IN ORDER: {poi_names}

[核心布局 - 4x4 网格]
{layout_rule}
**VIEW:** **Isometric view (45 degrees).**
**BACKGROUND:** **Solid White (#FFFFFF).**
- Exactly one centered icon cluster per occupied cell.
- Keep generous white space between cells.
- NO grid lines, borders, frames, labels, or separators.

[核心方向 - 标志性本体还原 + 图标化]
**STYLE GOAL:** **LANDMARK-FAITHFUL SIMPLIFIED 3D ICONS.**
1. Keep the current iconified direction: chunky matte-clay volumes, clean rendering, readable at 50px mobile size.
2. Compared with Prompt_图标化, prioritize the real POI body's visual identity: **signature silhouette, dominant color palette, and one key structural cue.**
3. For buildings and landmarks, use low-detail block modeling: large roof mass, main tower/dome/pagoda mass, simple facade block, and broad color panels.
4. Use **3 to 5 large primitive volumes** when needed for accuracy. Do not over-simplify into a generic temple, generic tower, generic mall, or generic scenery.
5. Details must stay broad and minimal. Avoid tiny windows, railings, text, signs, ornaments, micro-patterns, repeated panels, and clutter.
6. Colors should be faithful and slightly vivid: preserve gold roofs, red brick, white stone, green glass, blue water, etc. Avoid dark/black-heavy output unless the real POI requires it.

[核心修正 - 杀底座 & 杀文字]
**COMPOSITION:** **ISOLATED DIE-CUT 3D ICONS.**
1. **Ground:** **Objects sit DIRECTLY on the white floor.**
2. **Negative:** **NO base, NO platform, NO podium, NO tile, NO ground block.**
3. **Text:** **ABSOLUTELY NO TEXT.** All signs, billboards, and logos must be **BLANK** colored geometry. No letters, no scribbles.

[核心修正 - 无投影]
**LIGHTING:** **HIGH ANGLE SOFTBOX LIGHTING.**
Positioned **high above (80 degrees)**, **NO shadows.**
**Style:** Clean, studio product photography.

[材质与风格 - 哑光粘土]
**STYLE:** **Nanobanana Style + Matte Clay.**
- **Texture:** Smooth, dry, unglazed ceramic. **NO reflection.**
- **Vibe:** Cute, chunky, simplified icon shapes.
- Keep landmark colors clear, vivid, and recognizable.

[核心内容 - 16 个指定地标]

{_prompt_rows(specs, _identity_description)}

[FINAL VALIDATION]
Before rendering, verify {validation_scope}:
1. Correct POI order, row-major from left to right.
2. Every icon is recognizable as the supplied POI, not a generic replacement.
3. Architecture-heavy POIs preserve signature color and main silhouette through low-detail blocky masses.
4. Each icon remains simplified and readable at 50px, with broad surfaces only.
5. No text, logos, letters, numbers, signage, base, platform, podium, tile, or ground block.
6. Lighting, material, and white background match the original prompt style.

[技术参数]
8k, high-quality 3D icon render, octane render, clean edges, soft lighting, faithful landmark silhouette, accurate landmark colors, chunky matte clay, low-detail blocky forms, broad flat surfaces --ar 1:1 --stylize 50 --no generic building, generic temple, wrong landmark, wrong color, tiny details, micro details, dense details, many small objects, small props, tiny accessories, thin lines, railings, fences, repeated panels, photorealistic texture, busy texture, text, font, letters, words, signage, logo, brand, base, platform, podium, stand, pedestal, ground tile, glossy, shiny, reflection, noise, grain, dirt, high contrast, black shadows
"""


def write_city_project(city_dir: Path, city: str, specs: List[dict]) -> dict:
    specs = [_normalize_spec(spec) for spec in specs]
    prompts_dir = city_dir / "prompts"
    iconic_dir = prompts_dir / "Prompt_图标化"
    identity_dir = prompts_dir / "Prompt_本体强化"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    iconic_dir.mkdir(parents=True, exist_ok=True)
    identity_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for page_index, page_specs in enumerate(chunk_specs(specs), 1):
        prompt_path = prompts_dir / f"page_{page_index:02d}.txt"
        iconic_path = iconic_dir / f"page_{page_index:02d}.txt"
        identity_path = identity_dir / f"page_{page_index:02d}.txt"
        prompt_path.write_text(generate_page_prompt(city, page_specs, page_index), encoding="utf-8")
        iconic_path.write_text(
            generate_iconic_prompt(city, page_specs, page_index), encoding="utf-8"
        )
        identity_path.write_text(
            generate_identity_prompt(city, page_specs, page_index), encoding="utf-8"
        )
        pages.append({
            "page": page_index,
            "start_index": (page_index - 1) * BATCH_SIZE + 1,
            "end_index": (page_index - 1) * BATCH_SIZE + len(page_specs),
            "poi_count": len(page_specs),
            "pois": [spec["name"] for spec in page_specs],
            "poi_specs": [_project_spec(spec) for spec in page_specs],
            "described_count": sum(1 for spec in page_specs if spec.get("description")),
            "prompt": str(prompt_path.resolve()),
            "prompt_iconic": str(iconic_path.resolve()),
            "prompt_identity": str(identity_path.resolve()),
            "expected_batch": f"batch{page_index}.png",
        })
    project = {
        "version": 5,
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
    """Refresh generated prompt variants and add prompt English names."""
    changed = False
    iconic_dir = city_dir / "prompts" / "Prompt_图标化"
    identity_dir = city_dir / "prompts" / "Prompt_本体强化"
    iconic_dir.mkdir(parents=True, exist_ok=True)
    identity_dir.mkdir(parents=True, exist_ok=True)
    city = project.get("city") or city_dir.name
    for page in project.get("pages", []):
        specs = [_normalize_spec(spec) for spec in page.get("poi_specs", [])]
        if not specs:
            continue
        if page.get("poi_specs") != specs:
            page["poi_specs"] = specs
            changed = True
        page_index = int(page["page"])
        original_path = Path(page.get("prompt", ""))
        if not original_path.is_file():
            original_path = city_dir / "prompts" / f"page_{page_index:02d}.txt"
            page["prompt"] = str(original_path.resolve())
            changed = True
        original_path.write_text(
            generate_page_prompt(city, specs, page_index), encoding="utf-8"
        )
        if "prompt_no_base" in page:
            page.pop("prompt_no_base", None)
            changed = True
        iconic_path = iconic_dir / f"page_{page_index:02d}.txt"
        iconic_path.write_text(
            generate_iconic_prompt(city, specs, page_index), encoding="utf-8"
        )
        resolved_iconic = str(iconic_path.resolve())
        if page.get("prompt_iconic") != resolved_iconic:
            page["prompt_iconic"] = resolved_iconic
            changed = True
        identity_path = identity_dir / f"page_{page_index:02d}.txt"
        identity_path.write_text(
            generate_identity_prompt(city, specs, page_index), encoding="utf-8"
        )
        resolved_identity = str(identity_path.resolve())
        if page.get("prompt_identity") != resolved_identity:
            page["prompt_identity"] = resolved_identity
            changed = True
    if project.get("version", 1) < 5:
        project["version"] = 5
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
