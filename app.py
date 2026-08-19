import os
import re
import json
import time
import html
import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.parse import quote
from xml.etree import ElementTree as ET

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@gptnews999").strip()
SEEN_FILE = "seen.json"

CORE = {
    "rominimal": 25,
    "romanian minimal": 25,
    "deep minimal": 24,
    "minimal house": 22,
    "minimal tech": 20,
    "minimal techno": 20,
    "deep tech": 18,
    "deep house": 17,
    "tech house": 16,
    "minimal": 14,
}

RELATED = {
    "house": 7,
    "techno": 6,
    "afro house": 6,
    "organic house": 5,
    "progressive house": 5,
    "melodic house": 4,
    "indie dance": 4,
    "electronic": 2,
}

GENRES = {**CORE, **RELATED}

RESOURCE_TERMS = {
    "vocal pack": 30,
    "vocal packs": 30,
    "free vocals": 30,
    "free vocal": 30,
    "acapella": 28,
    "acapellas": 28,
    "sample pack": 24,
    "sample packs": 24,
    "free sample": 22,
    "free samples": 22,
    "drum kit": 22,
    "drum kits": 22,
    "one-shot": 20,
    "one shot": 20,
    "loop pack": 20,
    "loops": 15,
    "serum preset": 28,
    "serum presets": 28,
    "vital preset": 28,
    "vital presets": 28,
    "preset pack": 24,
    "preset packs": 24,
    "free preset": 22,
    "free presets": 22,
    "free vst3": 25,
    "free vst": 24,
    "free plugin": 24,
    "free plugins": 24,
    "free synth": 22,
    "free synthesizer": 22,
    "free effect": 20,
    "free effects": 20,
    "midi": 12,
}

FREE_TERMS = (
    "free", "free download", "free pack", "free sample",
    "freeware", "gratis", "100% free", "completely free",
    "royalty-free", "royalty free",
)

HARD_BAD = (
    "free trial", "trial version", "trial", "demo version",
    "subscription", "subscribe", "rent-to-own", "rent to own",
    "monthly plan", "annual plan", "paid only", "paid-only",
    "membership", "free to try", "limited trial",
)

EDITORIAL_PATTERNS = (
    r"^\s*(the\s+)?best\b",
    r"^\s*\d+\s+",
    r"\btop\s+\d+\b",
    r"\b\d+\s+best\b",
    r"\b\d+\s+free\s+(sample|samples|sample packs|vst|vsts|presets|plugins)\b",
)

EDITORIAL_WORDS = (
    "roundup", "listicle", "guide to", "how to", "review",
    "reviews", "best platforms", "top platforms", "for all genres",
    "all genres", "collection of", "sample radar:",
    "artist releases", "new single", "new album", "anniversary",
)

UNRELATED = (
    "trap", "hip-hop", "hip hop", "dubstep", "metal",
    "country", "reggae", "drum and bass", "dnb", "orchestral",
)

CATEGORY_TERMS = {
    "vocals": ("vocal", "vocals", "acapella", "acapellas"),
    "presets": ("serum preset", "vital preset", "preset"),
    "samples": ("sample pack", "sample packs", "sample", "loops", "one-shot"),
    "drums": ("drum kit", "drum kits", "drums", "percussion"),
    "plugins": ("free vst", "free vst3", "free plugin", "free plugins", "synth", "effect"),
    "midi": ("midi",),
}

SOURCES = [
    ("Bedroom Producers Blog", "https://bedroomproducersblog.com/feed/", ""),
    ("Rekkerd", "https://rekkerd.org/feed/", ""),
    ("MusicRadar", "https://www.musicradar.com/feeds.xml", ""),
    ("Google: Rominimal",
     "https://news.google.com/rss/search?q=" + quote('"rominimal" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset")'),
     "rominimal"),
    ("Google: Deep Minimal",
     "https://news.google.com/rss/search?q=" + quote('"deep minimal" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset")'),
     "deep minimal"),
    ("Google: Minimal House",
     "https://news.google.com/rss/search?q=" + quote('"minimal house" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset")'),
     "minimal house"),
    ("Google: Deep Tech",
     "https://news.google.com/rss/search?q=" + quote('"deep tech" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset")'),
     "deep tech"),
    ("Google: Tech House",
     "https://news.google.com/rss/search?q=" + quote('"tech house" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset")'),
     "tech house"),
    ("Google: House Vocals",
     "https://news.google.com/rss/search?q=" + quote('"house" ("free vocal pack" OR "free acapella" OR "free vocals") music production'),
     "house"),
    ("Google: Serum",
     "https://news.google.com/rss/search?q=" + quote('"free Serum preset" music production'),
     "serum preset"),
    ("Google: Vital",
     "https://news.google.com/rss/search?q=" + quote('"free Vital preset" music production'),
     "vital preset"),
    ("Google: Free VST",
     "https://news.google.com/rss/search?q=" + quote('"free VST" OR "free VST3" music production'),
     "free vst"),
    ("Google: Free Samples",
     "https://news.google.com/rss/search?q=" + quote('"free sample pack" music production -roundup -list -best'),
     ""),
]

