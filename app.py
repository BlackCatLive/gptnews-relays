
import os, re, json, time, html, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.parse import quote
from xml.etree import ElementTree as ET

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "").strip()
SEEN_FILE = "seen.json"

CORE_GENRES = {
    "minimal house": 18,
    "deep minimal": 20,
    "rominimal": 22,
    "romanian minimal": 22,
    "minimal techno": 16,
    "minimal tech": 16,
    "deep tech": 15,
    "deep house": 14,
    "tech house": 13,
    "minimal": 10,
}

RELATED_GENRES = {
    "afro house": 7,
    "progressive house": 6,
    "organic house": 5,
    "melodic house": 5,
    "indie dance": 4,
    "electro house": 3,
    "house": 5,
    "techno": 5,
    "electronic": 2,
}

GENRES = {**CORE_GENRES, **RELATED_GENRES}

RESOURCE = {
    "acapella": 14, "acapellas": 14, "vocal pack": 14, "vocal packs": 14,
    "free vocals": 14, "free vocal": 14,
    "sample pack": 11, "sample packs": 11, "free samples": 10, "free sample": 10,
    "drum kit": 10, "drum kits": 10, "one-shot": 9, "one shot": 9,
    "loops": 8, "loop pack": 10,
    "serum preset": 13, "serum presets": 13, "vital preset": 13, "vital presets": 13,
    "preset pack": 11, "preset packs": 11, "free preset": 10, "free presets": 10,
    "free vst": 11, "free vst3": 11, "free plugin": 10, "free plugins": 10,
    "free synth": 9, "free synthesizer": 9, "free effect": 9, "free effects": 9,
    "midi": 7,
}

FREE_WORDS = (
    "free", "gratis", "no cost", "100% free", "completely free",
    "free download", "free pack", "free sample", "freeware",
)

BAD = (
    "trial", "demo version", "free trial", "subscription", "subscribe",
    "rent-to-own", "rent to own", "monthly plan", "annual plan",
    "paid only", "paid-only", "membership", "free to try", "limited trial",
)

EDITORIAL = (
    "best free", "best platforms", "roundup", "list of", "guide to",
    "how to", "review", "reviews", "new single", "album", "song",
    "celebrate", "ministry", "artist releases", "anniversary", "news:",
    "platforms for", "for all genres", "all genres",
    "over 100,000", "over 100000", "unlimited free samples",
    "sample packs in 2026", "top platforms",
)

EDITORIAL_PATTERNS = (
    r"\btop\s+\d+\b",
    r"\b\d+\s+free\s+sample\s+packs?\b",
    r"\b\d+\s+free\s+samples?\b",
    r"\b\d+\s+free\s+vsts?\b",
    r"\b\d+\s+free\s+presets?\b",
    r"\b\d+\s+free\s+plugins?\b",
)

UNRELATED = (
    "trap", "hip-hop", "hip hop", "dubstep", "metal", "orchestral",
    "country", "reggae", "drum and bass", "dnb", "cinematic music",
)

CATEGORY_TERMS = {
    "vocals": ("vocal", "vocals", "acapella", "acapellas"),
    "presets": ("serum preset", "serum presets", "vital preset", "vital presets", "preset"),
    "samples": ("sample pack", "sample packs", "free samples", "one-shot", "one shot", "loops"),
    "drums": ("drum kit", "drum kits", "drums", "percussion"),
    "plugins": ("free vst", "free vst3", "free plugin", "free plugins", "synth", "effect"),
    "midi": ("midi",),
}

