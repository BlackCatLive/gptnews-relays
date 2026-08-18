# FINAL GPT News Relay
# Strict Russian-only Telegram feed for free music-production resources.
# See the chat message for what to replace.

import os
import re
import json
import time
import html
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.parse import quote
from xml.etree import ElementTree as ET

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "").strip()
SEEN_FILE = "seen.json"

GENRES = {
    "minimal house": 10, "deep minimal": 11, "rominimal": 12,
    "romanian minimal": 12, "minimal techno": 8, "minimal tech": 8,
    "deep tech": 8, "deep house": 7, "tech house": 6,
}

RESOURCE = {
    "acapella": 12, "acapellas": 12, "vocal pack": 12, "vocal packs": 12,
    "free vocals": 12, "free vocal": 12, "sample pack": 10,
    "sample packs": 10, "free samples": 9, "free sample": 9,
    "drum kit": 9, "drum kits": 9, "one-shot": 8, "one shot": 8,
    "loops": 7, "loop pack": 9, "serum preset": 11,
    "serum presets": 11, "vital preset": 11, "vital presets": 11,
    "preset pack": 9, "preset packs": 9, "free vst": 10,
    "free vst3": 10, "free plugin": 9, "free plugins": 9,
    "free synth": 8, "free synthesizer": 8, "free effect": 8,
    "free effects": 8, "midi": 6,
}

FREE_WORDS = (
    "free", "gratis", "no cost", "100% free", "completely free",
    "free download", "free pack", "free sample"
)

BAD = (
    "trial", "demo version", "free trial", "subscription", "subscribe",
    "rent-to-own", "rent to own", "monthly plan", "annual plan",
    "paid only", "paid-only", "buy now", "upgrade", "membership",
    "free to try", "limited trial"
)

EDITORIAL = (
    "best free", "top 10", "top 20", "top 50", "top 100",
    "ultimate list", "best platforms", "roundup", "list of",
    "guide to", "how to", "review", "reviews", "news", "new single",
    "album", "song", "release", "celebrate", "ministry"
)

CATEGORY_TERMS = {
    "vocals": ("vocal", "vocals", "acapella", "acapellas"),
    "presets": ("serum preset", "serum presets", "vital preset", "vital presets", "preset"),
    "samples": ("sample pack", "sample packs", "free samples", "one-shot", "one shot", "loops"),
    "drums": ("drum kit", "drum kits", "drums", "percussion"),
    "plugins": ("free vst", "free vst3", "free plugin", "free plugins", "synth", "effect"),
    "midi": ("midi",),
}

SOURCES = [
    ("Bedroom Producers Blog", "https://bedroomproducersblog.com/feed/"),
    ("Rekkerd", "https://rekkerd.org/feed/"),
    ("MusicRadar", "https://www.musicradar.com/feeds"),
    ("Google: free sample packs", "https://news.google.com/rss/search?q=" + quote('"free sample pack" music production')),
    ("Google: free vocals", "https://news.google.com/rss/search?q=" + quote('"free vocal pack" OR "free acapella" music production')),
    ("Google: Serum presets", "https://news.google.com/rss/search?q=" + quote('"free Serum preset" music production')),
    ("Google: Vital presets", "https://news.google.com/rss/search?q=" + quote('"free Vital preset" music production')),
    ("Google: free VST", "https://news.google.com/rss/search?q=" + quote('"free VST" plugin music production')),
    ("Google: free drum kits", "https://news.google.com/rss/search?q=" + quote('"free drum kit" music production')),
    ("Google: minimal house resources", "https://news.google.com/rss/search?q=" + quote('"minimal house" ("free sample" OR "free preset" OR "free vocal")')),
    ("Google: deep minimal resources", "https://news.google.com/rss/search?q=" + quote('"deep minimal" ("free sample" OR "free preset" OR "free vocal")')),
    ("Google: rominimal resources", "https://news.google.com/rss/search?q=" + quote('"rominimal" ("free sample" OR "free preset" OR "free vocal")')),
]

def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()

def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-5000:], f, ensure_ascii=False, indent=2)

