<div align="right"><sub><b>English</b>&nbsp;&nbsp;⇄&nbsp;&nbsp;<a href="./README.md">中文</a></sub></div>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/hero-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/hero-light.svg">
  <img src="./assets/hero-light.svg" width="880" alt="CoverLock — lock an account-level cover style-pack, render size-compliant, safe-zone-aware Xiaohongshu cover sets">
</picture>

<p><sub>CoverLock is a cover-set Skill for Xiaohongshu (小红书) creators: lock an account-level style-pack once, and every subsequent cover inherits the same look, is always size-compliant, and always keeps its title inside the safe-zone — you can even redraw a single cover while keeping the whole style. The killer self-proof is a consistency gallery of 10 covers from one locked style-pack.</sub></p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/version-0.1.0-5E5CE6.svg" alt="Version 0.1.0">
  <a href="https://github.com/SuperMarioYL/coverlock/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/SuperMarioYL/coverlock/ci.yml?label=CI&logo=github" alt="CI"></a>
  <img src="https://img.shields.io/badge/PRs-welcome-10A37F.svg" alt="PRs welcome">
  <img src="https://img.shields.io/badge/Skill-cover--sets-8985FF.svg" alt="Skill">
</p>

CoverLock is not one more "one prompt, one image" text-to-image box. It freezes **an account's whole visual language** into a `lock`-able, reusable, shareable **style-pack** asset: once locked, `gen` / `regen` reuse the exact same `model + prompt scaffold + palette + layout`, so every cover across posts and across days converges to one look — the same lane as guizang's (op7418) social-covers Skill, but pushing the named Xiaohongshu-cover surface one step further: **account-level style lock + enforced 4:5 / 3:4 sizing + enforced title safe-zone.**

The main visual comes from a domestic image model you bring your own key for (Doubao Seedream / Alibaba Qwen-Image). There is also a built-in zero-key, offline, deterministic `mock` model — so `install → gallery` runs end to end with no key and no network.

<h2><img src="https://api.iconify.design/tabler:topology-star-3.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Architecture</h2>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/atlas-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/atlas-light.svg">
  <img src="./assets/atlas-light.svg" width="880" alt="Flow: locked style-pack → domestic image model / mock → compose (sizing + title safe-zone) → 10 covers → consistency gallery">
</picture>

A single-process CLI — no server, no database, all local. **The owned value lives entirely in the offline layer** (`compose` / `rules` / `stylepack` / `gallery`): size compliance, the title safe-zone, and style-pack locking depend on no specific model, so they keep working even if a model API raises prices, shuts down, or is swapped for another provider. The model only produces the *text-free main visual* — a pluggable periphery. Platform sizing / safe-zone rules live in an external YAML (`assets/rules/xiaohongshu.yaml`): change the rules by editing config, not code.

<h2><img src="https://api.iconify.design/tabler:download.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Install</h2>

```bash
pip install coverlock
```

Requires Python 3.12+. From source: `git clone … && cd coverlock && pip install -e .`.

<h2><img src="https://api.iconify.design/tabler:rocket.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Quickstart</h2>

Three commands — zero key, offline — from install to the consistency gallery:

```bash
coverlock init my-pack --desc "minimal magazine look, Morandi palette, generous whitespace"
coverlock gen --pack my-pack.yaml --titles titles.txt --model mock   # render a vertical cover set
coverlock gallery --out out                                          # compose the 10-cover gallery
```

`titles.txt` is one title per line (`#` starts a comment). `--model mock` runs the whole pipeline with no API key and no network; swap in `--model doubao` / `--model qwen` and `export` the matching key to render real images with a domestic model.

<h2><img src="https://api.iconify.design/tabler:terminal-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Usage</h2>

The full `init → lock → gen → regen → gallery` in-the-loop control loop:

**1. Lock the style (freeze the style-pack)**

```bash
coverlock init my-pack --desc "minimal magazine look, Morandi palette, generous whitespace"
coverlock lock my-pack.yaml       # validate schema + write locked_sha; the style is now frozen
```

`lock` computes a sha256 over `model + prompt scaffold + palette + layout` and persists it. Any edit to a locked field is detected afterwards.

**2. Render a cover set**

```bash
export DOUBAO_API_KEY=...                        # bring your own key (skip it offline with --model mock)
coverlock gen --pack my-pack.yaml --titles titles.txt
# out/cover_01.png … cover_10.png
# each is 100% size-compliant (4:5 or 3:4) with the title 100% inside the safe-zone
# (auto shrink / wrap on overflow — never clipped)
```

`gen` reads only the locked pack and writes a sidecar so `regen` / `gallery` can reconstruct the whole set.

**3. Redraw a single cover, keep the style (in-the-loop)**

