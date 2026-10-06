"""Спільні функції для вичитки: пошук маркерів, парсинг рецептів."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECIPES = ROOT / "recipes"
REGISTRY = ROOT / "review" / "questions.json"
REVIEW_MD = ROOT / "перевірити.md"
SUGGEST = ROOT / "review" / "suggestions.json"

MARKER_RE = re.compile(r"<!--\s*\?\?(.*?)-->")
UNREADABLE = "<!-- ✗ не прочитано -->"
LIST_PREFIX_RE = re.compile(r"^(\s*(?:[-*]|\d+\.)\s+)")

ANS_OK = "ОК"
ANS_UNREADABLE = "НЕ ВДАЛОСЯ ПРОЧИТАТИ"
ANS_DELETE = "ВИДАЛИТИ"


def clean_line(line: str) -> str:
    """Рядок без ?? маркерів, з нормалізованими пробілами."""
    s = MARKER_RE.sub("", line)
    s = re.sub(r"[ \t]{2,}", " ", s).rstrip()
    s = re.sub(r"\s+([.,;:])", r"\1", s)
    return s


def hints(line: str) -> list[str]:
    return [h.strip() for h in MARKER_RE.findall(line)]


def parse_front(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta = {}
    if not m:
        return meta
    fm = m.group(1)
    for key in ("id", "title", "category", "group", "confidence"):
        mm = re.search(rf'^{key}:\s*"?(.*?)"?\s*$', fm, re.M)
        if mm:
            meta[key] = mm.group(1)
    meta["source_images"] = re.findall(r'^\s+-\s*"?(IMG_[^"\s]+)"?', fm, re.M)
    meta["body_start"] = text[: m.end()].count("\n")
    return meta


def recipe_files():
    return sorted(RECIPES.rglob("*.md"), key=lambda p: p.name)


def load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"next": 1, "questions": {}}


def save_registry(reg: dict):
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


def load_suggestions() -> dict:
    if SUGGEST.exists():
        return json.loads(SUGGEST.read_text(encoding="utf-8"))
    return {}