def fetch(url, timeout=15):
    req = Request(url, headers={"User-Agent": "GPTNewsRelay/6.0"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()

def parse_feed(source, url):
    try:
        root = ET.fromstring(fetch(url))
    except Exception as exc:
        print(f"FEED ERROR {source}: {exc}")
        return []
    result = []
    for node in root.iter():
        if node.tag.lower().split("}")[-1] not in ("item", "entry"):
            continue
        title = desc = link = date = ""
        for child in list(node):
            tag = child.tag.lower().split("}")[-1]
            text = clean_text(child.text or "")
            if tag == "title":
                title = text
            elif tag in ("description", "summary") and not desc:
                desc = text
            elif tag in ("pubdate", "published", "updated") and not date:
                date = text
            elif tag == "link":
                link = child.attrib.get("href", "") or text
        if title and link:
            result.append({"source": source, "title": title, "description": desc, "link": link, "date": date})
    return result[:100]

def fingerprint(item):
    return hashlib.sha256((item["title"] + "|" + item["link"]).encode()).hexdigest()

def classify(item):
    text = (item["title"] + " " + item["description"]).lower()
    resource_hits = [term for term in RESOURCE if term in text]
    free_hit = any(term in text for term in FREE_WORDS)
    if not free_hit:
        return -999, [], [], "no-free-signal"
    if any(term in text for term in BAD):
        return -999, [], [], "paid-or-trial"
    if not resource_hits:
        return -999, [], [], "not-resource"

    # Reject music/editorial news unless it clearly contains a downloadable resource.
    editorial = any(term in text for term in EDITORIAL)
    resource_phrase = any(term in text for term in (
        "download", "sample pack", "preset pack", "vocal pack",
        "acapella pack", "free vst", "free vst3", "free plugin"
    ))
    if editorial and not resource_phrase:
        return -999, [], [], "editorial"

    genres = [term for term in GENRES if term in text]
    categories = [
        category for category, terms in CATEGORY_TERMS.items()
        if any(term in text for term in terms)
    ]

    score = 10 + sum(RESOURCE[x] for x in resource_hits)
    score += sum(GENRES[x] for x in genres)
    if genres:
        score += 15
    if any(x in text for x in ("download", "downloadable", "get the pack")):
        score += 6
    if any(x in text for x in ("hip-hop", "trap", "dubstep", "metal", "orchestral")) and not genres:
        score -= 12

    return score, genres, categories[:3], "ok"

def translate_ru(text):
    text = clean_text(text)
    if not text or len(text.split()) <= 2:
        return text

    endpoint = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=auto&tl=ru&dt=t&q=" + quote(text)
    )

    last_error = None
    for attempt in range(3):
        try:
            raw = fetch(endpoint, timeout=12)
            data = json.loads(raw.decode("utf-8"))
            translated = "".join(
                part[0] for part in data[0]
                if isinstance(part, list) and part and part[0]
            ).strip()
            if translated:
                return translated
        except Exception as exc:
            last_error = exc
            time.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"translation failed: {last_error}")

def build_post(item, score, genres, categories):
    title_ru = translate_ru(item["title"])
    desc_ru = translate_ru(item["description"]) if item["description"] else ""

    # Never publish an untranslated normal English title.
    if len(item["title"].split()) >= 4 and title_ru.lower() == item["title"].lower():
        raise RuntimeError("translation returned original title")

    tags = " ".join("#" + x for x in categories) or "#resources"
    genre_line = "🎯 <b>ПОД ТВОЙ ЖАНР</b>" if genres else ""
    if len(desc_ru) > 320:
        desc_ru = desc_ru[:317].rsplit(" ", 1)[0] + "..."

    parts = [f"🎛 <b>{html.escape(title_ru)}</b>", "", f"🏷 {tags}"]
    if genre_line:
        parts.append(genre_line)
    if desc_ru:
        parts += ["", html.escape(desc_ru)]
    parts += [
        "",
        f"📡 <i>{html.escape(item['source'])}</i>",
        f"🔗 <a href=\"{html.escape(item['link'], quote=True)}\">Открыть материал</a>",
    ]
    return "\n".join(parts)

def telegram_send(text):
    if not TOKEN or not CHANNEL:
        raise RuntimeError("Telegram secrets are missing")
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": CHANNEL,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=15) as r:
        response = json.loads(r.read().decode("utf-8"))
    if not response.get("ok"):
        raise RuntimeError(str(response))

def main():
    if not TOKEN or not CHANNEL:
        raise SystemExit("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL missing")

    print("START FINAL STRICT MULTI-SOURCE SCAN")
    seen = load_seen()
    all_items = []

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(parse_feed, s, u): s for s, u in SOURCES}
        for future in as_completed(futures):
            source = futures[future]
            try:
                items = future.result()
                print(f"FOUND {len(items)} from {source}")
                all_items.extend(items)
            except Exception as exc:
                print(f"FEED ERROR {source}: {exc}")

    unique = {fingerprint(item): item for item in all_items}
    candidates = []
    rejected = 0

    for item in unique.values():
        if fingerprint(item) in seen:
            continue
        score, genres, categories, reason = classify(item)
        if score >= 30:
            candidates.append((score, item, genres, categories))
        else:
            rejected += 1

    candidates.sort(key=lambda x: x[0], reverse=True)
    print(f"CANDIDATES={len(candidates)} REJECTED={rejected}")

    posted = 0
    errors = 0

    for score, item, genres, categories in candidates[:12]:
        try:
            post = build_post(item, score, genres, categories)
            telegram_send(post)
            seen.add(fingerprint(item))
            posted += 1
            print(f"POSTED score={score} genre={len(genres)} categories={categories}: {item['title']}")
            time.sleep(0.2)
        except Exception as exc:
            errors += 1
            print(f"SKIPPED {item['title']}: {exc}")

    save_seen(seen)
    print(f"DONE published={posted} rejected={rejected} candidates={len(candidates)} errors={errors}")

if __name__ == "__main__":
    main()

