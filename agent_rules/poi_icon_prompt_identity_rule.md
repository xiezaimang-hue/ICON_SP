# POI Icon Prompt Rule: Prompt_本体强化

Use this rule to generate the landmark-faithful icon prompt variant for POI Icon Studio.

Goal:

- Keep the simplified, high-quality icon direction from `Prompt_图标化`.
- Improve POI identity accuracy by preserving the real landmark body's signature color, silhouette, roofline, facade proportion, and key structural cue.
- Avoid generic replacements such as a generic temple, generic tower, generic shopping mall, or generic scenery.

Core rules:

- Keep 4x4 row-major ordering and tail-page behavior.
- Keep solid white background, isometric 45-degree view, high-angle softbox lighting, no shadows, and matte clay material.
- Keep no text, no logo, no signage, no brand marks.
- Use 3 to 6 large primitive volumes when needed for identity accuracy.
- Architectural details must be large structural details, not decorative micro-details.
- Preserve recognizable landmark color blocks, such as gold roofs, red brick, white stone, green glass, blue water, or other real POI colors.
- Keep output readable at 50px mobile icon size.

For each POI:

- If a visual description is supplied, preserve it and append identity constraints.
- For architecture, emphasize roofline, tower/spire/dome/pagoda profile, facade proportion, entrance shape, tier count when visually important, and real color palette.
- For water/coast POIs, emphasize water color, shoreline shape, and one large natural cue.
- For nature/terrain POIs, emphasize mountain, cliff, cave, garden, or vegetation silhouette and natural color blocks.
- For generic activities/scenes, emphasize the most recognizable object type, dominant shape, and key color blocks.

Do not reintroduce `Prompt_无底座`; that variant has been removed from the active product.