def clean(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def fetch(url, timeout=15):
    req = Request(url, headers={"User-Agent": "GPTNewsRelay/10.0"})
    with urlopen(req, timeout=timeout) as response:
        return response.read()

def parse_feed(source, url, hint):
    try:
        root = ET.fromstring(fetch(url))
    except Exception as exc:
        print(f"FEED ERROR {source}: {exc}")
        return []

    result = []
    for node in root.iter():
        if node.tag.lower().split("}")[-1] not in ("item", "entry"):
            continue

        title = desc = link = ""
        for child in list(node):
            tag = child.tag.lower().split("}")[-1]
            value = clean(child.text or "")
            if tag == "title":
                title = value
            elif tag in ("description", "summary", "content") and not desc:
                desc = value
            elif tag == "link":
                link = child.attrib.get("href", "") or value

        if title and link:
            result.append({
                "source": source,
                "title": title,
                "description": desc,
                "link": link,
                "hint": hint,
            })

    print(f"FOUND {len(result[:100])} from {source}")
    return result[:100]

def fingerprint(item):
    return hashlib.sha256(
        (item["title"] + "|" + item["link"]).encode()
    ).hexdigest()

def has_term(text, term):
    return re.search(
        r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])",
        text
    ) is not None

def classify(item):
    title = item["title"].lower()
    desc = item["description"].lower()
    hint = item.get("hint", "").lower()
    text = title + " " + desc

    resources = [x for x in RESOURCE_TERMS if x in text]
    if not resources:
        return -999, [], [], "not-resource"

    if not any(x in text or x in hint for x in FREE_TERMS):
        return -999, [], [], "no-free-signal"

    if any(x in text for x in HARD_BAD):
        return -999, [], [], "paid-or-trial"

    if any(re.search(p, title) for p in EDITORIAL_PATTERNS):
        return -999, [], [], "editorial-list"

    if any(x in title for x in EDITORIAL_WORDS):
        return -999, [], [], "editorial"

    if any(x in title for x in (
        "release", "releases", "new single", "new album",
        "artist", "celebrates", "anniversary"
    )):
        return -999, [], [], "artist-news"

    genres = [g for g in GENRES if has_term(text, g)]
    if not genres and hint:
        genres = [g for g in GENRES if has_term(hint, g)]

    categories = [
        name for name, terms in CATEGORY_TERMS.items()
        if any(term in text for term in terms)
    ]

    universal = any(x in categories for x in ("vocals", "presets", "plugins"))

    if not genres and not universal:
        return -999, [], [], "no-target-genre"

    if not genres and any(x in categories for x in ("samples", "drums")):
        return -999, [], [], "generic-sample-no-genre"

    if any(x in text for x in UNRELATED) and not genres:
        return -999, [], [], "unrelated-genre"

    core = [g for g in genres if g in CORE]
    related = [g for g in genres if g in RELATED and g not in CORE]

    if core:
        tier = "CORE"
    elif related:
        tier = "RELATED"
    else:
        tier = "UNIVERSAL"

    score = 20
    score += sum(RESOURCE_TERMS[x] for x in resources)
    score += sum(GENRES[x] for x in genres)

    if tier == "CORE":
        score += 25
    elif tier == "RELATED":
        score += 8

    if "royalty-free" in text or "royalty free" in text:
        score += 8

    if "download" in text:
        score += 6

    # Once a concrete free resource passes all hard filters, do not let
    # an arbitrary score threshold throw it away.
    score = max(score, 25)

    return score, [f"tier:{tier}"] + genres, categories[:4], "ok"

