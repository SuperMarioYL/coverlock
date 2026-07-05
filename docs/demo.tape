# CoverLock demo — the happy path, fully offline (--model mock).
# Rendered to assets/demo.gif by .github/workflows/demo.yml (charmbracelet/vhs).
# Run locally with:  vhs docs/demo.tape

Output assets/demo.gif

Set Shell "bash"
Set FontSize 18
Set Width 1200
Set Height 720
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

# --- setup (kept off-camera) --------------------------------------------- #
Hide
Type "python -m venv .demovenv && source .demovenv/bin/activate" Enter
Type "pip install -q -e . >/dev/null 2>&1" Enter
Type "clear" Enter
Show

# --- 1. lock a style-pack ------------------------------------------------- #
Type "# 1. lock an account-level style-pack — the style is now frozen"
Enter
Type "coverlock init my-pack --desc '极简杂志风、莫兰迪色、大留白'"
Enter
Sleep 1.5s
Type "coverlock lock my-pack.yaml"
Enter
Sleep 2s

# --- 2. render a 10-cover set (offline mock, retargeted from the pack) ---- #
Type "# 2. render a 10-cover set — every cover 4:5, title in the safe-zone"
Enter
Type "printf '%s\n' '本周护肤清单' '通勤穿搭灵感' '周末咖啡地图' '极简书桌好物' '深夜厨房食谱' '城市徒步路线' '低成本旅行' '毛孩子日常' '读书笔记摘录' '换季收纳术' > titles.txt"
Enter
Sleep 500ms
Type "coverlock gen --pack my-pack.yaml --titles titles.txt --model mock"
Enter
Sleep 3s

# --- 3. keep the style, redraw a single cover ----------------------------- #
Type "# 3. keep the whole style, redraw just cover 3 (in-the-loop control)"
Enter
Type "coverlock regen --pack my-pack.yaml --index 3 --title '周末咖啡地图·新版'"
Enter
Sleep 2.5s

# --- 4. the consistency gallery + self-proof ------------------------------ #
Type "# 4. compose the consistency gallery — the self-proof screenshot"
Enter
Type "coverlock gallery --out out"
Enter
Sleep 3.5s

Type "# out/gallery.png: 10 covers, one locked style — size-compliant 10/10, titles-in-safe-zone 10/10"
Enter
Sleep 3s
