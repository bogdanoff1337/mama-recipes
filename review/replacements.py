#!/usr/bin/env python3
"""Повні заміни рецептів, які перше читання прочитало не той текст.

  replacements.py propose pass2/rep_IMG_xxxx.json   # записати пропозиції
  replacements.py build                             # перегенерувати заміни.md
  replacements.py apply [--write]                   # застосувати рецепти з [x] у заміни.md

Пропозиція: {id, title, body, reason, sure}. Frontmatter зберігається (id, фото, розділ),
змінюються title, confidence і тіло. Старий текст зберігається у review/pass2/replaced/.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import MARKER_RE, ROOT, parse_front, recipe_files

DIR = ROOT / "review" / "pass2" / "replace"
DONE = ROOT / "review" / "pass2" / "replaced"
DOC = ROOT / "заміни.md"


def file_for(rid):
    return next(p for p in recipe_files() if p.name.startswith(f"{rid}-"))


def body_of(text):
    return "\n".join(text.split("\n")[parse_front(text)["body_start"]:]).strip()


def propose(src):
    DIR.mkdir(parents=True, exist_ok=True)
    for r in json.loads(Path(src).read_text(encoding="utf-8")):
        (DIR / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print("пропозиція", r["id"], "→", r["title"])
    build()


def build():
    prev, prev_del = {}, {}
    if DOC.exists():  # зберегти вже поставлені галочки
        for m in re.finditer(r"^- \[(x|X| )\] замінити (\d{3})", DOC.read_text(encoding="utf-8"), re.M):
            prev[m.group(2)] = m.group(1).lower() == "x"
        for m in re.finditer(r"^- \[(x|X| )\] видалити (\d{3})", DOC.read_text(encoding="utf-8"), re.M):
            prev_del[m.group(2)] = m.group(1).lower() == "x"
    out = ["# Заміни рецептів (друге читання)", "",
           "Тут рецепти, де перше читання описало **не той текст**, що на фото.",
           "Постав `[x]` біля тих, які треба замінити, і запусти `python3 review/replacements.py apply --write`.",
           "Нечіткі місця в новій версії позначені `<!-- ?? -->` і після заміни потраплять у `перевірити`.", ""]
    items = sorted(DIR.glob("*.json")) if DIR.exists() else []
    for f in items:
        r = json.loads(f.read_text(encoding="utf-8"))
        p = file_for(r["id"])
        old = p.read_text(encoding="utf-8")
        meta = parse_front(old)
        mark = "x" if prev.get(r["id"]) else " "
        sure = "✅" if r.get("sure") else "⚠️"
        out += [f"## {r['id']}. {meta['title']} → {r['title']}", "",
                f"📷 {' · '.join('`' + i + '`' for i in meta['source_images'])} · {sure} {r.get('reason', '')}", "",
                f"![](photos/{meta['source_images'][0]})" if meta["source_images"] else "", "",
                f"- [{mark}] замінити {r['id']}", "",
                "<table><tr><th>Зараз</th><th>Пропозиція Claude</th></tr><tr><td>", "",
                "```", body_of(old), "```", "", "</td><td>", "",
                "```", f"# {r['title']}", "", r["body"].strip(), "```", "", "</td></tr></table>", ""]
    nf = ROOT / "review" / "pass2" / "notfound.json"
    if nf.exists():
        nfd = json.loads(nf.read_text(encoding="utf-8"))
        if nfd:
            out += ["---", "", "# Немає на жодному з 60 фото", "",
                    "Постав `[x] видалити NNN` — файл рецепта переїде в `review/pass2/removed/` (не губиться) і зникне з каталогу.", ""]
            for rid, note in sorted(nfd.items()):
                if rid.startswith("_"):
                    continue
                try:
                    t = parse_front(file_for(rid).read_text(encoding="utf-8"))["title"]
                except StopIteration:
                    continue
                mark = "x" if prev_del.get(rid) else " "
                out.append(f"- [{mark}] видалити {rid} — **{t}** — {note}")
            notes = [n for k, n in sorted(nfd.items()) if k.startswith("_")]
            if notes:
                out += ["", "## Обрізані / незрозумілі фрагменти — спитати маму", ""]
                out += [f"- {n}" for n in notes]
            out.append("")
    rg = ROOT / "review" / "pass2" / "regroup.json"
    if rg.exists():
        out += ["---", "", "# Перенести в інший розділ (зроблю на етапі групування)", ""]
        for rid, note in sorted(json.loads(rg.read_text(encoding="utf-8")).items()):
            out.append(f"- **{rid}** — {note}")
        out.append("")
    DOC.write_text("\n".join(out), encoding="utf-8")
    print(f"заміни.md: {len(items)} пропозицій")


def apply(write):
    text = DOC.read_text(encoding="utf-8")
    ids = re.findall(r"^- \[[xX]\] замінити (\d{3})", text, re.M)
    DONE.mkdir(parents=True, exist_ok=True)
    for rid in ids:
        r = json.loads((DIR / f"{rid}.json").read_text(encoding="utf-8"))
        p = file_for(rid)
        old = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", old, re.S)
        fm = m.group(1)
        title = r["title"].replace('"', "'")
        fm = re.sub(r'^title:.*$', f'title: "{title}"', fm, flags=re.M)
        conf = "medium" if MARKER_RE.search(r["body"]) else "high"
        fm = re.sub(r'^confidence:.*$', f'confidence: "{conf}"', fm, flags=re.M)
        if "replaced_in:" not in fm:
            fm += '\nreplaced_in: "pass2"'
        new = f"---\n{fm}\n---\n\n{r['body'].strip()}\n"
        print(f"{rid}: {parse_front(old)['title']} → {r['title']} ({conf})")
        if write:
            (DONE / p.name).write_text(old, encoding="utf-8")
            p.write_text(new, encoding="utf-8")
            (DIR / f"{rid}.json").rename(DONE / f"{rid}.json")
            # індекси
            for fn, pat, rep in [
                ("catalog.csv", rf"^{rid},[^,]*,(.*?),(.*?),\w+,", lambda mm: f"{rid},{title.replace(',', ' ')},{mm.group(1)},{mm.group(2)},{conf},"),
                ("index.md", rf"\*\*{rid}\. .*?\*\*(.*confidence: )`\w+`", lambda mm: f"**{rid}. {title}**{mm.group(1)}`{conf}`"),
            ]:
                fp = ROOT / fn
                raw = fp.read_bytes().decode("utf-8")
                fp.write_bytes(re.sub(pat, rep, raw, flags=re.M).encode("utf-8"))
            man = ROOT / "manifest.yaml"
            t = man.read_text(encoding="utf-8")
            t = re.sub(rf'(- id: "{rid}"\n(?:\s{{4}}.*\n)*?\s{{4}}title: )".*"', lambda mm: mm.group(1) + f'"{title}"', t)
            t = re.sub(rf'(- id: "{rid}"\n(?:\s{{4}}.*\n)*?\s{{4}}confidence: )"\w+"', lambda mm: mm.group(1) + f'"{conf}"', t)
            man.write_text(t, encoding="utf-8")
    dels = re.findall(r"^- \[[xX]\] видалити (\d{3})", text, re.M)
    removed = ROOT / "review" / "pass2" / "removed"
    for rid in dels:
        try:
            p = file_for(rid)
        except StopIteration:
            continue
        print(f"{rid}: видалити {parse_front(p.read_text(encoding='utf-8'))['title']}")
        if write:
            removed.mkdir(parents=True, exist_ok=True)
            p.rename(removed / p.name)
            fp = ROOT / "catalog.csv"
            raw = fp.read_bytes().decode("utf-8")
            fp.write_bytes(re.sub(rf"^{rid},.*\r?\n", "", raw, flags=re.M).encode("utf-8"))
            fp = ROOT / "index.md"
            fp.write_text(re.sub(rf"^- \*\*{rid}\. .*\n", "", fp.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
            man = ROOT / "manifest.yaml"
            t = man.read_text(encoding="utf-8")
            t = re.sub(rf'\n  - id: "{rid}"\n(?:    .*\n?)*?(?=\n  - id:|\Z)', "", t)
            n = len(re.findall(r'^  - id: "\d+"', t, re.M))
            t = re.sub(r"^recipe_count: \d+", f"recipe_count: {n}", t, flags=re.M)
            man.write_text(t, encoding="utf-8")
            nf = ROOT / "review" / "pass2" / "notfound.json"
            d = json.loads(nf.read_text(encoding="utf-8")); d.pop(rid, None)
            nf.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    if not write:
        print("Dry-run. Для запису: --write")
        return
    build()
    subprocess.run([sys.executable, str(Path(__file__).parent / "build_review.py")], check=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "propose":
        propose(sys.argv[2])
    elif cmd == "build":
        build()
    elif cmd == "apply":
        apply("--write" in sys.argv)
