#!/bin/bash
# halves.sh N -> top/bottom halves ~1500px wide, left 0..cut%
S=/tmp/claude-0/-home-claude/ebc54a55-54d2-5da0-af01-30eb81d6449e/scratchpad
cd /home/claude/mama_recipes_final
review/crop.sh IMG_$1 0 52 ${2:-0} ${3:-100} >/dev/null; review/crop.sh IMG_$1 48 100 ${2:-0} ${3:-100} >/dev/null
python3 review/dump_image.py IMG_$1.jpg
