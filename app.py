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

    ("Google: free VST downloads", "https://news.google.com/rss/search?q=%22free+VST%22+%22download%22+plugin&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free sample downloads", "https://news.google.com/rss/search?q=%22free+sample+pack%22+download&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free vocal downloads", "https://news.google.com/rss/search?q=%22free+vocal+pack%22+download&hl=en-US&gl=US&ceid=US:en"),
    ("Google: Serum preset downloads", "https://news.google.com/rss/search?q=%22free+Serum+presets%22+download&hl=en-US&gl=US&ceid=US:en"),
    ("Google: Vital preset downloads", "https://news.google.com/rss/search?q=%22free+Vital+presets%22+download&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free drum kit downloads", "https://news.google.com/rss/search?q=%22free+drum+kit%22+download+samples&hl=en-US&gl=US&ceid=US:en"),
    ("Google: KVR free downloads", "https://news.google.com/rss/search?q=site%3Akvraudio.com+%22free+download%22+VST+OR+plugin+OR+soundware&hl=en-US&gl=US&ceid=US:en"),
    ("Google: free synth presets downloads", "https://news.google.com/rss/search?q=%22free+synth+presets%22+download&hl=en-US&gl=US&ceid=US:en"),
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
    "interview", "podcast", "newsletter", "tips", "tricks",
    "explained", "video tutorial", "watch the video",
]

EDITORIAL_DOMAINS = {
    "musictech.com", "weareyou.com", "routenote.com", "remezcla.com",
    "bedroomproducersblog.com", "musicradar.com", "futurecdn.net",
    "attackmagazine.com", "musicgateway.com"
}

ARTICLE_PATTERNS = [
    "best ", "top ", "ultimate ", "guide to", "how to",
    "tips", "tricks", "tutorial", "review", "roundup",
    "10 free", "20 free", "50 free", "70 free",
    "list of", "platforms", "pack features", "anniversary pack",
    "partners with", "offers ", "article", "news:"
]

LISTICLE = [
    "best free", "top 5", "top 10", "top 20", "top 50",
    "ultimate list", "list of", "platforms for free",
    "sample packs for", "packs to kickstart", "unlock your sound",
    "10 free", "20 free", "50 free", "70 free",
    "2026 guide", "roundup", "round-up", "buyer guide",
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


def analyze(title, desc, source=""):
    text = (title + " " + desc).lower()
    source_low = source.lower()

    # Never publish trials/subscriptions/rent-to-own.
    bad = [x for x in BAD if x in text]
    if bad:
        return False, -999, bad, False

    has_free = any(x in text for x in [
        "free", "0.00", "$0", "£0", "€0",
        "pay what you like", "pay-what-you-like", "name your price"
    ])
    if not has_free:
        return False, 0, [], False

    product_terms = [
        "plugin", "vst", "vst3", "au plugin", "aax",
        "sample pack", "samples", "vocal", "vocals",
        "preset", "presets", "serum", "vital",
        "drum kit", "drums", "one-shot", "one shot",
        "loop", "loops", "soundbank", "sound bank",
        "synth", "midi", "kontakt", "decentsampler"
    ]

    if not any(k in text for k in product_terms):
        return False, 0, [], False

    score = sum(v for k, v in GOOD.items() if k in text)

    # Google News is discovery only. Reject editorial/listicle pages
    # unless they look like a concrete product-release/download notice.
    if source_low.startswith("google:"):
        direct = [
            "free download", "download", "available for free",
            "released", "releases", "is free", "now free",
            "free plugin", "free vst", "free sample pack",
            "free vocal pack", "free presets", "free preset"
        ]
        if not any(x in text for x in direct):
            return False, score, [], False

        # The RSS result can be an editorial article that merely mentions
        # a free product. Do not post those noisy aggregators.
        m = re.search(r'https?://([^/\s]+)', desc)
        host = m.group(1).lower().split(":")[0] if m else ""
        host = host[4:] if host.startswith("www.") else host

        if any(host == d or host.endswith("." + d) for d in EDITORIAL_DOMAINS):
            # Allow BPB only when the title itself is clearly a concrete free
            # product/sample/preset/plugin release, not a listicle.
            if host.endswith("bedroomproducersblog.com"):
                concrete = any(x in title.lower() for x in [
                    "free sample pack", "free plugin", "free vst",
                    "free presets", "free preset", "free drum", "free vocal"
                ])
                if not concrete:
                    return False, score, [], False
            else:
                return False, score, [], False

        if any(x in text for x in LISTICLE) or any(x in title.lower() for x in ARTICLE_PATTERNS):
            return False, score, [], False

    # For all sources, weak generic articles are not enough.
    if any(x in text for x in GENERIC) and score < 18:
        return False, score, [], False

    # If the title is clearly a list/article headline, reject it globally.
    title_low = title.lower()
    if any(x in title_low for x in [
        "best free", "top 5", "top 10", "top 20", "ultimate list",
        "free sample downloads:", "free samples:", "free vocals:",
        "free drum kits:", "free vst downloads:", "free plugins:",
        "guide", "roundup"
    ]):
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

    print("START FAST MULTI-SOURCE SCAN v10 PRODUCT FILTER", flush=True)

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

                ok, score, bad, limited = analyze(title, desc, name)

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

    by_source = {}
    for item in candidates:
        by_source[item[2]] = by_source.get(item[2], 0) + 1
    print("CANDIDATES BY SOURCE:", by_source, flush=True)

    MAX_POSTS_PER_RUN = 12  # safe cap; raise after quality check
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
