# POI Icon Sprite Sheet Prompt Rule

Use this rule when the user provides a city name and a list of POIs, and wants complete image-generation prompts for 4x4 city icon sprite sheets.

## Input

The user should provide:

- City name
- POIs, attractions, places, activities, foods, or experiences

Alternatively, the user may provide an online sheet or CSV containing city and POI rows. In that case, first extract the rows with:

```bash
python3 tools/sheet_to_poi_batches.py "SHEET_OR_CSV_URL"
```

Then read:

```text
generated_prompts/agent_prompt_requests.md
```

Use each generated page request as the input for this rule.

The sheet should contain at least these columns:

- `city` or `城市`
- `poi` or `景点`

Optional ordering columns:

- `order`, `序号`, `index`, or `排序`

Example:

```text
City: Singapore
POIs:
1. Merlion Statue
2. Sultan Mosque
3. National Museum of Singapore
...
16. Singapore Flyer
```

## Core Task

Generate one or more complete image-generation prompts.

Only rewrite the section named:

```text
[核心内容 - 16 个指定地标]
```

Keep all other template sections unchanged.

Split POIs into pages of up to 16 items:

- Page 1 = POI 1-16
- Page 2 = POI 17-32
- Page 3 = POI 33-48
- Continue until all POIs are used

If the POI count is not divisible by 16, the remaining POIs must become their own final page.

Within each page, split the page's POIs into a 4x4 grid:

- POI 1-4 = ROW 1
- POI 5-8 = ROW 2
- POI 9-12 = ROW 3
- POI 13-16 = ROW 4

For the final page with fewer than 16 POIs:

- Keep the same ROW structure.
- Fill rows from left to right, top to bottom.
- Only include the actual remaining POIs.
- Do not invent filler POIs.
- Do not add placeholder items such as "empty slot".
- The template may still say "4x4 Grid Sprite Sheet (16 distinct items)" unless the user explicitly asks to change fixed template text.

Each POI line must use this format:

```text
1. **POI English Name** (short visual icon description)
```

## Description Rules

For each POI, write an English visual description suitable for a cute chunky matte clay isometric 3D icon.

Requirements:

1. Describe visible objects, not abstract concepts.
2. Make the subject easy to render as an isolated 3D icon.
3. Mention iconic structure, shape, color, material, or natural elements when useful.
4. For buildings, describe silhouette, roof, towers, facade, spire, dome, or landmark structure.
5. For natural attractions, describe mountains, water, trees, waterfalls, rocks, gardens, flowers, or terrain.
6. For foods, activities, or experiences, describe a compact small scene or representative object.
7. If the POI involves signs, logos, branded objects, billboards, or text-heavy places, describe them as blank colored geometry, abstract geometric version, or no letters.
8. Do not ask for visible text, letters, words, logo text, brand lettering, scribbles, or signage details.
9. Do not add base, platform, podium, stand, pedestal, tile, island, diorama, ground block, or cast-shadow details.
10. Keep each description concise, ideally one sentence or phrase inside parentheses.
11. If the POI is in Chinese, translate it into a natural English POI name before writing the visual description.
12. If fewer than 16 POIs are provided, generate a single page with only those POIs. Do not ask for more unless the user explicitly requires a full 16-item sheet.
13. If more than 16 POIs are provided, generate multiple pages, with up to 16 POIs per page.
14. If the total POI count is not divisible by 16, generate the leftover POIs as their own final page.
15. Label each generated prompt clearly as `PAGE 1`, `PAGE 2`, etc. before the prompt.
16. For each page, preserve the full output template and only rewrite `[核心内容 - 16 个指定地标]` for that page's POIs.

## Output Template

```text
按照这个生图prompt的模板，帮我生产prompt。要求：仅仅改变[核心内容 - 16 个指定地标]部分的prompt，生成以下「{CITY_NAME}」城市的图标内容描述：{POI_LIST}

————————————————————————————————————

[核心布局 - 4x4 网格]
**LAYOUT:** **4x4 Grid Sprite Sheet (16 distinct items).**
**VIEW:** **Isometric view (45 degrees).**
**BACKGROUND:** **Solid White (#FFFFFF).**

[核心修正 - 杀底座 & 杀文字]
**COMPOSITION:** **ISOLATED DIE-CUT 3D ICONS.**
1. **Ground:** **Objects sit DIRECTLY on the white floor.**
2. **Negative:** **NO base, **NO platform, **NO podium, **NO tile, **NO ground block.
3. **Text:** **ABSOLUTELY NO TEXT.** All signs, billboards, and logos must be **BLANK** colored geometry. No letters, no scribbles.

[核心修正 - 无投影 (关键)]
**LIGHTING:** **HIGH ANGLE SOFTBOX LIGHTING.**
positioned **high above (80 degrees)**, **NO** shadows.
3. **Style:** Clean, studio product photography.

[材质与风格 - 哑光粘土]
**STYLE:** **Nanobanana Style + Matte Clay.**
- **Texture:** Smooth, dry, unglazed ceramic. **NO** reflection.
- **Vibe:** Cute, chunky, simplified shapes.

[核心内容 - 16 个指定地标]

**ROW 1 (Left to Right):**
1. **POI 1 English Name** (visual icon description)
2. **POI 2 English Name** (visual icon description)
3. **POI 3 English Name** (visual icon description)
4. **POI 4 English Name** (visual icon description)

**ROW 2 (Left to Right):**
1. **POI 5 English Name** (visual icon description)
2. **POI 6 English Name** (visual icon description)
3. **POI 7 English Name** (visual icon description)
4. **POI 8 English Name** (visual icon description)

**ROW 3 (Left to Right):**
1. **POI 9 English Name** (visual icon description)
2. **POI 10 English Name** (visual icon description)
3. **POI 11 English Name** (visual icon description)
4. **POI 12 English Name** (visual icon description)

**ROW 4 (Left to Right):**
1. **POI 13 English Name** (visual icon description)
2. **POI 14 English Name** (visual icon description)
3. **POI 15 English Name** (visual icon description)
4. **POI 16 English Name** (visual icon description)

[技术参数]
8k, 3D render, octane render, soft lighting --ar 1:1 --stylize 50 --no base, platform, podium, stand, pedestal, ground tile, glossy, shiny, reflection, noise, grain, dirt, high contrast, black shadows


[技术参数 - 负面词拉满]
8k, 3D render, octane render --ar 1:1 --stylize 100 --no long shadows, cast shadows, sunset, low light, text, font, letters, words, signage, logo, brand, base, stand, pedestal, podium, platform, slab, tile, ground block, diorama, island
```

## Quick Invocation For Other Agents

When another agent needs to use this rule, tell it:

```text
Read agent_rules/poi_icon_prompt_rule.md and generate 4x4 POI icon sprite sheet prompts from the city name and POI list. Split POIs into pages of up to 16 items. If the count is not divisible by 16, put the leftover POIs into a separate final page. Preserve the template exactly except for [核心内容 - 16 个指定地标].
```
