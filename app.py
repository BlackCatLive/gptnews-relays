import os,time,json,hashlib,re,html
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.request import Request,urlopen
from xml.etree import ElementTree as ET

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
CHANNEL=os.getenv("TELEGRAM_CHANNEL","@gptnews999")
SECRET=os.getenv("RELAY_SECRET","")
FEEDS=[("SoundShockAudio","https://soundshockaudio.com/feed/"),("Bedroom Producers Blog","https://bedroomproducersblog.com/feed/")]
POS={"vocal":8,"vocals":8,"vocal pack":10,"sample pack":7,"samples":5,"serum":6,"vital":6,"preset":7,"presets":7,"minimal":5,"house":3,"vst":5,"plugin":5,"drum":5,"one-shot":5,"royalty-free":5,"free download":6,"free":3}
NEG={"trial":-12,"demo":-10,"free trial":-15,"subscription":-12,"paid":-8,"buy now":-8,"torrent":-20}

def clean(s): return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",s or ""))).strip()
def score(t):
    t=t.lower()
    s=sum(v for k,v in POS.items() if k in t)+sum(v for k,v in NEG.items() if k in t)
    if any(x in t for x in ("free trial","subscription required","7-day trial","14-day trial","30-day trial")): s-=30
    return s
def load():
    try: return json.load(open("seen.json",encoding="utf-8"))
    except: return {}
def save(x): json.dump(x,open("seen.json","w",encoding="utf-8"),ensure_ascii=False)
def tg(text,url):
    import urllib.request
    data=json.dumps({"chat_id":CHANNEL,"text":text+"\n\n🔗 "+url,"parse_mode":"HTML"}).encode()
    r=urllib.request.Request("https://api.telegram.org/bot"+TOKEN+"/sendMessage",data=data,headers={"Content-Type":"application/json"})
    urllib.request.urlopen(r,timeout=20).read()
def feed(url):
    raw=urlopen(Request(url,headers={"User-Agent":"GPTNewsRelay/1.0"}),timeout=20).read()
    root=ET.fromstring(raw); out=[]
    for x in root.findall(".//item"):
        a=clean(x.findtext("title")); b=clean(x.findtext("link")); c=clean(x.findtext("description"))
        if a and b: out.append((a,b,c))
    return out[-20:]
def run():
    if not TOKEN: return {"ok":False,"error":"missing token"}
    seen=load(); n=0
    for source,url in FEEDS:
        try:
            for title,link,desc in feed(url):
                k=hashlib.sha256(link.encode()).hexdigest()
                if k in seen: continue
                text=title+" "+desc; seen[k]=int(time.time())
                if score(text)<5: continue
                low=text.lower()
                tag="🎤 VOCALS" if "vocal" in low else ("🎹 PRESETS" if ("preset" in low or "serum" in low or "vital" in low) else ("🥁 SAMPLES" if ("sample" in low or "drum" in low) else ("🔌 PLUGIN" if ("vst" in low or "plugin" in low) else "🎛️ MUSIC PRODUCTION")))
                tg(f"{tag}\n\n<b>{html.escape(title)}</b>\n\n{html.escape(desc[:500])}\n\n🆓 <b>FREE</b>\n📌 {html.escape(source)}",link); n+=1; time.sleep(2)
        except Exception as e: print(source,e,flush=True)
    save(seen); return {"ok":True,"published":n}
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/run"):
            if SECRET and self.path!="/run?key="+SECRET: self.send_response(403); self.end_headers(); return
            body=json.dumps(run()).encode()
        else: body=b'{"ok":true}'
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self,*a): pass
HTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),H).serve_forever()

