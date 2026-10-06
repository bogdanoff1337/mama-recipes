#!/usr/bin/env python3
"""Додає рецепти, пропущені першим читанням. Вхід — JSON-список:
{id, title, category, group, folder, image, tags[], body}. Оновлює catalog/manifest/index."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT

TR = dict(zip("абвгґдеєжзиіїйклмнопрстуфхцчшщьюя'", ["a","b","v","h","g","d","e","ye","zh","z","y","i","yi","y","k","l","m","n","o","p","r","s","t","u","f","kh","ts","ch","sh","shch","","yu","ya","-"]))


def slug(s):
    s = "".join(TR.get(c, c) for c in s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def main(src):
    items = json.loads(Path(src).read_text(encoding="utf-8"))
    csv = ROOT / "catalog.csv"
    man = ROOT / "manifest.yaml"
    idx = ROOT / "index.md"
    for r in items:
        rid = r["id"]
        if list((ROOT / "recipes").rglob(f"{rid}-*.md")):
            print(f"{rid} уже існує — пропускаю"); continue
        rel = f"recipes/{r['folder']}/{rid}-{slug(r['title'])}.md"
        tags = "\n".join(f'  - "{t}"' for t in r.get("tags", []))
        fm = (f'---\nid: "{rid}"\nlegacy_id: "P2-{r["image"].split(".")[0]}"\ntitle: "{r["title"]}"\n'
              f'source_images:\n  - "{r["image"]}"\ncategory: "{r["category"]}"\ngroup: "{r["group"]}"\n'
              f'tags:\n{tags}\nconfidence: "low"\norder: {int(rid)}\nadded_in: "pass2"\n---\n\n')
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(fm + r["body"].strip() + "\n", encoding="utf-8")
        with csv.open("ab") as f:
            f.write((f'{rid},{r["title"].replace(",", " ")},{r["category"]},{r["group"]},low,{r["image"]},P2-{r["image"].split(".")[0]},{rel}\r\n').encode("utf-8"))
        with man.open("a", encoding="utf-8") as f:
            f.write(f'\n  - id: "{rid}"\n    legacy_id: "P2-{r["image"].split(".")[0]}"\n    title: "{r["title"]}"\n'
                    f'    category: "{r["category"]}"\n    group: "{r["group"]}"\n    confidence: "low"\n'
                    f'    file: "{rel}"\n    source_images:\n      - "{r["image"]}"')
        t = idx.read_text(encoding="utf-8")
        if "# Додано другим читанням" not in t:
            t = t.rstrip() + "\n\n# Додано другим читанням\n\nРецепти, пропущені першим проходом. Буде розкладено по розділах на етапі групування.\n"
        t = t.rstrip() + f'\n- **{rid}. {r["title"]}** — `{r["image"]}` — confidence: `low`\n'
        idx.write_text(t, encoding="utf-8")
        mt = man.read_text(encoding="utf-8")
        n = int(re.search(r"^recipe_count: (\d+)", mt, re.M).group(1)) + 1
        man.write_text(re.sub(r"^recipe_count: \d+", f"recipe_count: {n}", mt, flags=re.M), encoding="utf-8")
        print("+", rel)


if __name__ == "__main__":
    main(sys.argv[1])
