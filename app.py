import os
import time
import json
import hashlib
import html
import re
from urllib.request import Request, urlopen
from urllib.parse import quote
from xml.etree import ElementTree as ET

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@gptnews999")

# Многоисточниковый поиск: RSS + Google News RSS-поиск.
# Google News RSS позволяет искать свежие публикации по ключевым словам,
# а не зависеть от одного сайта.
SOURCES = [
    ("Bedroom Producers Blog", "https://bedroomproducersblog.com/feed/"),
    ("KVR Audio", "https://www.kvraudio.com/news-feed.php"),
    ("Rekkerd", "https://rekkerd.org/feed/"),
    ("Google: free VST", "https://news.google.com/rss/search?q=free+VST+plugin+music+production&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free samples", "https://news.google.com/rss/search?q=free+sample+pack+music+production&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free vocals", "https://news.google.com/rss/search?q=free+vocal+pack+vocals+music+production&hl=en-US&gl=US&ceid=US:en"),
    ("Google: Serum presets", "https://news.google.com/rss/search?q=free+Serum+presets&hl=en-US&gl=US&ceid=US:en"),
    ("Google: Vital presets", "https://news.google.com/rss/search?q=free+Vital+presets&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free sound packs", "https://news.google.com/rss/search?q=free+drum+kit+OR+free+sound+pack+producer&hl=en-US&gl=US&ceid=US:en"),
]

# Слова, которые нужны нам для отбора.
GOOD = {
    "free": 5,
    "free download": 8,
    "free plugin": 10,
    "free vst": 10,
    "free sample": 9,
    "free samples": 9,
    "free sample pack": 12,
    "free vocal": 14,
    "free vocals": 14,
    "free vocal pack": 16,
    "free preset": 12,
    "free presets": 12,
    "free serum": 14,
    "serum preset": 12,
    "serum presets": 14,
    "vital preset": 12,
    "vital presets": 14,
    "sound bank": 6,
    "soundbank": 6,
    "drum kit": 8,
    "drum kit": 8,
    "one-shot": 7,
    "one shot": 7,
    "loops": 5,
    "midi": 4,
    "royalty-free": 6,
    "royalty free": 6,
}

# Жёсткий анти-триал. Такие материалы бот не публикует как FREE.
BAD = [
    "free trial", "trial version", "trial", "demo version", "demo plugin",
    "subscription required", "requires subscription", "membership required",
    "monthly subscription", "annual subscription", "rent-to-own", "rent to own",
    "subscription", "membership", "paid only", "commercial license required",
]

GENERIC = [
    "how to", "tutorial", "guide", "review", "comparison", "versus",
    "what is", "explained", "tips", "interview", "podcast", "newsletter",
]

# Источники/слова, которые часто дают нераздачи. Не блокируем скидки вообще,
# но скидка сама по себе не считается FREE.
DEAL_WORDS = ["sale", "discount", "coupon", "deal", "off", "offer"]


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def fetch(url, timeout=15):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 GPTNewsRelay/7.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_feed(raw):
    root = ET.fromstring(raw)
    items = []

    # RSS 2.0
    for x in root.findall(".//item"):
        title = clean(x.findtext("title"))
        link = clean(x.findtext("link"))
        desc = clean(x.findtext("description"))
        if title and link:
            items.append((title, link, desc))

    # Atom / некоторые Google News feeds
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for x in root.findall(".//a:entry", ns):
            title = clean(x.findtext("a:title", default="", namespaces=ns))
            desc = clean(x.findtext("a:summary", default="", namespaces=ns))
            link = ""
            for l in x.findall("a:link", ns):
                href = l.attrib.get("href", "")
                if href:
                    link = href
                    break
            if title and link:
                items.append((title, link, desc))

    return items


