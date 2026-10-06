#!/usr/bin/env python3
"""Вносить пропозиції другого читання (Claude) з JSON-файлу.

Операції (кожна з "id" рецепта, "answer", "sure", опційно "note"):
  sug           — "q": існуюче питання Qxxxx
  tag           — "match": підрядок наявного рядка без маркера -> до рядка додається маркер
  insert_after  — "match": підрядок рядка (або "" = одразу після frontmatter) -> вставляється
                  рядок-маркер (порожній вміст; відповідь його заповнить)
  title         — питання про назву; answer має бути "НАЗВА: …"
Текст рецептів НЕ змінюється — лише додаються маркери <!-- ?? Claude: … -->.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, SUGGEST, MARKER_RE, load_registry, load_suggestions, parse_front, recipe_files


def file_for(rid):
    for p in recipe_files():
        if p.name.startswith(f"{rid}-"):
            return p
    raise SystemExit(f"нема рецепта {rid}")


def main(src):
    ops = json.loads(Path(src).read_text(encoding="utf-8"))
    pending = []  # (rel, line_text, op)
    sug = load_suggestions()
    for op in ops:
        kind = op["op"]
        if kind == "sug":
            sug[op["q"]] = {k: op[k] for k in ("answer", "sure", "note") if k in op}
            continue
        p = file_for(op["id"])
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding="utf-8")
        lines = text.split("\n")
        body = parse_front(text)["body_start"]
        marker = f"<!-- ?? Claude: {op['hint']} -->"
        if kind == "tag":
            hits = [i for i in range(body, len(lines)) if op["match"] in lines[i]]
            if len(hits) != 1:
                raise SystemExit(f"{op['id']}: '{op['match']}' знайдено {len(hits)} разів")
            i = hits[0]
            if MARKER_RE.search(lines[i]):
                raise SystemExit(f"{op['id']}: рядок уже має маркер, використай sug")
            lines[i] = lines[i].rstrip() + " " + marker
            new_line = lines[i]
        elif kind in ("insert_after", "title"):
            if kind == "title" or op.get("match", "") == "":
                i = body  # одразу після frontmatter
            else:
                hits = [k for k in range(body, len(lines)) if op["match"] in lines[k]]
                if len(hits) != 1:
                    raise SystemExit(f"{op['id']}: '{op['match']}' знайдено {len(hits)} разів")
                i = hits[0] + 1
            new_line = marker if kind != "title" else f"<!-- ?? Claude: назва — {op['hint']} -->"
            lines.insert(i, new_line)
        else:
            raise SystemExit(f"невідома операція {kind}")
        p.write_text("\n".join(lines), encoding="utf-8")
        pending.append((rel, new_line, op))

    SUGGEST.write_text(json.dumps(sug, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run([sys.executable, str(Path(__file__).parent / "build_review.py")], check=True,
                   stdout=subprocess.DEVNULL)
    reg = load_registry()["questions"]
    for rel, line, op in pending:
        qid = next(k for k, q in reg.items() if q["status"] == "open" and q["file"] == rel and q["original"] == line)
        sug[qid] = {k: op[k] for k in ("answer", "sure", "note") if k in op}
        print(f"{qid} ← {op['op']} {op['id']}")
    SUGGEST.write_text(json.dumps(sug, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run([sys.executable, str(Path(__file__).parent / "build_review.py")], check=True)


if __name__ == "__main__":
    main(sys.argv[1])