```bash
coverlock regen --pack my-pack.yaml --index 3 --title "a new title"
# redraws cover 3 only; every other cover stays byte-for-byte identical
```

**4. Compose the consistency gallery (the core self-proof)**

```bash
coverlock gallery --out out
# out/gallery.png: a 10-cell grid + per-cover size✓ / safe-zone✓ badges
#                  + footer: size-compliant 10/10 · titles-in-safe-zone 10/10
```

**Helper commands**

```bash
coverlock models      # list models: mock (offline, no key) / doubao-seedream / qwen-image
coverlock rules       # print the loaded platform rule table (sizes + safe-zone rects)
coverlock --version
```

<h2><img src="https://api.iconify.design/tabler:photo.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Demo</h2>

![demo](assets/demo.gif)

`init → lock → gen` (10 covers) → `regen` a single cover → `gallery`, all offline with `--model mock`; it ends on the consistency gallery with the `size-compliant 10/10 · titles-in-safe-zone 10/10` self-proof badge.

<h2><img src="https://api.iconify.design/tabler:layout-grid.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Why CoverLock</h2>

- **The account-level style-pack is a new primitive** — not a stateless "one-shot prompt → image" (every cover drifts), but a hash-lockable, cross-post-reusable, shareable YAML asset. Taste stops being an abstract instruction and becomes a lockable file.
- **Always size-compliant** — after the model renders, PIL forces a resize / crop to exactly 4:5 or 3:4; changing platform sizes means editing one YAML.
- **Title always in the safe-zone** — the title is placed only inside the `rules`-defined safe-zone rectangle, auto shrinking / wrapping on overflow — never clipped, never over the platform's own overlays.
- **Pluggable, offline-capable models** — the offline layer depends on no single model; `mock` runs the full path with zero key, real images come from your own Doubao / Qwen key.
- **In-the-loop control** — `regen` can "keep the whole style, redraw just this one," which template tools can't.
- **Self-proof at a glance** — a consistency gallery of 10 covers from one locked pack, with per-cover compliance badges and a footer self-proof, is the strongest screenshot hook.

<h2><img src="https://api.iconify.design/tabler:adjustments.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Configuration</h2>

Platform geometry is the single source of truth, in `assets/rules/xiaohongshu.yaml` — change sizes / safe-zones there, touch no Python:

| Size | Canvas (px) | Safe-zone (x, y, w, h) |
|---|---|---|
| `4:5` | 1080 × 1350 | 96, 132, 888, 900 |
| `3:4` | 1080 × 1440 | 96, 140, 888, 980 |

The origin is the top-left of the canvas. The safe-zone is the rectangle the title must stay fully inside; it is inset from the canvas edges to clear the platform's top status bar, bottom action rail, and side gutters.

<h2><img src="https://api.iconify.design/tabler:coin.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Pricing</h2>

CoverLock itself is **OSS + bring-your-own-key, free forever** — keeping the tool open and offline-runnable is the basis for stars and trust.

A **hosted layer** for Xiaohongshu agencies / MCNs (planned, v0.2+): they manage dozens of accounts, render covers in bulk daily, and mostly don't want to configure a model key per account or run a CLI locally. The hosted layer upgrades "bring your own key, run locally" into — upload a batch of titles → the cloud renders a compliant set with the platform's domestic-model quota → the account's locked style-pack is stored in the cloud, with multi-account, multi-seat, shared-pack collaboration.

| Tier | For | Price (educated guess, not live) |
|---|---|---|
| **OSS** | Individual creators, bring your own key | Free · open source forever |
| **Hosted render + cloud style-pack** | Small brands / single-account agencies | from ¥99/mo (N packs + M covers/mo) |
| **Team** | MCNs / multi-account agencies | ¥499/mo (multi-seat + multi-account pack library), overage ¥0.3–0.5/cover |

> v0.1 ships no paywall — this only marks the direction. The hosted layer will launch after real agency demand is confirmed.

<h2><img src="https://api.iconify.design/tabler:map-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Roadmap</h2>

- [x] **v0.1** — size-compliant cover render · style-pack lock + single-cover regen · 10-cover consistency gallery · `mock` / Doubao / Qwen models
- [ ] More platform rule tables (vertical surfaces beyond Xiaohongshu)
- [ ] Font subsetting and custom title fonts
- [ ] Ship as an installable Skill in the codex / claude-skill ecosystem
- [ ] Hosted render + cloud style-pack storage (paid tier for agencies / MCNs)

## Out of scope

Auto-posting / publishing to any platform · scraping Xiaohongshu or others' content · ad-buying / follower-growth / traffic ops · multi-platform aggregation · training / fine-tuning image models · video covers. CoverLock only touches your own cover files.

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