def load_seen():
    try:
        with open("seen_v3.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen(seen):
    with open("seen_v3.json", "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)


def translate_ru(text):
    text = clean(text)
    if not text:
        return text
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single?client=gtx"
            "&sl=auto&tl=ru&dt=t&q=" + quote(text)
        )
        raw = fetch(url, timeout=10)
        data = json.loads(raw.decode("utf-8"))
        translated = "".join(p[0] for p in data[0] if p and p[0])
        return translated.strip() or text
    except Exception as e:
        print("TRANSLATION ERROR:", e, flush=True)
        return text


def analyze(title, desc):
    text = (title + " " + desc).lower()
    score = 0
    for word, points in GOOD.items():
        if word in text:
            score += points

    bad = [x for x in BAD if x in text]
    # Trial/subscription = стоп независимо от количества FREE в тексте.
    if bad:
        return False, -999, bad

    # Просто "sale/discount" без FREE нам не нужен.
    has_free = "free" in text or "0.00" in text or "$0" in text or "£0" in text or "€0" in text
    if not has_free:
        return False, score, []

    return score >= 8, score, []


def category(title, desc):
    text = (title + " " + desc).lower()

    if any(x in text for x in ["vocal", "vocals", "acapella", "a cappella"]):
        return "🎤 VOCALS"
    if any(x in text for x in ["serum", "vital", "preset", "presets", "soundbank", "sound bank"]):
        return "🎹 PRESETS"
    if any(x in text for x in ["sample pack", "samples", "sample pack", "drum kit", "drums", "one-shot", "one shot", "loops"]):
        return "🥁 SAMPLES"
    if any(x in text for x in ["vst", "plugin", "plug-in", "effect plugin", "instrument plugin"]):
        return "🔌 PLUGINS"
    if "midi" in text:
        return "🎼 MIDI"
    return "🎛️ MUSIC PRODUCTION"


def telegram(text, url):
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
    with urlopen(req, timeout=15) as r:
        r.read()


def post(title, desc, url, source):
    tag = category(title, desc)
    ru_title = translate_ru(title)

    text = (
        f"{tag}\n\n"
        f"<b>{html.escape(ru_title)}</b>\n\n"
        f"🆓 <b>БЕСПЛАТНО</b>\n"
        f"📌 Источник: {html.escape(source)}"
    )

    # Если в описании есть royalty-free — показываем это отдельно.
    if "royalty-free" in (title + " " + desc).lower() or "royalty free" in (title + " " + desc).lower():
        text += "\n✅ Royalty-free"

    telegram(text, url)


def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing", flush=True)
        return 1

    seen = load_seen()
    published = 0
    skipped = 0
    errors = 0

    print("START MULTI-SOURCE SCAN", flush=True)

    # Лимит на один запуск, чтобы при первом запуске не заспамить канал.
    MAX_POSTS_PER_RUN = 12

    for source, feed_url in SOURCES:
        if published >= MAX_POSTS_PER_RUN:
            break

        try:
            items = parse_feed(fetch(feed_url))
            print(f"FOUND {len(items)} from {source}", flush=True)

            # Новые/последние элементы идут первыми для более быстрого результата.
            for title, url, desc in reversed(items):
                if published >= MAX_POSTS_PER_RUN:
                    break

                key = hashlib.sha256(url.encode()).hexdigest()
                if key in seen:
                    continue

                ok, score, bad = analyze(title, desc)

                # Запоминаем только реально просмотренные материалы.
                seen[key] = int(time.time())

                if not ok:
                    skipped += 1
                    continue

                try:
                    post(title, desc, url, source)
                    published += 1
                    print(f"POSTED [{score}] {source}: {title}", flush=True)
                    time.sleep(0.35)
                except Exception as e:
                    errors += 1
                    print("TELEGRAM ERROR:", e, flush=True)

        except Exception as e:
            errors += 1
            print("FEED ERROR", source, e, flush=True)

    save_seen(seen)
    print(f"DONE published={published} skipped={skipped} errors={errors}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
