# POI Icon Prompt Rule: Prompt_无底座

Use this rule to generate the second, base-free prompt variant for POI Icon Studio. It is independent from `poi_icon_prompt_rule.md`; never replace or reinterpret the original rule.

## Input And Paging

- Input: city name plus ordered POI specs containing `name` and optional `description`.
- Split POIs into pages of at most 16.
- Fill each page left-to-right and top-to-bottom in a 4x4 grid.
- A partial final page contains only real POIs; never invent placeholders.
- Preserve the supplied POI order exactly.

## Base-Free Composition

Every occupied cell contains one borderless, freestanding matte-clay icon cluster on pure white.

- No visible floor plane or shared supporting geometry.
- No square, rectangular, circular, or rounded ground plate.
- No platform, podium, pedestal, plinth, slab, tile, diorama block, or presentation foundation.
- No thick grass patch, raised beach tile, extruded water tile, floating land chunk, cutaway soil, or vertical terrain sidewall.
- Buildings end directly at their architectural footprint.
- Mountains and cliffs end in irregular natural silhouettes with no flat underside.
- Water, sand, grass, and garden accents use irregular organic edges with zero visible thickness.
- Objects in a scene stand independently without a shared patch beneath them.

Do not use the phrases `miniature 3D icon`, `objects sit on the floor`, or `studio product photography`. Do not include engine-specific parameters such as `--no`, `--ar`, or `--stylize`.

## Per-POI Description

Preserve a supplied visual description and append one category-specific boundary rule. When no description exists, describe a recognizable freestanding matte-clay interpretation of the POI before appending the rule.

1. Water/coastal POIs: zero-thickness water, sand, and shoreline accents; no beach tile, water slab, sidewall, or terrain block.
2. Terrain/nature POIs: irregular subject silhouette; no flat underside, cutaway soil, terrain wall, or land platform.
3. Architecture POIs: natural architectural footprint; no shared ground plate, lawn slab, display plinth, or presentation base.
4. Other scenes: independent objects in one borderless cluster; no shared floor patch, tile, platform, pedestal, or diorama base.

## Shared Visual Rules

- Isometric view around 45 degrees.
- Pure white `#FFFFFF` background.
- Bright, even, high-angle ambient lighting with nearly no shadows.
- No text, numbers, signage, logos, brand marks, or text-like scribbles.
- Smooth dry unglazed ceramic, cute chunky simplified geometry, no gloss or reflections.
- Consistent camera, scale, material, and lighting across the page.

Finish each page with a validation checklist covering POI order, text, support geometry, terrain thickness, shared ground, white background, shadows, and style consistency.

## Quick Invocation

```text
Read agent_rules/poi_icon_prompt_no_base_rule.md. Generate Prompt_无底座 for the supplied city and ordered POIs, using pages of up to 16. Preserve any supplied visual descriptions, append category-specific base-free geometry constraints, and never modify the original prompt variant.
```
