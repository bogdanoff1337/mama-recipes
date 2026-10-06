#!/usr/bin/env python3
"""Друкує всі рецепти з даного фото з номерами Q на сумнівних рядках."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_registry, parse_front, recipe_files, MARKER_RE
reg = load_registry()["questions"]
by = {(q["file"], q["line_no"]): k for k, q in reg.items() if q["status"] == "open"}
for img in sys.argv[1:]:
    for p in recipe_files():
        t = p.read_text(encoding="utf-8"); m = parse_front(t)
        if img not in m.get("source_images", []): continue
        rel = p.relative_to(ROOT).as_posix()
        print(f"=== {m['id']} {m['title']} [{m['confidence']}] {m['source_images']}")
        for i, l in enumerate(t.split("\n")[m["body_start"]:], m["body_start"] + 1):
            q = by.get((rel, i), "")
            print(f"{q:>6} | {l}")
