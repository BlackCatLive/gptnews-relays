import os
import json
import time
import hashlib
import re
import html
import urllib.request
from xml.etree import ElementTree as ET

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@gptnews999")

FEEDS = [
    ("SoundShockAudio", "https://soundshockaudio.com/feed/"),
    ("Bedroom Producers Blog", "https://bedroomproducersblog.com/feed/"),
]

POSITIVE = {
    "vocal": 8,
    "vocals": 8,
    "vocal pack": 10,
    "sample pack": 7,
    "samples": 5,
    "serum": 6,
    "vital": 6,
    "preset": 7,
    "presets": 7,
    "minimal": 5,
    "minimal house": 8,
    "house": 3,
    "vst": 5,
    "plugin": 5,
    "drum": 5,
    "one-shot": 5,
    "one shot": 5,
    "royalty-free": 5,
    "free download": 8,
    "free": 3,
}

NEGATIVE = {
    "trial": -20,
    "free trial": -30,
    "demo": -15,
    "subscription": -25,
    "subscription required": -30,
    "paid": -12,
    "buy now": -15,
    "monthly": -15,
    "annual": -15,
    "per month": -15,
    "7-day trial": -30,
    "14-day trial": -30,
    "30-day trial": -30,
}


def clean(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def score(text):
    text = text.lower()

    value = 0

    for word, points in POSITIVE.items():
        if word in text:
            value += points

    for word, points in NEGATIVE.items():
        if word in text:
            value += points

    return value


def load_seen():
    try:
        with open("seen.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen(seen):
    with open("seen.json", "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def telegram_send(text, url):
    data = json.dumps({
        "chat_id": CHANNEL,
        "text": text + "\n\n🔗 " + url,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def get_feed(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GPTNewsRelay/1.0"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()

    root = ET.fromstring(raw)

    result = []

    for item in root.findall(".//item"):
        title = clean(item.findtext("title"))
        link = clean(item.findtext("link"))
        description = clean(item.findtext("description"))

        if title and link:
            result.append((title, link, description))

    return result[-30:]


def get_category(text):
    text = text.lower()

    if "vocal" in text:
        return "🎤 VOCALS"

    if any(x in text for x in ["preset", "serum", "vital"]):
        return "🎹 PRESETS"

    if any(x in text for x in ["sample", "drum", "one-shot", "one shot"]):
        return "🥁 SAMPLES"

    if any(x in text for x in ["vst", "plugin"]):
        return "🔌 PLUGINS"

    return "🎛️ MUSIC PRODUCTION"


def is_trial_or_paid(text):
    text = text.lower()

    blocked = [
        "free trial",
        "subscription required",
        "trial version",
        "trial version available",
        "7-day trial",
        "14-day trial",
        "30-day trial",
        "monthly subscription",
        "annual subscription",
        "paid subscription",
        "requires subscription",
    ]

    return any(x in text for x in blocked)


def run():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing")
        return

    seen = load_seen()
    published = 0

    for source, feed_url in FEEDS:
        try:
            articles = get_feed(feed_url)

            for title, link, description in articles:
                article_id = hashlib.sha256(link.encode()).hexdigest()

                if article_id in seen:
                    continue

                full_text = f"{title} {description}"
                current_score = score(full_text)

                # Отбрасываем trial / subscription / paid предложения
                if is_trial_or_paid(full_text):
                    print("SKIP PAID/TRIAL:", title)
                    seen[article_id] = int(time.time())
                    continue

                # Нужен достаточно релевантный материал
                if current_score < 5:
                    print("SKIP LOW SCORE:", title)
                    seen[article_id] = int(time.time())
                    continue

                category = get_category(full_text)

                message = (
                    f"{category}\n\n"
                    f"<b>{html.escape(title)}</b>\n\n"
                    f"{html.escape(description[:600])}\n\n"
                    f"🆓 <b>FREE</b>\n"
                    f"📌 {html.escape(source)}"
                )

                try:
                    telegram_send(message, link)

                    seen[article_id] = int(time.time())
                    published += 1

                    print("PUBLISHED:", title)

                    time.sleep(2)

                except Exception as error:
                    print("TELEGRAM ERROR:", error)

        except Exception as error:
            print("FEED ERROR:", source, error)

    save_seen(seen)

    print("DONE. Published:", published)


if __name__ == "__main__":
    run()
