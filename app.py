import os,time,json,hashlib,re,html
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.request import Request,urlopen
from urllib.parse import quote
from xml.etree import ElementTree as ET

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
CHANNEL=os.getenv("TELEGRAM_CHANNEL","@gptnews999")
SECRET=os.getenv("RELAY_SECRET","")

FEEDS=[
    ("SoundShockAudio","https://soundshockaudio.com/feed/"),
    ("Bedroom Producers Blog","https://bedroomproducersblog.com/feed/")
]

POS={
    "vocal":8,"vocals":8,"vocal pack":10,
    "sample pack":7,"samples":5,
    "serum":6,"vital":6,
    "preset":7,"presets":7,
    "minimal":5,"house":3,
    "vst":5,"plugin":5,
    "drum":5,"one-shot":5,
    "royalty-free":5,"free download":6,"free":3
}

NEG={
    "trial":-12,"demo":-10,
    "free trial":-15,
    "subscription":-12,
    "paid":-8,"buy now":-8
}

def clean(s):
    return re.sub(
        r"\s+"," ",
        html.unescape(re.sub(r"<[^>]+>"," ",s or ""))
    ).strip()

def score(t):
    t=t.lower()
    s=sum(v for k,v in POS.items() if k in t)
    s+=sum(v for k,v in NEG.items() if k in t)

    if any(x in t for x in (
        "free trial",
        "subscription required",
        "7-day trial",
        "14-day trial",
        "30-day trial"
    )):
        s-=30

    return s

def translate(text):
    if not text:
        return ""

    try:
        url=(
            "https://translate.googleapis.com/translate_a/single"
            "?client=gtx&sl=auto&tl=ru&dt=t&q="+quote(text[:4000])
        )

        req=Request(
            url,
            headers={"User-Agent":"Mozilla/5.0"}
        )

        raw=urlopen(req,timeout=20).read().decode("utf-8")
        data=json.loads(raw)

        return "".join(
            part[0] for part in data[0] if part[0]
        ).strip()

    except Exception as e:
        print("TRANSLATE ERROR:",e,flush=True)
        return text

def load():
    try:
        return json.load(
            open("seen.json",encoding="utf-8")
        )
    except:
        return {}

def save(x):
    json.dump(
        x,
        open("seen.json","w",encoding="utf-8"),
        ensure_ascii=False
    )

def tg(text,url):
    data=json.dumps({
        "chat_id":CHANNEL,
        "text":text+"\n\n🔗 "+url,
        "parse_mode":"HTML",
        "disable_web_page_preview":False
    }).encode()

    req=Request(
        "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
        data=data,
        headers={"Content-Type":"application/json"}
    )

    urlopen(req,timeout=20).read()

def feed(url):
    raw=urlopen(
        Request(
            url,
            headers={"User-Agent":"GPTNewsRelay/1.0"}
        ),
        timeout=20
    ).read()

    root=ET.fromstring(raw)
    out=[]

    for x in root.findall(".//item"):
        title=clean(x.findtext("title"))
        link=clean(x.findtext("link"))
        desc=clean(x.findtext("description"))

        if title and link:
            out.append((title,link,desc))

    return out[-20:]

def run():
    if not TOKEN:
        return {"ok":False,"error":"missing token"}

    seen=load()
    n=0

    for source,url in FEEDS:
        try:
            for title,link,desc in feed(url):

                k=hashlib.sha256(
                    link.encode()
                ).hexdigest()

                if k in seen:
                    continue

                text=title+" "+desc
                seen[k]=int(time.time())

                if score(text)<5:
                    continue

                low=text.lower()

                if "vocal" in low:
                    tag="🎤 VOCALS"
                elif any(x in low for x in ("preset","serum","vital")):
                    tag="🎹 PRESETS"
                elif any(x in low for x in ("sample","drum")):
                    tag="🥁 SAMPLES"
                elif any(x in low for x in ("vst","plugin")):
                    tag="🔌 PLUGIN"
                else:
                    tag="🎛️ MUSIC PRODUCTION"

                ru_title=translate(title)
                ru_desc=translate(desc[:1500])

                message=(
                    f"{tag}\n\n"
                    f"<b>{html.escape(ru_title)}</b>\n\n"
                    f"{html.escape(ru_desc[:700])}\n\n"
                    f"🆓 <b>FREE</b>\n"
                    f"📌 {html.escape(source)}"
                )

                tg(message,link)

                n+=1
                time.sleep(3)

        except Exception as e:
            print(source,e,flush=True)

    save(seen)

    return {
        "ok":True,
        "published":n
    }

class H(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path.startswith("/run"):

            if SECRET and self.path != "/run?key="+SECRET:
                self.send_response(403)
                self.end_headers()
                return

            body=json.dumps(run()).encode()

        else:
            body=b'{"ok":true}'

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/json"
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self,*a):
        pass

HTTPServer(
    ("0.0.0.0",int(os.getenv("PORT","10000"))),
    H
).serve_forever()
