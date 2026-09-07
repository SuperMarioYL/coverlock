[English](README.en.md) | **简体中文**

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/hero-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/hero-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/hero-dark.svg">
  <img src="assets/presentation/hero-light.svg" width="1000" alt="把封面风格、模型参数与标题布局保存成可锁定的 style-pack，重复生成并检查一套封面。">
</picture>

**把封面风格、模型参数与标题布局保存成可锁定的 style-pack，重复生成并检查一套封面。**

`v0.5.0` · `Python 3.12+` · [Apache-2.0](LICENSE)

[Website](https://coverlock.lei6393.com) · [Demo record](docs/demo-results.json)

## 为什么使用

批量做封面时，模型视觉、标题排版和平台尺寸通常要反复配置。CoverLock 把这些设置收进 YAML style-pack，锁定后复用同一套参数，并将每张封面的尺寸与标题边界记录在 sidecar 中供 gallery 检查。

## 架构

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/architecture-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/architecture-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/architecture-dark.svg">
  <img src="assets/presentation/architecture-light.svg" width="1000" alt="stylepack.py 管理 YAML 和锁定摘要；模型 adapter 生成无文字底图；compose.py 按 rules.py 的尺寸与安全区排标题；gallery.py 读取实际合成时的合规记录拼图。模型能力与本地排版检查是不同环节。">
</picture>

stylepack.py 管理 YAML 和锁定摘要；模型 adapter 生成无文字底图；compose.py 按 rules.py 的尺寸与安全区排标题；gallery.py 读取实际合成时的合规记录拼图。模型能力与本地排版检查是不同环节。

平台规则在 [assets/rules](assets/rules/)，示例风格在 [assets/stylepacks/example.yaml](assets/stylepacks/example.yaml)。v0.5.0 会在模型覆盖参数生效前验证原始 pack 的锁。

## 安装

需要 Python 3.12+。安装依赖需要网络，示例使用内置 mock，不需要模型 key。

```bash
git clone https://github.com/SuperMarioYL/coverlock.git
cd coverlock
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 快速开始

实际运行 3 张封面的离线 mock 流程，验证锁定、合成、单张重绘和 gallery。3/3 是本次输入的本地几何检查结果，不证明模型画质或平台审核通过。

```bash
python -m coverlock.cli lock examples/presentation-pack.yaml
python -m coverlock.cli gen --pack examples/presentation-pack.yaml --titles examples/presentation-titles.txt --out examples/presentation-output
python -m coverlock.cli regen --pack examples/presentation-pack.yaml --out examples/presentation-output --index 2 --title "Read something new"
python -m coverlock.cli gallery --out examples/presentation-output
```

输入为 [锁定 pack](examples/presentation-pack.yaml) 与 [3 个标题](examples/presentation-titles.txt)，完整命令见 [重放脚本](examples/presentation_demo.sh)。输出 gallery 位于 [examples/presentation-output/gallery.png](examples/presentation-output/gallery.png)。

## 使用

`init` 创建草稿，`lock` 冻结字段，`gen` 生成整套，`regen --index N` 重绘一张，`gallery` 拼图。指定 `--pack` 时默认要求有效锁；需要进化风格时重新锁定并重生成整套，避免混用不同风格的封面。

## 实际 Demo

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/process-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/process-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/process-dark.svg">
  <img src="assets/presentation/process-light.svg" width="1000" alt="实际运行 3 张封面的离线 mock 流程，验证锁定、合成、单张重绘和 gallery。3/3 是本次输入的本地几何检查结果，不证明模型画质或平台审核通过。">
</picture>

### 锁定风格

对示例 pack 计算并保存锁定摘要。

```text
$ python -m coverlock.cli lock examples/presentation-pack.yaml
locked examples/presentation-pack.yaml
locked_sha: f3dab7a4a2c7cc0cdb3aad0575d091dd5a2c061621497f26e44876c966a8b4a6
the style is now frozen; any edit to a locked field will be detected.
```

### 生成三张

内置 mock 生成三张，尺寸与标题边界检查为 3/3。

```text
$ python -m coverlock.cli gen --pack examples/presentation-pack.yaml --titles examples/presentation-titles.txt --out examples/presentation-output
coverlock gen · pack=presentation (locked) · model=mock · size=4:5 (1080x1350) · 3 title(s)
  [✓] cover_01.png  1080x1350  size=✓ safe-zone=✓
  [✓] cover_02.png  1080x1350  size=✓ safe-zone=✓
  [✓] cover_03.png  1080x1350  size=✓ safe-zone=✓
done · size-compliant 3/3 · titles-in-safe-zone 3/3 · out=examples/presentation-output
```

### 重绘第二张

第二张换成新标题。

```text
$ python -m coverlock.cli regen --pack examples/presentation-pack.yaml --out examples/presentation-output --index 2 --title "Read something new"
regenerated cover 02 → examples/presentation-output/cover_02.png (same locked pack; other covers untouched)
```

### 检查套图

gallery 汇总本地合成记录。

```text
$ python -m coverlock.cli gallery --out examples/presentation-output
gallery → examples/presentation-output/gallery.png
size-compliant 3/3 · titles-in-safe-zone 3/3
```

## 能力与接入

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/integrations-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/integrations-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/integrations-dark.svg">
  <img src="assets/presentation/integrations-light.svg" width="1000" alt="文件输入和本地合成层可离线使用，远程模型只负责底图。用 models、rules 查看当前 backend 与几何规则；gallery 读取合成时记录的标题边界，而不是仅看固定尺寸。">
</picture>

文件输入和本地合成层可离线使用，远程模型只负责底图。用 models、rules 查看当前 backend 与几何规则；gallery 读取合成时记录的标题边界，而不是仅看固定尺寸。



## 配置

规则表给出 4:5 的 1080×1350、3:4 的 1080×1440，以及标题安全区。`--size` 选择尺寸，`--out` 选择目录；pack 锁定模型、prompt scaffold、palette 和 layout。可选远程 backend 需要其 API key。超长标题可能无法满足安全区，CLI 和 gallery 会报告失败。

## 路线图与范围

当前提供本地 CLI、锁定与单张重绘、三类 backend 和 gallery。更多平台、字体控制与托管协作是后续方向；没有自动发布或已上线的托管套餐。

- mock 是离线占位视觉，不能代表豆包或 Qwen 的图像质量。
- 安全区检查遵循仓库规则表，不等于平台审核或所有标题都能适配。
- 不自动发布内容，也不提供已上线的托管套餐。

## 许可证

[Apache-2.0](LICENSE)
