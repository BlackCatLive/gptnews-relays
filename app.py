import os
import time
import json
import hashlib
import re
import html
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from xml.etree import ElementTree as ET


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@gptnews999")

FEEDS = [
    (
        "Bedroom Producers Blog",
        "https://bedroomproducersblog.com/feed/"
    ),
    (
        "Rekkerd Samples & Presets",
        "https://rekkerd.org/category/samples-and-presets/feed/"
    ),
    (
        "Rekkerd",
        "https://rekkerd.org/feed/"
    ),
]


# -------------------------
# КЛЮЧЕВЫЕ СЛОВА
# -------------------------

POSITIVE = {
    "vocal": 10,
    "vocals": 10,
    "vocal pack": 12,
    "acapella": 10,
    "acapellas": 10,

    "sample pack": 9,
    "sample pack free": 12,
    "samples": 6,
    "sound pack": 7,
    "soundbank": 6,
    "one-shot": 7,
    "drum kit": 8,
    "drum samples": 8,

    "serum": 9,
    "serum presets": 12,
    "vital": 9,
    "vital presets": 12,
    "preset": 8,
    "presets": 8,
    "synth presets": 9,

    "vst": 7,
    "vst3": 7,
    "plugin": 7,
    "audio plugin": 8,
    "effect plugin": 8,

    "minimal": 6,
    "minimal house": 8,
    "house": 4,
    "deep house": 5,
    "tech house": 5,

    "free": 6,
    "free download": 10,
    "freeware": 10,
    "royalty-free": 8,
    "free forever": 12,
}


NEGATIVE = {
    "free trial": -20,
    "trial": -15,
    "7-day trial": -25,
    "14-day trial": -25,
    "30-day trial": -25,
    "subscription": -20,
    "subscription required": -25,
    "monthly subscription": -25,
    "paid": -10,
    "buy now": -10,
    "sale": -8,
    "discount": -8,
    "deal": -8,
}


# -------------------------
# УТИЛИТЫ
# -------------------------

def clean(text):
    text = text or ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def score(text):
    text = text.lower()

    result = 0

    for word, points in POSITIVE.items():
        if word in text:
            result += points

    for word, points in NEGATIVE.items():
        if word in text:
            result += points

    return result


def category(text):
    t = text.lower()

    if any(x in t for x in [
        "vocal",
        "vocals",
        "acapella",
        "acapellas"
    ]):
        return "🎤 VOCALS", "#vocals"

    if any(x in t for x in [
        "serum",
        "vital",
        "preset",
        "presets",
        "synth presets"
    ]):
        return "🎹 PRESETS", "#presets"

    if any(x in t for x in [
        "sample pack",
        "samples",
        "sound pack",
        "soundbank",
        "one-shot",
        "drum kit",
        "drum samples"
    ]):
        return "🥁 SAMPLES", "#samples"

    if any(x in t for x in [
        "vst",
        "vst3",
        "plugin",
        "audio plugin",
        "effect plugin"
    ]):
        return "🔌 PLUGINS", "#plugins"

    if any(x in t for x in [
        "minimal",
        "house",
        "deep house",
        "tech house"
    ]):
        return "🎛️ HOUSE / MINIMAL", "#house"

    return "🎛️ MUSIC PRODUCTION", "#musicproduction"


# -------------------------
# TELEGRAM
# -------------------------

def send_telegram(text, url):

    data = {
        "chat_id": CHANNEL,
        "text": text + "\n\n🔗 " + url,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    request = urllib.request.Request(
        "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Content-Type": "application/json"
        }
    )

    response = urllib.request.urlopen(
        request,
        timeout=20
    )

    result = json.loads(
        response.read().decode("utf-8")
    )

    if not result.get("ok"):
        raise RuntimeError(
            "Telegram error: " + str(result)
        )


# -------------------------
# RSS
# -------------------------

