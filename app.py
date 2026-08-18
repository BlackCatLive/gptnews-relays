import os
import time
import json
import hashlib
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.parse import quote, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@gptnews999")

# Источники. KVR напрямую иногда отдаёт 403 GitHub Actions,
# поэтому вместо него используем Google News с site:kvraudio.com.
SOURCES = [
    ("Bedroom Producers Blog", "https://bedroomproducersblog.com/feed/"),
    ("Rekkerd", "https://rekkerd.org/feed/"),
    ("MusicRadar", "https://www.musicradar.com/feeds.xml"),
    ("Sound On Sound", "https://www.soundonsound.com/news/sosrssfeed.php"),

    ("Google: free VST", "https://news.google.com/rss/search?q=free+VST+plugin+music+production&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free samples", "https://news.google.com/rss/search?q=free+sample+pack+music+production&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free vocals", "https://news.google.com/rss/search?q=free+vocal+pack+vocals+music+production&hl=en-US&gl=US&ceid=US:en"),
    ("Google: Serum presets", "https://news.google.com/rss/search?q=free+Serum+presets&hl=en-US&gl=US&ceid=US:en"),
    ("Google: Vital presets", "https://news.google.com/rss/search?q=free+Vital+presets&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free drum kits", "https://news.google.com/rss/search?q=free+drum+kit+one+shots+samples&hl=en-US&gl=US&ceid=US:en"),
    ("Google: KVR free audio", "https://news.google.com/rss/search?q=site%3Akvraudio.com+%22free%22+plugin+OR+VST+OR+soundware&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free synth presets", "https://news.google.com/rss/search?q=free+synth+presets+wavetable+producer&hl=en-US&gl=US&ceid=US:en"),
]

GOOD = {
    "free download": 12, "free plugin": 12, "free vst": 12,
    "free sample pack": 14, "free samples": 10, "free sample": 9,
    "free vocal pack": 18, "free vocals": 16, "free vocal": 14,
    "free presets": 14, "free preset": 12,
    "serum presets": 16, "serum preset": 14,
    "vital presets": 16, "vital preset": 14,
    "drum kit": 9, "one-shot": 8, "one shot": 8,
    "loops": 6, "midi": 5, "soundbank": 7, "sound bank": 7,
    "royalty-free": 7, "royalty free": 7,
    "free synthesizer": 10, "free synth": 10,
    "free effect": 9, "free effects": 9,
    "free instrument": 9,
}

# Жёстко исключаем пробные версии и подписки.
BAD = [
    "free trial", "trial version", "trial plugin", "trial",
    "demo version", "demo only", "subscription required",
    "requires subscription", "membership required", "monthly subscription",
    "annual subscription", "rent-to-own", "rent to own",
    "subscription", "membership", "paid only",
]

GENERIC = [
    "tutorial", "how to", "guide", "review", "comparison",
    "interview", "podcast", "newsletter", "tips", "explained",
]

LIMITED = [
    "limited time", "for a limited time", "until", "ends on",
    "through", "expires", "while supplies last", "this week",
    "today only", "48 hours", "72 hours", "until the end",
]

DEAL_ONLY = ["sale", "discount", "coupon", "deal", "off"]


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def fetch(url, timeout=12):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 GPTNewsRelay/8.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    )
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_feed(raw):
    root = ET.fromstring(raw)
    items = []

    for x in root.findall(".//item"):
        title = clean(x.findtext("title"))
        link = clean(x.findtext("link"))
        desc = clean(x.findtext("description"))
        if title and link:
            items.append((title, link, desc))

    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for x in root.findall(".//a:entry", ns):
            title = clean(x.findtext("a:title", default="", namespaces=ns))
            desc = clean(x.findtext("a:summary", default="", namespaces=ns))
            link = ""
            for l in x.findall("a:link", ns):
                if l.attrib.get("href"):
                    link = l.attrib["href"]
                    break
            if title and link:
                items.append((title, link, desc))

    return items


def load_seen():
    try:
        with open("seen_v4.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen(seen):
    with open("seen_v4.json", "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)


def canonical_url(url):
    try:
        p = urlsplit(url)
        # Убираем типичный трекинг, чтобы одинаковая статья не считалась новой.
        q = re.sub(r"(^|&)(utm_[^=]+|gclid|fbclid)=[^&]*", "", p.query)
        q = re.sub(r"&&+", "&", q).strip("&")
        return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), q, ""))
    except Exception:
        return url


def translate_ru(text):
    text = clean(text)
    if not text:
        return ""
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single?client=gtx"
            "&sl=auto&tl=ru&dt=t&q=" + quote(text[:900])
        )
        raw = fetch(url, timeout=8)
        data = json.loads(raw.decode("utf-8"))
        return "".join(x[0] for x in data[0] if x and x[0]).strip() or text
    except Exception as e:
        print("TRANSLATION ERROR:", e, flush=True)
        return text


