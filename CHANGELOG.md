# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/SuperMarioYL/coverlock/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SuperMarioYL/coverlock/releases/tag/v0.1.0
