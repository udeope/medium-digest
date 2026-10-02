#!/usr/bin/env python3
"""Inject the latest last30days cron response into the Medium Pages digest."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = Path(r"C:\Users\admin\AppData\Local\hermes\cron\output\e9c848fb9508")
INDEX = ROOT / "index.html"
START = "<!-- NEWS_DIGEST_START -->"
END = "<!-- NEWS_DIGEST_END -->"
CSS_START = "/* NEWS_DIGEST_CSS_START */"
CSS_END = "/* NEWS_DIGEST_CSS_END */"
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
STORY_RE = re.compile(r"\*\*(.+?)\*\*\s+-\s+(.*)")
MONTHS_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}
CSS = """.news-section{background:#121212;border:1px solid #2a2a2a;border-radius:14px;padding:22px;margin:30px 0 40px}
.news-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:16px}
.news-kicker{color:#7dc3ff;font-size:.72rem;text-transform:uppercase;letter-spacing:.12em}
.news-heading h2{margin:4px 0 0;color:#fff;font-size:1.3rem}
.news-date{color:#888;font-size:.82rem;white-space:nowrap}
.news-overview{background:#171717;border:1px solid #303030;border-radius:10px;padding:16px 18px;margin-bottom:14px}
.news-overview h3,.news-group h3{font-size:.94rem;color:#fff;line-height:1.4;margin-bottom:9px}
.news-overview ul,.news-list{padding-left:19px;color:#bbb}
.news-overview li{margin:5px 0}
.news-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}
.news-group{padding:16px;background:#161616;border:1px solid #2a2a2a;border-radius:10px}
.news-group h3{font-size:.9rem}
.news-list{font-size:.87rem;line-height:1.6}
.news-list li{margin:0 0 10px}
.news-list li:last-child{margin-bottom:0}
.news-feature{grid-column:1/-1;border-color:#37506a}
.news-section a{color:#7dc3ff;text-decoration:none}
.news-section a:hover{text-decoration:underline}
.news-sources{margin-top:14px;color:#777;font-size:.77rem}
.news-note{margin-top:8px;color:#d0ae70;font-size:.82rem}
@media(max-width:600px){.news-section{padding:16px}.news-heading{flex-direction:column}.news-date{white-space:normal}}"""


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("La fecha debe tener formato YYYY-MM-DD") from exc


def latest_transcript(target: date) -> Path:
    candidates: list[tuple[date, float, Path]] = []
    for path in OUTPUT_DIR.glob("*.md"):
        match = re.match(r"(\d{4}-\d{2}-\d{2})_", path.name)
        if not match:
            continue
        run_date = parse_date(match.group(1))
        if run_date <= target:
            candidates.append((run_date, path.stat().st_mtime, path))
    if not candidates:
        raise FileNotFoundError(f"No hay transcripciones last30days hasta {target.isoformat()}")
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def extract_response(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^## Response\s*\n(.*)$", text, re.MULTILINE | re.DOTALL)
    if not match or not match.group(1).strip():
        raise ValueError(f"No se encontró una sección ## Response válida en {path.name}")
    return match.group(1).strip()


def parse_digest(response: str) -> dict:
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if not lines:
        raise ValueError("La respuesta last30days está vacía")
    match_date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", lines[0])
    if not match_date:
        raise ValueError("La primera línea del digest debe incluir YYYY-MM-DD")
    digest_date = parse_date(match_date.group(1))
    overview: list[str] = []
    categories: list[dict] = []
    current = ""
    current_category: dict | None = None
    footer = ""
    notes: list[str] = []

    for raw_line in lines[1:]:
        line = re.sub(r"^#{1,4}\s+", "", raw_line)
        if line.startswith("🧭"):
            current = "overview"
            current_category = None
        elif line.startswith("⚡"):
            footer = line
            current = "footer"
            current_category = None
        elif line.startswith("⚠️"):
            notes.append(line)
        elif line.startswith(("🤖", "🛠️", "🛡️", "💼", "🔥")):
            current_category = {"title": line, "items": []}
            categories.append(current_category)
            current = "category"
        elif line.startswith(("• ", "- ")):
            content = line[2:].strip()
            if current == "overview":
                overview.append(content)
            elif current == "category" and current_category is not None:
                story = STORY_RE.fullmatch(content)
                if not story:
                    raise ValueError(f"Noticia sin formato **título** - resumen: {line[:120]}")
                current_category["items"].append({"title": story.group(1), "summary": story.group(2)})
            else:
                raise ValueError(f"Bullet fuera de una sección reconocida: {line[:100]}")
        elif current == "footer" and line.startswith("⚠️"):
            notes.append(line)
        else:
            raise ValueError(f"Línea no reconocida en el digest: {line[:120]}")

    count = sum(len(category["items"]) for category in categories)
    if not categories or count == 0:
        raise ValueError("No se encontraron noticias en la respuesta")
    if not footer:
        raise ValueError("Falta la atribución final ⚡ vía last30days")
    return {"date": digest_date, "overview": overview, "categories": categories, "footer": footer, "notes": notes, "count": count}


def inline_html(value: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in LINK_RE.finditer(value):
        plain = html.escape(value[cursor:match.start()]).replace("**", "").replace("`", "")
        if plain:
            pieces.append(plain)
        label = html.escape(match.group(1).replace("**", "").replace("`", ""))
        url = html.escape(match.group(2), quote=True)
        pieces.append(f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>')
        cursor = match.end()
    tail = html.escape(value[cursor:]).replace("`", "")
    if tail:
        pieces.append(tail)
    rendered = "".join(pieces)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    return rendered


def spanish_date(value: date) -> str:
    return f"{value.day} de {MONTHS_ES[value.month]} de {value.year}"


def render_section(data: dict) -> str:
    date_label = spanish_date(data["date"])
    chunks = [
        START,
        '<section class="news-section" id="news-digest" aria-labelledby="news-title">',
        '  <div class="news-heading"><div><div class="news-kicker">last30days · digest diario</div>',
        '    <h2 id="news-title">Digest Diario de Noticias Tech</h2></div>',
        f'    <div class="news-date">{html.escape(date_label)}</div></div>',
    ]
    if data["overview"]:
        chunks.append('  <div class="news-overview"><h3>🧭 Lectura rápida</h3><ul>')
        chunks.extend(f"    <li>{inline_html(item)}</li>" for item in data["overview"])
        chunks.append("  </ul></div>")
    chunks.append('  <div class="news-grid">')
    for category in data["categories"]:
        feature = " news-feature" if category["title"].startswith("🔥") else ""
        chunks.append(f'    <div class="news-group{feature}"><h3>{inline_html(category["title"])}</h3><ul class="news-list">')
        for story in category["items"]:
            chunks.append(f'      <li><strong>{inline_html(story["title"])}</strong> - {inline_html(story["summary"])}</li>')
        chunks.append("    </ul></div>")
    chunks.append("  </div>")
    chunks.append(f'  <div class="news-sources">{inline_html(data["footer"])}</div>')
    chunks.extend(f'  <div class="news-note">{inline_html(note)}</div>' for note in data["notes"])
    chunks.extend(["</section>", END])
    return "\n".join(chunks)


def ensure_css(document: str) -> str:
    block = f"{CSS_START}\n{CSS}\n{CSS_END}"
    marker_re = re.compile(re.escape(CSS_START) + r".*?" + re.escape(CSS_END), re.DOTALL)
    if marker_re.search(document):
        return marker_re.sub(block, document, count=1)
    match = re.search(r"</style\s*>", document, re.IGNORECASE)
    if match:
        return document[:match.start()] + "\n" + block + "\n" + document[match.start():]
    head_close = re.search(r"</head\s*>", document, re.IGNORECASE)
    if not head_close:
        raise ValueError("index.html no contiene </style> ni </head>")
    style_block = f"<style>\n{block}\n</style>\n"
    return document[:head_close.start()] + style_block + document[head_close.start():]


def inject_section(document: str, section: str) -> str:
    marker_re = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if marker_re.search(document):
        return marker_re.sub(section, document, count=1)
    # Replace an older unmarked insertion, if a previous one-off publish left one.
    document = re.sub(r'<section\b(?=[^>]*\bid=["\']news-digest["\'])[^>]*>.*?</section>', "", document, count=1, flags=re.IGNORECASE | re.DOTALL)
    target = re.search(r"<section\b[^>]*class=[\"'][^\"']*articles-section", document, re.IGNORECASE)
    if not target:
        raise ValueError("No se encontró section.articles-section en index.html")
    return document[:target.start()] + section + "\n\n" + document[target.start():]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Fecha del index.html, YYYY-MM-DD")
    args = parser.parse_args()
    try:
        target_date = parse_date(args.date)
        transcript = latest_transcript(target_date)
        response = extract_response(transcript)
        data = parse_digest(response)
        title_date = spanish_date(target_date)
        document = INDEX.read_text(encoding="utf-8")
        title = re.search(r"<title>(.*?)</title>", document, re.IGNORECASE | re.DOTALL)
        if not title or title_date not in html.unescape(title.group(1)):
            raise ValueError(f"El título de index.html no corresponde a {title_date}; no se modifica la página")
        document = ensure_css(document)
        document = inject_section(document, render_section(data))
        INDEX.write_text(document, encoding="utf-8", newline="")
        result = {
            "ok": True,
            "page_date": target_date.isoformat(),
            "news_date": data["date"].isoformat(),
            "stories": data["count"],
            "categories": len(data["categories"]),
            "transcript": transcript.name,
            "index": str(INDEX),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"NEWS_SECTION_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
