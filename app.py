# FINAL GPT News Relay
# Strict Russian-only Telegram feed for free music-production resources.

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
    "minimal house": 10,
    "deep minimal": 11,
    "rominimal": 12,
    "romanian minimal": 12,
    "minimal techno": 8,
    "minimal tech": 8,
    "deep tech": 8,
    "deep house": 7,
    "tech house": 6,
}

RESOURCE = {
    "acapella": 12,
    "acapellas": 12,
    "vocal pack": 12,
    "vocal packs": 12,
    "free vocals": 12,
    "free vocal": 12,
    "sample pack": 10,
    "sample packs": 10,
    "free samples": 9,
    "free sample": 9,
    "drum kit": 9,
    "drum kits": 9,
    "one-shot": 8,
    "one shot": 8,
    "loops": 7,
    "loop pack": 9,
    "serum preset": 11,
    "serum presets": 11,
    "vital preset": 11,
    "vital presets": 11,
    "preset pack": 9,
    "preset packs": 9,
    "free vst": 10,
    "free vst3": 10,
    "free plugin": 9,
    "free plugins": 9,
    "free synth": 8,
    "free synthesizer": 8,
    "free effect": 8,
    "free effects": 8,
    "midi": 6,
}

FREE_WORDS = (
    "free",
    "gratis",
    "no cost",
    "100% free",
    "completely free",
    "free download",
    "free pack",
    "free sample",
)

BAD = (
    "trial",
    "demo version",
    "free trial",
    "subscription",
    "subscribe",
    "rent-to-own",
    "rent to own",
    "monthly plan",
    "annual plan",
    "paid only",
    "paid-only",
    "buy now",
    "upgrade",
    "membership",
    "free to try",
    "limited trial",
)

EDITORIAL = (
    "best free",
    "top 10",
    "top 20",
    "top 50",
    "top 100",
    "ultimate list",
    "best platforms",
    "roundup",
    "list of",
    "guide to",
    "how to",
    "review",
    "reviews",
    "news",
    "new single",
    "album",
    "song",
    "release",
    "celebrate",
    "ministry",
)

CATEGORY_TERMS = {
    "vocals": (
        "vocal",
        "vocals",
        "acapella",
        "acapellas",
    ),
    "presets": (
        "serum preset",
        "serum presets",
        "vital preset",
        "vital presets",
        "preset",
    ),
    "samples": (
        "sample pack",
        "sample packs",
        "free samples",
        "one-shot",
        "one shot",
        "loops",
    ),
    "drums": (
        "drum kit",
        "drum kits",
        "drums",
        "percussion",
    ),
    "plugins": (
        "free vst",
        "free vst3",
        "free plugin",
        "free plugins",
        "synth",
        "effect",
    ),
    "midi": (
        "midi",
    ),
}

SOURCES = [
    (
        "Bedroom Producers Blog",
        "https://bedroomproducersblog.com/feed/",
    ),
    (
        "Rekkerd",
        "https://rekkerd.org/feed/",
    ),
    (
        "MusicRadar",
        "https://www.musicradar.com/feeds",
    ),
    (
        "Google: free sample packs",
        "https://news.google.com/rss/search?q="
        + quote('"free sample pack" music production'),
    ),
    (
        "Google: free vocals",
        "https://news.google.com/rss/search?q="
        + quote('"free vocal pack" OR "free acapella" music production'),
    ),
    (
        "Google: Serum presets",
        "https://news.google.com/rss/search?q="
        + quote('"free Serum preset" music production'),
    ),
    (
        "Google: Vital presets",
        "https://news.google.com/rss/search?q="
        + quote('"free Vital preset" music production'),
    ),
    (
        "Google: free VST",
        "https://news.google.com/rss/search?q="
        + quote('"free VST" plugin music production'),
    ),
    (
        "Google: free drum kits",
        "https://news.google.com/rss/search?q="
        + quote('"free drum kit" music production'),
    ),
    (
        "Google: minimal house resources",
        "https://news.google.com/rss/search?q="
        + quote(
            '"minimal house" '
            '("free sample" OR "free preset" OR "free vocal")'
        ),
    ),
    (
        "Google: deep minimal resources",
        "https://news.google.com/rss/search?q="
        + quote(
