# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-08-14

### Fixed

- **Gallery sidecar indexed by cover number, not list position** — when a
  middle cover (e.g. `cover_03.png`) is deleted before `gallery` runs, the
  surviving covers now look up their own title / persisted safe-zone verdict by
  the cover number encoded in the filename (`cover_03.png` -> 3), so they no
  longer shift left one slot and inherit the deleted cover's verdict. The footer
  self-proof stops lying about a set with a gap.
- **Corrupt `.coverlock_titles.json` degrades gracefully** — `read_sidecar`
  now wraps `json.loads` and raises `StylePackError` on a truncated / malformed
  sidecar (e.g. an interrupted `gen`/`regen` write). `gallery` falls back to the
  no-sidecar path instead of crashing with a raw `JSONDecodeError`, and `regen`
  surfaces a clean error instead of a traceback.

### Added

- **Product site** — `web/site.json` (host `coverlock.lei6393.com`) formalized
  as a tracked target file and distribution channel: a static hero +
  CTA-to-GitHub landing surface, distinct from the CLI / Skill surfaces.

## [0.3.0] - 2026-08-07

### Fixed

- **Gallery safe-zone audit honors the pack's font** — the gallery now reads
  each cover's compose-time `title_in_safe_zone` verdict verbatim from the
  sidecar instead of re-deriving it with the platform default font, so a pack
  that sets `layout.title_font` can no longer report a false positive.
- **`layout_title` fallback respects `max_lines`** — the last-resort fallback
  no longer returns an unbounded line count; a title that cannot fit in
  `max_lines` at any size is capped honestly.
- **`--model` override no longer bypasses the lock check** — the original
  pack's lock is verified before the in-memory model override is applied, so a
  pack tampered after lock is still detected.

## [0.2.0] - 2026-08-02

### Fixed

- **Gallery safe-zone count is recomputed** — the footer no longer hardcodes
  every cover as title-in-safe-zone; the verdict is derived from the cover's
  title and the platform safe-zone.
- **Degenerate title fallback no longer lies** — when a title cannot fit even
  at `min_size_pt`, the fallback no longer reports `title_in_safe_zone=True`
  while the drawn text overflows it.

## [0.1.0] - 2026-07-05

### Added

- **Render size-compliant covers** — generate a cover set from a batch of
  titles: each cover is forced to an exact 4:5 or 3:4 canvas and its title is
  typeset entirely inside the Xiaohongshu safe-zone (auto shrink/wrap, never
  clipped). Platform geometry lives in an external, editable rule file
  (`assets/rules/xiaohongshu.yaml`) so sizes/safe-zones change without touching
  code.
- **Pluggable image models** — an offline, deterministic, zero-key `mock` model
  (so `install → gallery` runs with no key and no network), plus bring-your-own-key
  clients for 豆包 Seedream (`doubao-seedream`) and 阿里 Qwen-Image (`qwen-image`).
  Real provider clients import lazily, so a missing/broken one never breaks the
  offline core.
- **Lock a style-pack and regen a single cover** — persist a style-pack (model
  + prompt scaffold + palette + layout) as YAML and hash-lock it with sha256;
  `regen --index N` reuses the same locked pack to redraw one cover while the
  rest stay byte-for-byte identical (in-the-loop control).
- **Consistency gallery** — compose 10 covers from one locked pack into a single
  `gallery.png`: a 10-cell grid with per-cover `size ✓ / safe-zone ✓` corner
  badges and a self-proving footer (`size-compliant N/10 · titles-in-safe-zone
  N/10`).
- **CLI** (`coverlock`) — the full `init → lock → gen → regen → gallery` loop,
  plus `models` and `rules` introspection commands.

[Unreleased]: https://github.com/SuperMarioYL/coverlock/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/SuperMarioYL/coverlock/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/SuperMarioYL/coverlock/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/SuperMarioYL/coverlock/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/SuperMarioYL/coverlock/releases/tag/v0.1.0
