import os
import time
import json
import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse, quote
from xml.etree import ElementTree as ET

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@gptnews999")

# SoundShockAudio is now the primary source.
SOUND_SHOCK = [
    ("🔌 PLUGINS", "https://soundshockaudio.com/vst-plugins/"),
    ("🥁 SAMPLES", "https://soundshockaudio.com/samples-and-loops/"),
    ("🎹 PRESETS", "https://soundshockaudio.com/synth-presets/"),
    ("🎛️ TEMPLATES", "https://soundshockaudio.com/daw-templates/"),
    ("🎼 KONTAKT", "https://soundshockaudio.com/kontakt-instruments/"),
    ("🎹 MIDI", "https://soundshockaudio.com/midi/"),
]

BPB_FEED = ("Bedroom Producers Blog", "https://bedroomproducersblog.com/feed/")

BAD = [
    "trial", "demo", "subscription", "membership",
    "rent-to-own", "rent to own", "paid", "buy now",
    "commercial license", "discount", "coupon",
]

GENERIC = [
    "best ", "top ", "how to", "guide", "tutorial",
    "review", "comparison", "versus", "what is",
    "explained", "tips", "roundup", "round-up",
    "interview", "podcast",
]

EXCLUDED_PATHS = {
    "free-downloads", "browse", "about-us", "blog", "category",
    "vst-plugins", "samples-and-loops", "synth-presets",
    "daw-templates", "kontakt-instruments", "midi",
    "free-kontakt-instruments", "free-vst-plugins",
}

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current_href = dict(attrs).get("href")
            self.current_text = []

    def handle_data(self, data):
        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current_href is not None:
            text = re.sub(r"\s+", " ", " ".join(self.current_text)).strip()
            self.links.append((self.current_href, text))
            self.current_href = None
            self.current_text = []

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

def load_seen():
    try:
        with open("seen_v2.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_seen(seen):
    with open("seen_v2.json", "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)

def fetch(url):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (GPTNewsRelay/4.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    return urlopen(req, timeout=12).read()

def product_links(page_url):
    raw = fetch(page_url)
    parser = LinkParser()
    parser.feed(raw.decode("utf-8", errors="ignore"))

    result = []
    seen = set()

    for href, text in parser.links:
        if not href or not text:
            continue

        absolute = urljoin(page_url, href)
        p = urlparse(absolute)

        if p.netloc not in ("soundshockaudio.com", "www.soundshockaudio.com"):
            continue

        parts = [x for x in p.path.split("/") if x]
        if len(parts) != 1:
            continue

        slug = parts[0].lower()
        if slug in EXCLUDED_PATHS:
            continue

        if absolute in seen:
            continue

        # Product cards generally have a short, meaningful title.
        if len(text) < 3 or len(text) > 180:
            continue

        if any(x in text.lower() for x in GENERIC):
            continue

        seen.add(absolute)
        result.append((clean(text), absolute))

    return result

def get_bpb():
    raw = fetch(BPB_FEED[1])
    root = ET.fromstring(raw)
    out = []

    for x in root.findall(".//item"):
        title = clean(x.findtext("title"))
        link = clean(x.findtext("link"))
        desc = clean(x.findtext("description"))
        if title and link:
            out.append((title, link, desc))

    return out[-20:]

def bpb_is_free(title, desc):
    text = (title + " " + desc).lower()

    if any(x in text for x in BAD):
        return False

    return (
        "free" in title.lower()
        or "free download" in text
        or "free plugin" in text
        or "free sample" in text
        or "free preset" in text
        or "free vst" in text
    )


def translate_ru(text):
    """Translate short English titles to Russian without an API key."""
    text = clean(text)
    if not text:
        return text
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single?client=gtx"
            "&sl=auto&tl=ru&dt=t&q=" + quote(text)
        )
        raw = fetch(url)
        data = json.loads(raw.decode("utf-8"))
        translated = "".join(part[0] for part in data[0] if part and part[0])
        return translated.strip() or text
    except Exception as e:
        print("TRANSLATION ERROR:", e, flush=True)
        return text


def send_telegram(text, url):
    payload = json.dumps({
        "chat_id": CHANNEL,
        "text": text + "\n\n🔗 " + url,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()

    req = Request(
        "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    with urlopen(req, timeout=15) as response:
        response.read()

def post(tag, title, url, source):
    title = clean(title)
    ru_title = translate_ru(title)

    text = (
        f"{tag}\n\n"
        f"<b>{html.escape(ru_title)}</b>\n\n"
        f"🆓 <b>FREE</b>\n"
        f"📌 {html.escape(source)}"
    )

    send_telegram(text, url)

def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing", flush=True)
        return 1

    seen = load_seen()
    published = 0
    errors = 0

    print("START", flush=True)

    # Check SoundShock categories.
    for tag, page in SOUND_SHOCK:
        try:
            items = product_links(page)
            print(f"{tag}: FOUND {len(items)} product links", flush=True)

            # Only publish a few on the first run, then new ones normally.
            for title, url in items[:5]:
                key = hashlib.sha256(url.encode()).hexdigest()

                if key in seen:
                    continue

                try:
                    post(tag, title, url, "SoundShockAudio")
                    seen[key] = int(time.time())
                    published += 1
                    print("POSTED:", title, flush=True)
                    time.sleep(0.4)
                except Exception as e:
                    errors += 1
                    print("TELEGRAM ERROR:", e, flush=True)

        except Exception as e:
            errors += 1
            print("SOUND SHOCK ERROR:", tag, e, flush=True)

    # BPB is backup only; never post ordinary articles.
    try:
        bpb_items = get_bpb()
        print("BPB:", len(bpb_items), "items", flush=True)

        for title, url, desc in bpb_items:
            key = hashlib.sha256(url.encode()).hexdigest()

            if key in seen:
                continue

            if not bpb_is_free(title, desc):
                seen[key] = int(time.time())
                continue

            try:
                tag = "🎛️ MUSIC PRODUCTION"
                low = (title + " " + desc).lower()

                if "vocal" in low:
                    tag = "🎤 VOCALS"
                elif "preset" in low or "serum" in low or "vital" in low:
                    tag = "🎹 PRESETS"
                elif "sample" in low or "drum" in low:
                    tag = "🥁 SAMPLES"
                elif "vst" in low or "plugin" in low:
                    tag = "🔌 PLUGINS"

                post(tag, title, url, "Bedroom Producers Blog")
                seen[key] = int(time.time())
                published += 1
                print("POSTED BPB:", title, flush=True)
                time.sleep(0.4)

            except Exception as e:
                errors += 1
                print("TELEGRAM ERROR:", e, flush=True)

    except Exception as e:
        errors += 1
        print("BPB ERROR:", e, flush=True)

    save_seen(seen)

    print(
        f"DONE published={published} errors={errors}",
        flush=True
    )

    return 0

if __name__ == "__main__":
    raise SystemExit(main())

