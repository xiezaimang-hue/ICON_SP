# POI Icon Prompt Rule: Prompt_图标化

Use this rule to generate the simplified-icon prompt variant for POI Icon Studio. It is independent from the original prompt and from `Prompt_本体强化`.

## Goal

Generate high-quality 3D matte-clay city/POI icon sprite sheets that are less detailed and more readable as small mobile icons. Do not reduce image quality, resolution, material quality, or rendering polish. Reduce only visual complexity.

## Layout

- Split POIs into pages of up to 16 items.
- Full pages must render exactly 16 separate icons in a 4x4 grid.
- Tail pages must render exactly the remaining POI count in the first row-major cells, with all unused cells blank pure white.
- Preserve row-major order: left-to-right, top-to-bottom.

## Style

- Keep isometric 45-degree view, pure white background, matte-clay material, cute chunky shapes, and high-quality 3D rendering.
- Each icon should use 2 to 4 oversized primitive volumes whenever possible.
- Use one dominant big silhouette plus very few large supporting blocks.
- Favor bold silhouettes, thick geometry, rounded forms, clear color blocking, and toy-like chunky massing.
- Icons must remain recognizable at around 50px mobile display size.

## Avoid

- Tiny windows, dense decorations, many small props, tiny accessories, thin lines, railings, fences, repeated panels, photorealistic clutter, realistic fine texture, busy material details, text, logos, letters, numbers, heavy shadows, glossy reflections, and base/platform/podium geometry.

## POI Descriptions

Preserve supplied visual descriptions, then append a low-detail icon-readability constraint:

`build it from 2 to 4 oversized primitive volumes only, one dominant silhouette, very few supporting blocks, no small props, no tiny accessories, no micro-details, toy-like chunky massing, readable at 50px mobile icon size`

When no description exists, describe a clear icon-like matte-clay interpretation of the POI using only the most recognizable visual cue, then append the same constraint.