def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            value = json.load(f)
        return set(value) if isinstance(value, list) else set()
    except Exception:
        return set()

def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-5000:], f, ensure_ascii=False, indent=2)

def translate_ru(text):
    text = clean(text)
    if not text or len(text.split()) < 3:
        return text

    url = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=auto&tl=ru&dt=t&q=" + quote(text)
    )

    for attempt in range(3):
        try:
            data = json.loads(fetch(url, 12).decode("utf-8"))
            result = "".join(
                part[0] for part in data[0]
                if isinstance(part, list) and part and part[0]
            ).strip()
            if result:
                return result
        except Exception as exc:
            if attempt == 2:
                print(f"TRANSLATION ERROR: {exc}")
            time.sleep(attempt + 1)

    return text

def build_post(item, genres, categories):
    title = translate_ru(item["title"])
    desc = translate_ru(item["description"]) if item["description"] else ""

    tier = next(
        (x.split(":", 1)[1] for x in genres if x.startswith("tier:")),
        "UNIVERSAL"
    )
    real_genres = [x for x in genres if not x.startswith("tier:")]

    tags = " ".join("#" + x for x in categories) or "#resources"

    if tier == "CORE":
        badge = "🎯 <b>ПОД ТВОЙ ЖАНР</b>"
    elif tier == "RELATED":
        badge = "🟡 <b>БЛИЗКИЙ ЖАНР</b>"
    else:
        badge = "🔧 <b>УНИВЕРСАЛЬНЫЙ РЕСУРС</b>"

    parts = [
        f"🎛 <b>{html.escape(title)}</b>",
        "",
        f"🏷 {tags}",
        badge,
    ]

    if real_genres:
        parts.append("🎚 " + html.escape(", ".join(real_genres[:3])))

    if desc:
        parts += ["", html.escape(desc[:500])]

    parts += [
        "",
        "🆓 <b>БЕСПЛАТНО</b>",
        f"📡 {html.escape(item['source'])}",
        f'🔗 <a href="{html.escape(item["link"], quote=True)}">Открыть материал</a>',
    ]

    return "\n".join(parts)

def telegram_send(text):
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")

    payload = json.dumps({
        "chat_id": CHANNEL,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()

    req = Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(req, timeout=20) as response:
        result = json.loads(response.read().decode())

    if not result.get("ok"):
        raise RuntimeError(str(result))

def main():
    if not TOKEN:
        raise SystemExit("ERROR: TELEGRAM_BOT_TOKEN missing")

    print("START NEW GENRE-AWARE RELAY")

    seen = load_seen()
    all_items = []

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(parse_feed, source, url, hint): source
            for source, url, hint in SOURCES
        }

        for future in as_completed(futures):
            try:
                all_items.extend(future.result())
            except Exception as exc:
                print(f"SOURCE ERROR: {exc}")

    unique = {fingerprint(x): x for x in all_items}

    candidates = []
    reasons = Counter()

    for item in unique.values():
        if fingerprint(item) in seen:
            continue

        score, genres, categories, reason = classify(item)

        if score >= 25:
            candidates.append((score, item, genres, categories))
        else:
            reasons[reason] += 1

    candidates.sort(key=lambda x: x[0], reverse=True)

    print(f"CANDIDATES={len(candidates)} REJECTED={sum(reasons.values())}")
    print("REJECTION_REASONS=" + json.dumps(dict(reasons), ensure_ascii=False))

    core = sum("tier:CORE" in x[2] for x in candidates)
    related = sum("tier:RELATED" in x[2] for x in candidates)
    universal = sum("tier:UNIVERSAL" in x[2] for x in candidates)

    print(f"ACCEPTED_TIERS CORE={core} RELATED={related} UNIVERSAL={universal}")

    posted = 0
    errors = 0

    for score, item, genres, categories in candidates[:12]:
        try:
            telegram_send(build_post(item, genres, categories))
            seen.add(fingerprint(item))
            posted += 1
            print(
                f"POSTED score={score} genre={genres} "
                f"categories={categories}: {item['title']}"
            )
            time.sleep(0.5)
        except Exception as exc:
            errors += 1
            print(f"POST ERROR {item['title']}: {exc}")

    save_seen(seen)

    print(
        f"DONE published={posted} "
        f"candidates={len(candidates)} errors={errors}"
    )

if __name__ == "__main__":
    main()