def analyze(title, desc):
    text = (title + " " + desc).lower()

    bad = [x for x in BAD if x in text]
    if bad:
        return False, -999, bad, False

    has_free = any(x in text for x in [
        "free", "0.00", "$0", "£0", "€0", "pay what you like",
        "pay-what-you-like", "name your price"
    ])
    if not has_free:
        return False, 0, [], False

    score = sum(v for k, v in GOOD.items() if k in text)

    # Бесплатность должна быть связана с нашим типом контента.
    if not any(k in text for k in [
        "plugin", "vst", "sample", "vocal", "preset", "serum",
        "vital", "drum", "one-shot", "loop", "soundbank", "synth"
    ]):
        return False, score, [], False

    # Общие статьи/обзоры не нужны, если нет сильного совпадения.
    if any(x in text for x in GENERIC) and score < 14:
        return False, score, [], False

    limited = any(x in text for x in LIMITED)
    return score >= 8, score, [], limited


def category(title, desc):
    text = (title + " " + desc).lower()

    if any(x in text for x in [
        "vocal", "vocals", "acapella", "a cappella", "voice pack", "choir"
    ]):
        return "🎤 VOCALS", "#vocals"

    if any(x in text for x in [
        "serum", "vital", "preset", "presets", "soundbank", "sound bank"
    ]):
        return "🎹 PRESETS", "#presets"

    if any(x in text for x in [
        "sample pack", "samples", "drum kit", "drums", "one-shot",
        "one shot", "loops", "wav pack", "sound pack"
    ]):
        return "🥁 SAMPLES", "#samples"

    if any(x in text for x in [
        "vst", "plugin", "plug-in", "effect plugin", "instrument plugin",
        "synthesizer", "synth plugin"
    ]):
        return "🔌 PLUGINS", "#plugins"

    if "midi" in text:
        return "🎼 MIDI", "#midi"

    return "🎛️ OTHER", "#other"


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
    with urlopen(req, timeout=12) as r:
        r.read()


def make_post(title, desc, url, source, limited):
    tag, hashtag = category(title, desc)

    ru_title = translate_ru(title)
    short_desc = clean(desc)[:350]
    ru_desc = translate_ru(short_desc) if short_desc else ""

    status = "🟡 <b>FREE — ОГРАНИЧЕННОЕ ВРЕМЯ</b>" if limited else "🟢 <b>FREE — БЕСПЛАТНО</b>"

    text = (
        f"{tag}  {hashtag}\n\n"
        f"<b>{html.escape(ru_title)}</b>\n\n"
        f"{status}\n"
        f"📌 Источник: {html.escape(source)}"
    )

    if ru_desc:
        text += f"\n\n{html.escape(ru_desc)}"

    low = (title + " " + desc).lower()
    if "royalty-free" in low or "royalty free" in low:
        text += "\n\n✅ Royalty-free"

    telegram(text, url)


def fetch_source(source):
    name, url = source
    try:
        items = parse_feed(fetch(url))
        return name, items, None
    except Exception as e:
        return name, [], e


def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing", flush=True)
        return 1

    seen = load_seen()
    published = 0
    skipped = 0
    errors = 0
    candidates = []

    print("START FAST MULTI-SOURCE SCAN", flush=True)

    # Параллельно читаем источники — поэтому релей больше не должен
    # ждать каждый RSS по очереди.
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_source, s) for s in SOURCES]
        for future in as_completed(futures):
            name, items, err = future.result()
            if err:
                errors += 1
                print(f"FEED ERROR {name}: {err}", flush=True)
                continue

            print(f"FOUND {len(items)} from {name}", flush=True)

            for title, url, desc in items[:25]:
                canon = canonical_url(url)
                key = hashlib.sha256(canon.encode()).hexdigest()

                if key in seen:
                    continue

                ok, score, bad, limited = analyze(title, desc)

                # Сразу запоминаем просмотренные URL, чтобы не гонять их
                # по кругу на следующих запусках.
                seen[key] = int(time.time())

                if not ok:
                    skipped += 1
                    continue

                # Дедупликация ещё до публикации: одна и та же статья
                # из BPB + Google News попадёт только один раз.
                candidates.append((score, limited, name, title, url, desc, key))

    # Самое релевантное — первым.
    candidates.sort(key=lambda x: x[0], reverse=True)

    MAX_POSTS_PER_RUN = 12
    for score, limited, source, title, url, desc, key in candidates:
        if published >= MAX_POSTS_PER_RUN:
            break

        try:
            make_post(title, desc, url, source, limited)
            published += 1
            print(
                f"POSTED [{score}] {source}: {title}"
                + (" [LIMITED]" if limited else ""),
                flush=True
            )
            time.sleep(0.25)
        except Exception as e:
            errors += 1
            print(f"TELEGRAM ERROR {source}: {e}", flush=True)

    save_seen(seen)
    print(
        f"DONE published={published} skipped={skipped} "
        f"candidates={len(candidates)} errors={errors}",
        flush=True
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
