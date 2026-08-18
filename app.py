import os, time, json, hashlib, re, html, concurrent.futures
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@gptnews999")

FEEDS = [
    ("Bedroom Producers Blog", "https://bedroomproducersblog.com/feed/"),
    ("SoundShockAudio", "https://soundshockaudio.com/feed/"),
]

CATEGORIES = {
    "🎤 VOCALS": ["vocal", "vocals", "voice", "acapella", "acapellas"],
    "🎹 PRESETS": ["preset", "presets", "serum preset", "vital preset", "sylenth preset", "massive preset", "spire preset"],
    "🥁 SAMPLES": ["sample pack", "samples", "drum kit", "drum pack", "one-shot", "one shot", "loop pack", "loops", "sound pack", "sound library"],
    "🔌 PLUGINS": ["free vst", "vst plugin", "vst3", "audio plugin", "plugin", "effect plugin", "synth plugin", "instrument plugin"],
    "🎛️ MIDI / TEMPLATES": ["midi", "midi pack", "template", "templates", "project file", "project files"],
    "🎼 KONTAKT": ["kontakt", "decent sampler", "sfz library"],
}

FREE = [
    "free download", "free to download", "free plugin", "free vst",
    "free sample pack", "free samples", "free presets", "free preset",
    "free sound library", "free kontakt", "now free", "is free",
    "are free", "available for free", "released for free", "freebie",
    "giveaway", "100% free", "completely free", "totally free",
]

BAD = [
    "free trial", "trial version", "free demo", "demo version", "trial",
    "subscription", "subscription required", "membership required",
    "rent-to-own", "rent to own", "paid", "buy now", "commercial license",
    "discount", "sale", "coupon", "upgrade required",
]

GENERIC = [
    "best ", "top ", "how to", "guide", "tutorial", "review",
    "comparison", "versus", "what is", "explained", "tips",
    "roundup", "round-up", "interview", "podcast",
]

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def load_seen():
    try:
        with open("seen.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_seen(seen):
    with open("seen.json", "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)

def get_feed(source_url):
    raw = urlopen(
        Request(source_url, headers={"User-Agent": "GPTNewsRelay/3.0"}),
        timeout=10
    ).read()

    root = ET.fromstring(raw)
    items = []

    for x in root.findall(".//item"):
        title = clean(x.findtext("title"))
        link = clean(x.findtext("link"))
        desc = clean(x.findtext("description"))
        if title and link:
            items.append((title, link, desc))

    # Atom fallback
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for x in root.findall(".//a:entry", ns):
            title = clean(x.findtext("a:title", "", ns))
            link_el = x.find("a:link", ns)
            link = link_el.attrib.get("href", "") if link_el is not None else ""
            desc = clean(
                x.findtext("a:summary", "", ns)
                or x.findtext("a:content", "", ns)
            )
            if title and link:
                items.append((title, link, desc))

    return items[-30:]

def classify(title, desc):
    text = (title + " " + desc).lower()

    if any(x in title.lower() for x in GENERIC):
        return None

    for tag, words in CATEGORIES.items():
        if any(w in text for w in words):
            return tag

    return None

def is_free(title, desc):
    text = (title + " " + desc).lower()

    if any(x in text for x in BAD):
        return False

    return any(x in text for x in FREE) or bool(re.search(r"\bFREE\b", title, re.I))

def send_telegram(text, url):
    payload = json.dumps({
        "chat_id": CHANNEL,
        "text": text + "\n\n🔗 " + url,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }).encode()

    req = Request(
        "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    urlopen(req, timeout=15).read()

def make_post(tag, title, desc, source):
    desc = clean(desc)
    if len(desc) > 600:
        desc = desc[:597] + "..."

    out = [
        tag,
        "",
        "<b>" + html.escape(title) + "</b>",
    ]

    if desc:
        out += ["", html.escape(desc)]

    out += [
        "",
        "🆓 <b>FREE</b>",
        "📌 " + html.escape(source),
    ]

    return "\n".join(out)

def check_source(item):
    source, url = item
    try:
        return source, get_feed(url), None
    except Exception as e:
        return source, [], str(e)

def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing")
        return 1

    seen = load_seen()
    published = 0
    skipped = 0
    errors = []

    print("CHECKING FEEDS...", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
        results = list(pool.map(check_source, FEEDS))

    for source, items, error in results:
        if error:
            print("FEED ERROR", source, error, flush=True)
            errors.append(source + ": " + error)
            continue

        print("FOUND", len(items), "items from", source, flush=True)

        for title, link, desc in items:
            key = hashlib.sha256(link.encode()).hexdigest()

            if key in seen:
                continue

            tag = classify(title, desc)

            if not tag:
                skipped += 1
                seen[key] = int(time.time())
                continue

            if not is_free(title, desc):
                skipped += 1
                seen[key] = int(time.time())
                continue

            try:
                send_telegram(make_post(tag, title, desc, source), link)

                # Mark as seen ONLY after successful Telegram delivery.
                seen[key] = int(time.time())
                published += 1

                print("POSTED:", title, flush=True)
                time.sleep(0.35)

            except Exception as e:
                errors.append("Telegram: " + str(e))
                print("TELEGRAM ERROR:", e, flush=True)

    save_seen(seen)

    print(
        "DONE",
        "published=", published,
        "skipped=", skipped,
        "errors=", len(errors),
        flush=True
    )

    if errors:
        for e in errors:
            print("ERROR:", e, flush=True)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
