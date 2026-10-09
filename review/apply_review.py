#!/usr/bin/env python3
"""Застосовує відповіді з перевірити.md (і/або відповіді.json з HTML) до рецептів.

  python3 review/apply_review.py                 # dry-run: показує, що зміниться
  python3 review/apply_review.py --write         # вносить зміни
  python3 review/apply_review.py --json відповіді.json [--write]

Після --write: прибирає вирішені маркери, піднімає confidence, оновлює
catalog.csv / manifest.yaml / index.md, веде лог у review/перевірено.md
і перегенеровує перевірити.md / .html лише з відкритими питаннями.
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (ANS_DELETE, ANS_OK, ANS_UNREADABLE, LIST_PREFIX_RE, MARKER_RE, REVIEW_MD,
                    ROOT, UNREADABLE, clean_line, load_registry, save_registry)

RANK = {"low": 0, "medium": 1, "high": 2}


def parse_md_answers(path: Path) -> dict:
    ans, qid = {}, None
    for line in path.read_text(encoding="utf-8").split("\n"):
        m = re.search(r"\*\*(Q\d{4})\*\*", line)
        if m:
            qid = m.group(1)
            continue
        m = re.match(r"^\s*Відповідь:\s*(.*?)\s*$", line)
        if m and qid:
            if m.group(1):
                ans[qid] = m.group(1)
            qid = None
    return ans


def transform(original: str, answer: str):
    """-> (new_line | None для видалення, опис дії). ValueError при некоректній відповіді."""
    a = answer.strip()
    up = a.upper()
    cleaned = clean_line(original)
    if up == ANS_OK:
        return cleaned, "ok"
    if up == ANS_DELETE:
        return None, "delete"
    if up == ANS_UNREADABLE:
        return re.sub(r"[ \t]{2,}", " ", MARKER_RE.sub(UNREADABLE, original)).rstrip(), "unreadable"
    if up.startswith("НАЗВА:"):
        return ("__TITLE__", a.split(":", 1)[1].strip()), "title"
    if "<!--" in a:
        raise ValueError("відповідь містить коментар <!-- -->")
    if "=>" in a:
        new = cleaned
        for pair in a.split(";"):
            if not pair.strip():
                continue
            if "=>" not in pair:
                raise ValueError(f"пара без '=>': {pair!r}")
            src, dst = (x.strip() for x in pair.split("=>", 1))
            if src not in new:
                raise ValueError(f"фрагмент {src!r} не знайдено в рядку {new!r}")
            new = new.replace(src, dst, 1)
        return new, "replace"
    m = LIST_PREFIX_RE.match(original)
    if m and not LIST_PREFIX_RE.match(a):
        a = m.group(1) + a
    return a, "rewrite"


def set_confidence(text: str) -> tuple[str, str | None]:
    if MARKER_RE.search(text):
        return text, None
    m = re.search(r'^confidence:\s*"?(\w+)"?\s*$', text, re.M)
    if not m:
        return text, None
    cur = m.group(1)
    target = "medium" if UNREADABLE in text else "high"
    if RANK.get(target, 0) <= RANK.get(cur, 0):
        return text, None
    return text[:m.start()] + f'confidence: "{target}"' + text[m.end():], target


def update_indexes(changes: dict):
    """changes: {recipe_id: new_confidence}"""
    if not changes:
        return
    csv = ROOT / "catalog.csv"
    rows = csv.read_text(encoding="utf-8-sig").splitlines()
    for i, row in enumerate(rows):
        cols = row.split(",")
        if cols and cols[0] in changes and len(cols) > 4:
            cols[4] = changes[cols[0]]
            rows[i] = ",".join(cols)
    csv.write_text("﻿" + "\n".join(rows), encoding="utf-8")

    man = ROOT / "manifest.yaml"
    t = man.read_text(encoding="utf-8")
    for rid, conf in changes.items():
        t = re.sub(rf'(- id: "{rid}"\n(?:\s{{4}}.*\n)*?\s{{4}}confidence: )"\w+"', rf'\1"{conf}"', t)
    man.write_text(t, encoding="utf-8")

    idx = ROOT / "index.md"
    t = idx.read_text(encoding="utf-8")
    for rid, conf in changes.items():
        t = re.sub(rf"(\*\*{rid}\. .*confidence: )`\w+`", rf"\1`{conf}`", t)
    idx.write_text(t, encoding="utf-8")


def update_titles(changes: dict):
    """changes: {rel_file: new_title}"""
    if not changes:
        return
    csv = ROOT / "catalog.csv"
    rows = csv.read_text(encoding="utf-8-sig").splitlines()
    for i, row in enumerate(rows):
        cols = row.split(",")
        if len(cols) > 7 and cols[-1] in changes:
            rows[i] = ",".join([cols[0], changes[cols[-1]].replace(",", " ")] + cols[-6:])
    csv.write_bytes(("\ufeff" + "\r\n".join(rows) + "\r\n").encode("utf-8"))
    man = ROOT / "manifest.yaml"
    t = man.read_text(encoding="utf-8")
    idx = ROOT / "index.md"
    it = idx.read_text(encoding="utf-8")
    for rel, title in changes.items():
        rid = re.search(r"/(\d{3})-", rel).group(1)
        t = re.sub(rf'(- id: "{rid}"\n(?:\s{{4}}.*\n)*?\s{{4}}title: )".*"', lambda m: m.group(1) + f'"{title}"', t)
        it = re.sub(rf"\*\*{rid}\. .*?\*\*", lambda m: f"**{rid}. {title}**", it)
    man.write_text(t, encoding="utf-8")
    idx.write_text(it, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    reg = load_registry()
    qs = reg["questions"]
    answers = parse_md_answers(REVIEW_MD)
    if args.json:
        for k, v in json.loads(args.json.read_text(encoding="utf-8")).items():
            if v and v.strip():
                if k in answers and answers[k] != v:
                    print(f"⚠ {k}: різні відповіді в md і json — беру json")
                answers[k] = v

    by_file, errors = {}, []
    for qid, ans in sorted(answers.items()):
        q = qs.get(qid)
        if not q or q["status"] != "open":
            errors.append(f"{qid}: немає серед відкритих питань")
            continue
        try:
            new, kind = transform(q["original"], ans)
        except ValueError as e:
            errors.append(f"{qid}: {e}")
            continue
        by_file.setdefault(q["file"], []).append((qid, q["original"], new, kind, ans))

    conf_changes, log, title_changes = {}, [], {}
    for rel, items in by_file.items():
        path = ROOT / rel
        lines = path.read_text(encoding="utf-8").split("\n")
        used = set()
        for qid, orig, new, kind, ans in items:
            idx = next((i for i, l in enumerate(lines) if l == orig and i not in used), None)
            if idx is None:
                errors.append(f"{qid}: рядок у {rel} змінився вручну — перезапусти build_review.py")
                continue
            used.add(idx)
            if kind == "title":
                title = new[1].replace('"', "'")
                fm_end = next(i for i in range(1, len(lines)) if lines[i] == "---")
                for i in range(1, fm_end):
                    if lines[i].startswith("title:"):
                        print(f"\n{qid} [title] {rel}\n  - {lines[i]}\n  + title: \"{title}\"")
                        lines[i] = f'title: "{title}"'
                        title_changes[rel] = title
                new = None
                lines[idx] = None
                log.append((qid, rel, orig, f"НАЗВА: {title}", ans))
                continue
            print(f"\n{qid} [{kind}] {rel}:{idx + 1}\n  - {orig}\n  + {new if new is not None else '(видалено)'}")
            lines[idx] = new
            log.append((qid, rel, orig, new, ans))
        text = "\n".join(l for l in lines if l is not None)
        text, conf = set_confidence(text)
        if conf:
            rid = re.search(r'^id:\s*"?(\d+)"?', text, re.M).group(1)
            conf_changes[rid] = conf
            print(f"  ↑ {rel}: confidence → {conf}")
        if args.write:
            path.write_text(text, encoding="utf-8")

    print(f"\nВідповідей: {len(answers)}, застосовано: {len(log)}, помилок: {len(errors)}")
    for e in errors:
        print("✗", e)

    if not args.write:
        print("\nDry-run. Для запису: --write")
        return
    now = dt.datetime.now().isoformat(timespec="seconds")
    for qid, rel, orig, new, ans in log:
        qs[qid].update(status="resolved", answer=ans, resolved_at=now)
    save_registry(reg)
    update_indexes(conf_changes)
    update_titles(title_changes)
    logf = ROOT / "review" / "перевірено.md"
    with logf.open("a", encoding="utf-8") as f:
        if not logf.stat().st_size:
            f.write("# Журнал вичитки\n\n")
        for qid, rel, orig, new, ans in log:
            f.write(f"- `{now}` **{qid}** `{rel}`\n  - було: `{orig}`\n  - відповідь: `{ans}`\n"
                    f"  - стало: `{new if new is not None else '(видалено)'}`\n")
    subprocess.run([sys.executable, str(Path(__file__).parent / "build_review.py")], check=True)


if __name__ == "__main__":
    main()
