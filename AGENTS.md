# Agent Instructions

Before modifying this repository, read [`AGENT_FEATURE_GUIDE.md`](AGENT_FEATURE_GUIDE.md).

That document is the source of truth for the current POI prompt, spreadsheet import, icon splitting, optional Codex review, human evaluation, localhost GUI, macOS packaging, data schemas, defaults, tests, and known limitations.

Key invariants:

- AI image review is optional and disabled by default.
- Non-AI splitting must never consume Codex/Plus usage.
- AI review failures must not block cropped image output.
- The GUI server must bind only to `127.0.0.1`.
- Preserve compatibility with string-only `pois.json` entries.
- Do not commit or edit `inputs/`, `outputs/`, `.venv/`, `build/`, or `dist/` artifacts unless explicitly requested.
