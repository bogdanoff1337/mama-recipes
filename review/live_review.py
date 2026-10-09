#!/usr/bin/env python3
import json
import re
import socket
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from apply_review import update_titles
from common import MARKER_RE, ROOT, clean_line, load_registry, parse_front, recipe_files


PAGE = Path(__file__).with_name("live_review.html")
ANSWER_FILE = Path(__file__).with_name(".live_answer.json")
TITLE_MAX_LENGTH = 200


def recipe_data():
    registry = load_registry()["questions"]
    questions = {qid: q for qid, q in registry.items() if q["status"] == "open"}
    by_file = {}
    for qid, question in questions.items():
        by_file.setdefault(question["file"], []).append({"qid": qid, **question})
    recipes = []
    for path in recipe_files():
        rel = path.relative_to(ROOT).as_posix()
        current = by_file.get(rel, [])
        text = path.read_text(encoding="utf-8")
        meta = parse_front(text)
        lines = text.split("\n")
        body_start = meta.get("body_start", 0)
        line_questions = {}
        for question in current:
            line_questions.setdefault(question["line_no"] - body_start - 1, []).append(question)
        body = []
        for index, line in enumerate(lines[body_start:]):
            item = {"text": line}
            if index in line_questions:
                item["questions"] = line_questions[index]
            body.append(item)
        recipes.append({
            "id": meta.get("id", ""),
            "title": meta.get("title", ""),
            "category": meta.get("category", ""),
            "images": meta.get("source_images", []),
            "file": rel,
            "body": body,
        })
    return sorted(recipes, key=lambda recipe: (recipe["category"], recipe["id"]))


def visible_line(question):
    def replacement(match):
        hint = match.group(1).strip() or "?"
        return f"[{hint}]"
    return MARKER_RE.sub(replacement, question["original"])


def answer_for(question, value):
    original = question["original"]
    if value == visible_line(question):
        return None
    match = MARKER_RE.search(original)
    if not match:
        return value
    before = original[:match.start()]
    after = original[match.end():]
    inline = re.fullmatch(re.escape(before) + r"\[(.*?)\]" + re.escape(after), value)
    if inline:
        return clean_line(before + inline.group(1) + after)
    return value


def normalized_title(value):
    title = " ".join(str(value).split()).replace('"', "'")
    if not title:
        raise ValueError("Назва не може бути порожньою")
    if len(title) > TITLE_MAX_LENGTH:
        raise ValueError(f"Назва довша за {TITLE_MAX_LENGTH} символів")
    return title


def rename_recipe(rel, value):
    paths = {path.relative_to(ROOT).as_posix(): path for path in recipe_files()}
    if rel not in paths:
        raise ValueError("Рецепт не знайдено")
    title = normalized_title(value)
    path = paths[rel]
    lines = path.read_text(encoding="utf-8").split("\n")
    front_end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    title_index = next((i for i in range(1, front_end or 0) if lines[i].startswith("title:")), None)
    if title_index is None:
        raise ValueError("У рецепті немає поля title")
    if lines[title_index] == f'title: "{title}"':
        return False
    lines[title_index] = f'title: "{title}"'
    path.write_text("\n".join(lines), encoding="utf-8")
    update_titles({rel: title})
    subprocess.run([sys.executable, str(Path(__file__).with_name("build_review.py"))], cwd=ROOT, check=True,
                   capture_output=True)
    return True


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE.read_bytes())
            return
        if self.path == "/api/recipes":
            self.respond({"recipes": recipe_data()})
            return
        super().do_GET()

    def do_POST(self):
        if self.path not in ("/api/answer", "/api/title"):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            request = json.loads(self.rfile.read(length))
            if self.path == "/api/title":
                saved = rename_recipe(request["file"], request["title"])
                self.respond({"saved": saved, "recipes": recipe_data()})
                return
            qid = request["qid"]
            value = request["value"].strip()
            question = load_registry()["questions"].get(qid)
            if not question or question["status"] != "open":
                raise ValueError("Питання вже закрито або не знайдено")
            answer = answer_for(question, value)
            if answer is None:
                self.respond({"saved": False})
                return
            ANSWER_FILE.write_text(json.dumps({qid: answer}, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("apply_review.py")), "--json", str(ANSWER_FILE), "--write"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            ANSWER_FILE.unlink(missing_ok=True)
            if result.returncode:
                raise ValueError(result.stderr or result.stdout)
            self.respond({"saved": True, "recipes": recipe_data()})
        except KeyError as error:
            self.respond({"error": f"Не вистачає поля {error}"}, 400)
        except (ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
            self.respond({"error": str(error)}, 400)

    def respond(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # пакет не надсилається, лише вибір інтерфейсу
            return s.getsockname()[0]
        except OSError:
            return "IP-цього-компʼютера"


if __name__ == "__main__":
    # --lan: доступ з телефону в тій самій Wi-Fi (без пароля — лише вдома)
    lan = "--lan" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--lan"]
    port = int(args[0]) if args else 8765
    server = ThreadingHTTPServer(("0.0.0.0" if lan else "127.0.0.1", port), Handler)
    print(f"Відкрийте http://127.0.0.1:{port}")
    if lan:
        print(f"З телефону (та сама Wi-Fi): http://{lan_ip()}:{port}")
    server.serve_forever()
