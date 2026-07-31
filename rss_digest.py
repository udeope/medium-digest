#!/usr/bin/env python3
"""
RSS-first Medium digest pipeline (option 1b).
Fetches publication feeds, extracts real full text where available (free articles),
marks member-only articles as PREVIEW with the feed blurb.
No CAPTCHA, no browser, deterministic. Writes articles.json.
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent / "articles.json"
MAX_FULL_CHARS = 8000  # recortar texto completo para el JSON (tokens)

# Publicaciones que Edu sigue en su digest (extraídas del email de hoy + pubs gratis)
PUBS = [
    "ai-advances",
    "towards-artificial-intelligence",
    "data-science-collective",
    "code-like-a-girl",
    "gopenai",
    "better-programming",
    "crows-feet",
    "books-are-our-superpower",
    "the-startup",
    "ai-in-plain-english",
    "stackademic",
    "the-generator",
    "python-in-plain-english",
]


def get(url, timeout=20):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def strip_html(s):
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_feed(feed):
    items = re.findall(r"<item>.*?</item>", feed, re.S)
    out = []
    for it in items:
        def g(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", it, re.S)
            return m.group(1).strip() if m else ""

        title = re.sub(r"<!\[CDATA\[|\]\]>", "", g("title"))
        link = g("link")
        content = re.sub(r"<!\[CDATA\[|\]\]>", "", g("content:encoded"))
        desc = re.sub(r"<!\[CDATA\[|\]\]>", "", g("description"))
        creator = re.sub(r"<!\[CDATA\[|\]\]>", "", g("dc:creator"))
        pubdate = g("pubDate")
        cats = re.findall(r"<category>(.*?)</category>", it)
        cats = [re.sub(r"<!\[CDATA\[|\]\]>", "", c) for c in cats][:5]

        plain = strip_html(content)
        kind = "FULL" if len(plain) >= 2000 else "PREVIEW"
        if kind == "FULL":
            text = plain[:MAX_FULL_CHARS]
            blurb = ""
        else:
            text = ""
            blurb = strip_html(desc)[:900]

        out.append({
            "title": title,
            "url": link,
            "author": creator,
            "date": pubdate,
            "categories": cats,
            "kind": kind,
            "text": text,
            "blurb": blurb,
        })
    return out


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    seen, articles = set(), []
    errors = []
    for pub in PUBS:
        try:
            feed = get(f"https://medium.com/feed/{pub}")
            for a in parse_feed(feed):
                if a["url"] in seen or not a["url"]:
                    continue
                seen.add(a["url"])
                a["pub"] = pub
                articles.append(a)
            print(f"  {pub:32s} OK")
        except Exception as e:
            errors.append(f"{pub}: {str(e)[:50]}")
            print(f"  {pub:32s} ERROR {str(e)[:50]}")
        time.sleep(1.0)

    # Ordenar por fecha DESC (más reciente primero)
    articles.sort(key=lambda a: a["date"], reverse=True)

    # Hybrid: top N por fecha, pero con backfill para garantizar MIN_FULL legibles
    MIN_FULL = 8
    top = articles[:limit]
    full_count = sum(1 for a in top if a["kind"] == "FULL")
    if full_count < MIN_FULL:
        # reemplazar los PREVIEW más antiguos del top por FULL más recientes del resto
        rest_full = [a for a in articles[limit:] if a["kind"] == "FULL"]
        for a in rest_full:
            if full_count >= MIN_FULL:
                break
            # buscar el PREVIEW más antiguo del top
            oldest_prev = None
            for i in range(len(top) - 1, -1, -1):
                if top[i]["kind"] == "PREVIEW":
                    oldest_prev = i
                    break
            if oldest_prev is None:
                break
            top[oldest_prev] = a
            full_count += 1
    articles = top

    stats = {"FULL": sum(1 for a in articles if a["kind"] == "FULL"),
             "PREVIEW": sum(1 for a in articles if a["kind"] == "PREVIEW")}
    payload = {"generated": datetime.now(timezone.utc).isoformat(), "stats": stats, "articles": articles}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTotal: {len(articles)} articulos | FULL={stats['FULL']} | PREVIEW={stats['PREVIEW']} | errores: {len(errors)}")
    if errors:
        print("Errores:", "; ".join(errors))
    print(f"Guardado en {OUT}")


if __name__ == "__main__":
    main()
