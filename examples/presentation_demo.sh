#!/usr/bin/env bash
set -euo pipefail
python -m coverlock.cli lock examples/presentation-pack.yaml
python -m coverlock.cli gen --pack examples/presentation-pack.yaml --titles examples/presentation-titles.txt --out examples/presentation-output
python -m coverlock.cli regen --pack examples/presentation-pack.yaml --out examples/presentation-output --index 2 --title "Read something new"
python -m coverlock.cli gallery --out examples/presentation-output