# name, RSS URL, genre/resource hint for Google RSS results
SOURCES = [
    ("Bedroom Producers Blog", "https://bedroomproducersblog.com/feed/", ""),
    ("Rekkerd", "https://rekkerd.org/feed/", ""),
    ("MusicRadar", "https://www.musicradar.com/feeds.xml", ""),
    ("Google: Minimal House", "https://news.google.com/rss/search?q=" + quote('"minimal house" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset" OR "free VST")'), "minimal house"),
    ("Google: Deep Minimal", "https://news.google.com/rss/search?q=" + quote('"deep minimal" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset")'), "deep minimal"),
    ("Google: Rominimal", "https://news.google.com/rss/search?q=" + quote('"rominimal" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset")'), "rominimal"),
    ("Google: Deep Tech", "https://news.google.com/rss/search?q=" + quote('"deep tech" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset")'), "deep tech"),
    ("Google: Tech House", "https://news.google.com/rss/search?q=" + quote('"tech house" ("free sample" OR "free sample pack" OR "free vocal" OR "free preset")'), "tech house"),
    ("Google: House Vocals", "https://news.google.com/rss/search?q=" + quote('"house" ("free vocal pack" OR "free acapella" OR "free vocals") music production'), "house"),
    ("Google: Minimal Samples", "https://news.google.com/rss/search?q=" + quote('"minimal" ("free sample pack" OR "free drum kit" OR "free one shot") music production'), "minimal"),
    ("Google: Serum", "https://news.google.com/rss/search?q=" + quote('"free Serum preset" music production'), "Serum presets"),
    ("Google: Vital", "https://news.google.com/rss/search?q=" + quote('"free Vital preset" music production'), "Vital presets"),
    ("Google: Free VST", "https://news.google.com/rss/search?q=" + quote('"free VST" OR "free VST3" music production'), "free VST"),
    ("Google: Free Samples", "https://news.google.com/rss/search?q=" + quote('"free sample pack" music production -roundup -list -best'), ""),
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
    req = Request(url, headers={"User-Agent": "GPTNewsRelay/8.0"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()

def parse_feed(source, url, hint=""):
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
            elif tag in ("description", "summary", "content") and not desc:
                desc = text
            elif tag in ("pubdate", "published", "updated") and not date:
                date = text
            elif tag == "link":
                link = child.attrib.get("href", "") or text
        if title and link:
            result.append({
                "source": source, "title": title, "description": desc,
                "link": link, "date": date, "hint": hint
            })
    return result[:100]

def fingerprint(item):
    return hashlib.sha256((item["title"] + "|" + item["link"]).encode()).hexdigest()

def genre_tier(genres):
    core = [g for g in genres if g in CORE_GENRES]
    related = [g for g in genres if g in RELATED_GENRES and g not in CORE_GENRES]

    if core:
        return "CORE", core, related
    if related:
        return "RELATED", core, related
    return "UNIVERSAL", core, related


def classify(item):
    main_text = (item["title"] + " " + item["description"]).lower()
    hint = (item.get("hint") or "").lower()
    source = (item.get("source") or "").lower()
    text = main_text + " " + hint

    resource_hits = [term for term in RESOURCE if term in main_text]
    if not resource_hits:
        return -999, [], [], "not-resource"

    free_from_hint = any(
        x in source for x in ("free", "minimal", "rominimal", "deep tech", "tech house", "house vocals")
    )
    if not any(term in main_text for term in FREE_WORDS) and not free_from_hint:
        return -999, [], [], "no-free-signal"

    if any(term in main_text for term in BAD):
        return -999, [], [], "paid-or-trial"

    if any(term in main_text for term in EDITORIAL):
        return -999, [], [], "editorial"

    if any(re.search(pattern, main_text) for pattern in EDITORIAL_PATTERNS):
        return -999, [], [], "editorial-list"

    # Reject pages whose title is clearly a catalog/listicle rather than
    # one concrete downloadable product/resource.
    title_lower = item["title"].lower()
    if any(x in title_lower for x in (
        "platforms", "best of", "ultimate", "collection of",
        "free resources", "free resource list", "sample radar:",
    )):
        return -999, [], [], "catalog-title"

    direct_resource = any(term in main_text for term in (
        "download", "downloadable", "sample pack", "preset pack",
        "vocal pack", "acapella pack", "free vst", "free vst3",
        "free plugin", "free sample", "free samples", "free preset",
        "free presets", "free drum kit", "one-shot", "one shot",
    ))
    resource_from_hint = any(
        x in source for x in ("free vst", "free samples", "free sample", "serum", "vital", "vocals", "samples")
    )
    if not direct_resource and not resource_from_hint:
        return -999, [], [], "not-direct-resource"

    genres = [term for term in GENRES if term in text]
    tier, core_genres, related_genres = genre_tier(genres)

    categories = [
        category for category, terms in CATEGORY_TERMS.items()
        if any(term in main_text for term in terms)
    ]

    # Generic presets/plugins/vocals are useful across the target styles.
    generic_ok = any(x in categories for x in ("presets", "plugins", "vocals"))
    if not genres and not generic_ok:
        return -999, [], [], "no-target-genre"

    # Generic sample/drum resources are NOT enough by themselves.
    # Generic plugins, presets and vocals remain useful across the target styles.
    if not genres and any(x in categories for x in ("samples", "drums")):
        return -999, [], [], "generic-sample-no-genre"

    if any(x in main_text for x in UNRELATED) and not genres:
        return -999, [], [], "unrelated-genre"

    if any(x in main_text for x in (
        "release free sample pack", "releases free sample pack",
        "release a free sample pack", "new single", "new album",
    )):
        return -999, [], [], "artist-news"

    score = 12 + sum(RESOURCE[x] for x in resource_hits) + sum(GENRES[x] for x in genres)

    if tier == "CORE":
        score += 22
    elif tier == "RELATED":
        score += 7

    if any(x in core_genres for x in ("rominimal", "deep minimal", "minimal house")):
        score += 10
    if any(x in main_text for x in ("royalty-free", "royalty free", "commercial use")):
        score += 5
    if any(x in main_text for x in ("download", "downloadable", "get the pack")):
        score += 7
    if any(x in main_text for x in UNRELATED) and genres:
        score -= 5

    if score < 35:
        return -999, [], [], "low-score"

    tagged_genres = [f"tier:{tier}"] + genres
    return score, tagged_genres, categories[:3], "ok"

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
            data = json.loads(fetch(endpoint, 12).decode("utf-8"))
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

    if len(item["title"].split()) >= 4 and title_ru.lower() == item["title"].lower():
        raise RuntimeError("translation returned original title")

    tags = " ".join("#" + x for x in categories) or "#resources"
    tier = next((x.split(":", 1)[1] for x in genres if x.startswith("tier:")), "UNIVERSAL")
    real_genres = [x for x in genres if not x.startswith("tier:")]
    genre_text = ", ".join(real_genres[:3])

    parts = [
        f"🎛 <b>{html.escape(title_ru)}</b>",
        "",
        f"🏷 {tags}",
    ]

    if tier == "CORE":
        parts.append("🎯 <b>ПОД ТВОЙ ЖАНР</b>" + (": " + html.escape(genre_text) if genre_text else ""))
    elif tier == "RELATED":
        parts.append("🟡 <b>БЛИЗКИЙ ЖАНР</b>" + (": " + html.escape(genre_text) if genre_text else ""))
    else:
        parts.append("🔧 <b>УНИВЕРСАЛЬНЫЙ РЕСУРС</b>")

    if desc_ru:
        if len(desc_ru) > 320:
            desc_ru = desc_ru[:317].rsplit(" ", 1)[0] + "..."
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

    req = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(req, timeout=15) as r:
        response = json.loads(r.read().decode("utf-8"))

    if not response.get("ok"):
        raise RuntimeError(str(response))

def main():
    if not TOKEN or not CHANNEL:
        raise SystemExit("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL missing")

    print("START FINAL GENRE-AWARE MULTI-SOURCE SCAN")

    seen = load_seen()
    all_items = []

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(parse_feed, source, url, hint): source
            for source, url, hint in SOURCES
        }

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
    rejection_reasons = Counter()

    for item in unique.values():
        if fingerprint(item) in seen:
            continue

        score, genres, categories, reason = classify(item)

        if score >= 35:
            candidates.append((score, item, genres, categories))
        else:
            rejected += 1
            rejection_reasons[reason] += 1

    candidates.sort(key=lambda x: x[0], reverse=True)

    print(f"CANDIDATES={len(candidates)} REJECTED={rejected}")
    print("REJECTION_REASONS=" + json.dumps(dict(rejection_reasons), ensure_ascii=False))

    posted = 0
    errors = 0

    for score, item, genres, categories in candidates[:12]:
        try:
            post = build_post(item, score, genres, categories)
            telegram_send(post)

            seen.add(fingerprint(item))
            posted += 1

            print(
                f"POSTED score={score} genre={genres} "
                f"categories={categories}: {item['title']}"
            )

            time.sleep(0.2)

        except Exception as exc:
            errors += 1
            print(f"SKIPPED {item['title']}: {exc}")

    save_seen(seen)

    print(
        f"DONE published={posted} rejected={rejected} "
        f"candidates={len(candidates)} errors={errors}"
    )

if __name__ == "__main__":
    main()


