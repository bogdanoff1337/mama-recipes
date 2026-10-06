#!/usr/bin/env python3
"""Збирає всі <!-- ?? --> з рецептів -> questions.json, перевірити.md, перевірити.html.

ID питань (Q0001…) стабільні між перезапусками: відкрите питання з тим самим
файлом і тим самим текстом рядка зберігає свій номер.
Запуск: python3 review/build_review.py
"""
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (ROOT, REVIEW_MD, UNREADABLE, clean_line, hints, load_registry, load_suggestions,
                    parse_front, recipe_files, save_registry, MARKER_RE)

SECTION_ORDER = ["Консервація", "Салати", "Основні страви", "Риба та морепродукти",
                 "Закуски", "Соуси та приправи", "Випічка", "Десерти", "Напої"]


def scan():
    reg = load_registry()
    qs = reg["questions"]
    # відкриті питання, індексовані за (file, original) -> для стабільних ID
    open_idx = {}
    for qid, q in qs.items():
        if q["status"] == "open":
            open_idx.setdefault((q["file"], q["original"]), []).append(qid)

    seen = set()
    recipes = []
    for path in recipe_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        meta = parse_front(text)
        lines = text.split("\n")
        body = lines[meta.get("body_start", 0):]
        rq = []
        for i, line in enumerate(lines):
            if not MARKER_RE.search(line):
                continue
            key = (rel, line)
            cands = [q for q in open_idx.get(key, []) if q not in seen]
            if cands:
                qid = cands[0]
            else:
                qid = f"Q{reg['next']:04d}"
                reg["next"] += 1
                qs[qid] = {"file": rel, "original": line, "status": "open"}
            seen.add(qid)
            qs[qid].update(line_no=i + 1, current=clean_line(line), hints=hints(line),
                           recipe_id=meta.get("id"), title=meta.get("title"))
            rq.append(qid)
        recipes.append({
            "id": meta.get("id"), "title": meta.get("title"), "category": meta.get("category"),
            "group": meta.get("group"), "confidence": meta.get("confidence"),
            "images": meta.get("source_images", []), "file": rel,
            "body": body, "body_offset": meta.get("body_start", 0), "questions": rq,
        })
    # відкриті питання, яких більше нема у файлах (рядок змінено вручну)
    for qid, q in qs.items():
        if q["status"] == "open" and qid not in seen:
            q["status"] = "gone"
    save_registry(reg)
    return reg, recipes


def sort_key(r):
    cat = r["category"] or ""
    return (SECTION_ORDER.index(cat) if cat in SECTION_ORDER else 99, r["id"] or "")


REPL_DIR = ROOT / "review" / "pass2" / "replace"


def pending_replacements():
    return {p.stem for p in REPL_DIR.glob("*.json")} if REPL_DIR.exists() else set()


def write_md(reg, recipes):
    qs = reg["questions"]
    pend = pending_replacements()
    recipes = [r for r in recipes if r["id"] not in pend]
    sug = load_suggestions()
    n_open = sum(len(r["questions"]) for r in recipes)
    n_done = sum(1 for q in qs.values() if q["status"] == "resolved")
    n_unread = sum("\n".join(r["body"]).count(UNREADABLE) for r in recipes)
    out = [
        "# Перевірити з мамою", "",
        f"Відкрито: **{n_open}** питань у **{sum(1 for r in recipes if r['questions'])}** рецептах · "
        f"закрито: **{n_done}** · позначено нечитабельними: **{n_unread}**", "",
        "## Як заповнювати", "",
        "Під кожним питанням є рядок `Відповідь:`. Порожня відповідь = питання лишається відкритим.", "",
        "| Пишеш у відповідь | Що станеться з рядком |",
        "|---|---|",
        "| `ОК` | поточний текст правильний, маркер прибирається |",
        "| `1 ст. => 1 склянка` | заміна фрагмента в рядку (кілька — через `;`) |",
        "| `- сіль — 1 склянка` | рядок повністю замінюється цим текстом |",
        "| `НЕ ВДАЛОСЯ ПРОЧИТАТИ` | лишається з позначкою ✗, більше не питається |",
        "| `ВИДАЛИТИ` | рядок видаляється (для службових приміток типу «частина списку бліда») |",
        "| `НАЗВА: Зебра` | змінює назву рецепта, рядок-питання прибирається |",
        "",
        "**Claude:** — пропозиція з другого читання фото. ✅ = прочитано впевнено, ⚠️ = варіант, звір із фото.",
        "Щоб прийняти — скопіюй її у `Відповідь:` (у HTML — кнопка «Прийняти» або `Alt+4`).",
        "",
        f"⏳ **{len(pend)}** рецептів чекають рішення в `заміни.md` — їхні питання з'являться тут після рішення." if pend else "",
        "",
        "`[ ]` / `[x]` ставити не обов'язково — скрипт орієнтується на заповнену відповідь.",
        "Нічого не змінюється, поки не запустиш `python3 review/apply_review.py --write`.",
        "",
    ]
    cur_cat = None
    for r in sorted(recipes, key=sort_key):
        if not r["questions"]:
            continue
        if r["category"] != cur_cat:
            cur_cat = r["category"]
            out += ["---", "", f"# {cur_cat}", ""]
        imgs = " · ".join(f"`{i}`" for i in r["images"])
        out += [f"## {r['id']}. {r['title']}", "",
                f"📷 {imgs} · 📄 `{r['file']}` · confidence: `{r['confidence']}`", ""]
        for i in r["images"]:
            out.append(f"![{i}](photos/{i})")
        out.append("")
        for qid in r["questions"]:
            q = qs[qid]
            h = "; ".join(x for x in q["hints"] if x) or "нечітко"
            cur = q["current"].strip() or "(порожньо)"
            out += [f"- [ ] **{qid}** — {h}",
                    f"  Зараз: `{cur}`"]
            if qid in sug:
                sg = sug[qid]
                mark = "✅" if sg.get("sure") else "⚠️"
                note = f" — {sg['note']}" if sg.get("note") else ""
                out.append(f"  Claude: {mark} `{sg['answer']}`{note}")
            out += [f"  Відповідь: ", ""]
    REVIEW_MD.write_text("\n".join(out), encoding="utf-8")
    return n_open


def write_html(reg, recipes):
    qs = reg["questions"]
    pend = pending_replacements()
    recipes = [r for r in recipes if r["id"] not in pend]
    sug = load_suggestions()
    data = []
    for r in sorted(recipes, key=sort_key):
        if not r["questions"]:
            continue
        data.append({
            "id": r["id"], "title": r["title"], "category": r["category"], "images": r["images"],
            "file": r["file"], "body": r["body"], "offset": r["body_offset"],
            "q": [{"qid": qid, "line": qs[qid]["line_no"], "current": qs[qid]["current"],
                   "hints": qs[qid]["hints"], "sug": sug.get(qid)} for qid in r["questions"]],
        })
    tpl = (Path(__file__).parent / "review_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (ROOT / "перевірити.html").write_text(tpl.replace("/*__DATA__*/[]", payload), encoding="utf-8")


if __name__ == "__main__":
    reg, recipes = scan()
    n = write_md(reg, recipes)
    write_html(reg, recipes)
    print(f"Відкритих питань: {n}. Оновлено перевірити.md і перевірити.html")