def load_feed(source, url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "GPTNewsRelay/2.0"
        }
    )

    raw = urllib.request.urlopen(
        request,
        timeout=20
    ).read()

    root = ET.fromstring(raw)

    articles = []

    # обычный RSS
    for item in root.findall(".//item"):

        title = clean(
            item.findtext("title")
        )

        link = clean(
            item.findtext("link")
        )

        description = clean(
            item.findtext("description")
        )

        if title and link:
            articles.append(
                (
                    source,
                    title,
                    link,
                    description
                )
            )

    # Atom
    if not articles:

        namespace = {
            "atom": "http://www.w3.org/2005/Atom"
        }

        for entry in root.findall(
            ".//atom:entry",
            namespace
        ):

            title = clean(
                entry.findtext(
                    "atom:title",
                    default="",
                    namespaces=namespace
                )
            )

            description = clean(
                entry.findtext(
                    "atom:summary",
                    default="",
                    namespaces=namespace
                )
            )

            link = ""

            link_element = entry.find(
                "atom:link",
                namespace
            )

            if link_element is not None:
                link = link_element.attrib.get(
                    "href",
                    ""
                )

            if title and link:
                articles.append(
                    (
                        source,
                        title,
                        link,
                        description
                    )
                )

    return articles[-30:]


# -------------------------
# SEEN
# -------------------------

def load_seen():

    try:

        with open(
            "seen.json",
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return {}


def save_seen(seen):

    with open(
        "seen.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            seen,
            f,
            ensure_ascii=False
        )


# -------------------------
# MAIN
# -------------------------

def run():

    if not TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN missing",
            flush=True
        )

        return


    seen = load_seen()

    published = 0
    checked = 0


    for source, feed_url in FEEDS:

        print(
            "CHECK",
            source,
            feed_url,
            flush=True
        )

        try:

            articles = load_feed(
                source,
                feed_url
            )

            print(
                "FOUND",
                len(articles),
                source,
                flush=True
            )

        except Exception as e:

            print(
                "FEED ERROR",
                source,
                str(e),
                flush=True
            )

            continue


        for source, title, link, description in articles:

            checked += 1

            article_id = hashlib.sha256(
                link.encode("utf-8")
            ).hexdigest()


            if article_id in seen:
                continue


            text = (
                title
                + " "
                + description
            )

            article_score = score(text)


            # Помечаем как просмотренную,
            # чтобы не проверять её снова
            seen[article_id] = int(
                time.time()
            )


            print(
                "ARTICLE",
                article_score,
                title,
                flush=True
            )


            # Слишком слабый материал
            if article_score < 5:
                continue


            # Категория
            tag_name, hashtag = category(
                text
            )


            message = (
                f"{tag_name}\n\n"
                f"<b>{html.escape(title)}</b>\n\n"
                f"{html.escape(description[:700])}\n\n"
                f"🆓 <b>FREE</b>\n"
                f"📌 {html.escape(source)}\n"
                f"{hashtag}"
            )


            try:

                send_telegram(
                    message,
                    link
                )

                published += 1

                print(
                    "TELEGRAM OK:",
                    title,
                    flush=True
                )

                time.sleep(2)

            except Exception as e:

                print(
                    "TELEGRAM ERROR:",
                    str(e),
                    flush=True
                )


    save_seen(seen)


    print(
        f"DONE checked={checked} published={published}",
        flush=True
    )


# -------------------------
# HTTP SERVER
# -------------------------

class Handler(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path.startswith("/run"):

            run()

            body = b'{"ok":true}'

        else:

            body = b'{"ok":true}'


        self.send_response(200)

        self.send_header(
            "Content-Type",
            "application/json"
        )

        self.end_headers()

        self.wfile.write(body)


    def log_message(self, *args):
        pass


if __name__ == "__main__":

    # GitHub Actions запускает именно этот блок
    if os.getenv("GITHUB_ACTIONS"):

        run()

    else:

        port = int(
            os.getenv(
                "PORT",
                "10000"
            )
        )

        HTTPServer(
            ("0.0.0.0", port),
            Handler
        ).serve_forever()
