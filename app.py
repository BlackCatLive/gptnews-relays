import os,time,json,hashlib,re,html
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.request import Request,urlopen
from xml.etree import ElementTree as ET

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
CHANNEL=os.getenv("TELEGRAM_CHANNEL","@gptnews999")
SECRET=os.getenv("RELAY_SECRET","")

FEEDS=[
    ("Bedroom Producers Blog","https://bedroomproducersblog.com/feed/"),
    ("SoundShockAudio","https://soundshockaudio.com/feed/"),
]

CATEGORY_RULES = [
    ("🎤 VOCALS", ["vocal","vocals","voice","acapella","acapellas"]),
    ("🎹 PRESETS", ["preset","presets","serum preset","vital preset","sylenth preset","massive preset","spire preset"]),
    ("🥁 SAMPLES", ["sample pack","samples","drum kit","drum pack","one-shot","one shot","loops","loop pack","sound pack","sound library"]),
    ("🔌 PLUGINS", ["vst","vst3","audio plugin","plugin","effect plugin","synth plugin","instrument plugin","au plugin"]),
    ("🎛️ MIDI / TEMPLATES", ["midi","midi pack","midi files","template","templates","project file","project files"]),
    ("🎼 KONTAKT", ["kontakt","decent sampler","sfz library"]),
]

HARD_REJECT = [
    "free trial","trial version","trial","demo version","demo only",
    "subscription","subscription required","membership required",
    "rent-to-own","rent to own","buy now","paid","commercial license",
    "only $","only €","only £","for $","for €","for £",
    "discount","sale","coupon","intro offer","introductory offer",
    "upgrade required","after the trial","after trial",
]

LIMITED_MARKERS = [
    "free until","free through","free for a limited time","limited time",
    "until august","until september","until october","until november",
    "until december","until january","until february","until march",
    "until april","until may","until june","until july",
]

FREE_MARKERS = [
    "free download","free to download","free plugin","free vst",
    "free sample pack","free samples","free presets","free preset",
    "free sound library","free kontakt","free kontakt library",
    "now free","is free","are free","available for free",
    "released for free","released free","giveaway","freebie",
    "100% free","completely free","totally free","free version",
]

GENERIC_ARTICLE_MARKERS = [
    "best ","top ","how to","guide","tutorial","review","reviews",
    "comparison","vs ","versus","what is","explained","tips",
    "roundup","round-up","list of","interview","podcast",
]

def clean(s):
    return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",s or ""))).strip()

def load():
    try:
        return json.load(open("seen.json",encoding="utf-8"))
    except Exception:
        return {}

def save(x):
    with open("seen.json","w",encoding="utf-8") as f:
        json.dump(x,f,ensure_ascii=False)

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
        Request(url,headers={"User-Agent":"GPTNewsRelay/2.0"}),
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

    if not out:
        ns={"a":"http://www.w3.org/2005/Atom"}
        for x in root.findall(".//a:entry",ns):
            title=clean(x.findtext("a:title",default="",namespaces=ns))
            link_el=x.find("a:link",ns)
            link=link_el.attrib.get("href","") if link_el is not None else ""
            desc=clean(
                x.findtext("a:summary",default="",namespaces=ns)
                or x.findtext("a:content",default="",namespaces=ns)
            )
            if title and link:
                out.append((title,link,desc))

    return out[-30:]

def category(title,desc):
    text=(title+" "+desc).lower()

    if any(x in title.lower() for x in GENERIC_ARTICLE_MARKERS):
        return None

    for tag,words in CATEGORY_RULES:
        if any(w in text for w in words):
            return tag
    return None

def is_free(title,desc):
    title_l=title.lower()
    text=(title+" "+desc).lower()

    if any(x in text for x in HARD_REJECT):
        return False,False

    title_has_free=any(x in title_l for x in FREE_MARKERS) or bool(
        re.search(r"\bFREE\b",title,re.I)
    )

    if not title_has_free:
        return False,False

    limited=any(x in text for x in LIMITED_MARKERS)
    return True,limited

def build_message(tag,title,desc,source,limited):
    label="🆓 <b>FREE</b>"
    if limited:
        label="⏳ <b>FREE — LIMITED TIME</b>"

    description=clean(desc)
    if len(description)>650:
        description=description[:647]+"..."

    parts=[
        tag,"",
        "<b>"+html.escape(title)+"</b>","",
    ]
    if description:
        parts.append(html.escape(description))
    parts.extend(["",label,"📌 "+html.escape(source)])
    return "\n".join(parts)

def run():
    if not TOKEN:
        return {"ok":False,"error":"missing token"}

    seen=load()
    published=0
    skipped=0
    errors=[]

    for source,url in FEEDS:
        try:
            items=feed(url)

            for title,link,desc in items:
                key=hashlib.sha256(link.encode()).hexdigest()

                if key in seen:
                    continue

                seen[key]=int(time.time())

                tag=category(title,desc)
                if not tag:
                    skipped+=1
                    continue

                free,limited=is_free(title,desc)
                if not free:
                    skipped+=1
                    continue

                try:
                    tg(build_message(tag,title,desc,source,limited),link)
                    published+=1
                    time.sleep(2)
                except Exception as e:
                    errors.append(source+": Telegram "+str(e))

        except Exception as e:
            errors.append(source+": "+str(e))

    save(seen)
    return {
        "ok":True,
        "published":published,
        "skipped":skipped,
        "errors":errors
    }

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/run"):
            if SECRET and self.path != "/run?key="+SECRET:
                self.send_response(403)
                self.end_headers()
                return
            body=json.dumps(run(),ensure_ascii=False).encode()
        else:
            body=b'{"ok":true}'

        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self,*a):
        pass

HTTPServer(
    ("0.0.0.0",int(os.getenv("PORT","10000"))),
    H
).serve_forever()
