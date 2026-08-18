import os,time,json,hashlib,re,html,urllib.request,urllib.parse
from xml.etree import ElementTree as ET

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
CHANNEL=os.getenv("TELEGRAM_CHANNEL","@gptnews999")
FEEDS=[("SoundShockAudio","https://soundshockaudio.com/feed/"),("Bedroom Producers Blog","https://bedroomproducersblog.com/feed/")]

POS={"vocal":8,"vocals":8,"vocal pack":10,"sample pack":7,"samples":5,"serum":6,"vital":6,"preset":7,"presets":7,"minimal":5,"minimal house":8,"deep house":5,"tech house":4,"house":3,"vst":5,"vst3":5,"plugin":5,"drum":5,"one-shot":5,"one shot":5,"midi":5,"loop":5,"loops":5,"project file":5,"royalty-free":5,"free download":7,"free":3}
NEG={"trial":-20,"demo":-15,"free trial":-30,"subscription":-25,"subscription required":-30,"paid":-12,"buy now":-15,"monthly subscription":-20,"annual subscription":-20,"per month":-15,"crack":-50,"pirated":-50,"torrent":-50}
BLOCKED=("free trial","subscription required","trial version","7-day trial","14-day trial","30-day trial","monthly subscription","annual subscription","requires subscription","paid subscription")

def clean(s):
    return re.sub(r"\\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",s or ""))).strip()

def score(t):
    t=t.lower()
    return sum(v for k,v in POS.items() if k in t)+sum(v for k,v in NEG.items() if k in t)

def translate(s):
    s=clean(s)
    if not s: return ""
    if len(re.findall(r"[Ð-Ð¯Ð°-ÑÐÑ]",s))>len(re.findall(r"[A-Za-z]",s)): return s
    try:
        q=urllib.parse.urlencode({"client":"gtx","sl":"auto","tl":"ru","dt":"t","q":s[:3500]})
        req=urllib.request.Request("https://translate.googleapis.com/translate_a/single?"+q,headers={"User-Agent":"Mozilla/5.0"})
        data=json.loads(urllib.request.urlopen(req,timeout=20).read().decode())
        return "".join(x[0] for x in data[0] if x and x[0]).strip() or s
    except Exception as e:
        print("TRANSLATE ERROR",e); return s

def load():
    try: return json.load(open("seen.json",encoding="utf-8"))
    except: return {}

def save(x): json.dump(x,open("seen.json","w",encoding="utf-8"),ensure_ascii=False,indent=2)

def tg(text,url):
    data=json.dumps({"chat_id":CHANNEL,"text":text+"\n\nð "+url,"parse_mode":"HTML","disable_web_page_preview":False}).encode()
    req=urllib.request.Request("https://api.telegram.org/bot"+TOKEN+"/sendMessage",data=data,headers={"Content-Type":"application/json"})
    urllib.request.urlopen(req,timeout=30).read()

def feed(url):
    raw=urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"GPTNewsRelay/2.0"}),timeout=30).read()
    root=ET.fromstring(raw); out=[]
    for x in root.findall(".//item"):
        a,b,c=clean(x.findtext("title")),clean(x.findtext("link")),clean(x.findtext("description"))
        if a and b: out.append((a,b,c))
    return out[-30:]

def tags(t):
    t=t.lower(); r=[]
    def add(x):
        if x not in r: r.append(x)
    if "vocal" in t: add("#VOCALS")
    if any(x in t for x in ("preset","serum","vital","synth preset")): add("#PRESETS")
    if any(x in t for x in ("sample pack","samples","drum kit","drum pack")): add("#SAMPLES")
    if any(x in t for x in ("vst","vst3","plugin")): add("#VST")
    if "midi" in t: add("#MIDI")
    if "loop" in t: add("#LOOPS")
    if any(x in t for x in ("project file","project files","flp","ableton project")): add("#PROJECTS")
    if any(x in t for x in ("news","release","released","announcement","update")): add("#NEWS")
    if "minimal" in t: add("#MINIMAL")
    if "deep house" in t: add("#DEEPHOUSE")
    if "tech house" in t: add("#TECHHOUSE")
    if "house" in t and not any(x in r for x in ("#DEEPHOUSE","#TECHHOUSE")): add("#HOUSE")
    if any(x in t for x in ("free","$0","0.00","free download","royalty-free")): add("#FREE")
    if not r: add("#OTHER")
    return " ".join(r)

def run():
    if not TOKEN: print("ERROR: TELEGRAM_BOT_TOKEN missing"); return
    seen=load(); published=0
    for source,url in FEEDS:
        try:
            for title,link,desc in feed(url):
                k=hashlib.sha256(link.encode()).hexdigest()
                if k in seen: continue
                text=title+" "+desc; low=text.lower()
                if any(x in low for x in BLOCKED) or score(text)<5:
                    seen[k]=int(time.time()); continue
                ru_title=translate(title); ru_desc=translate(desc[:1600])
                msg=f"{tags(text)}\n\n<b>{html.escape(ru_title)}</b>\n\n{html.escape(ru_desc[:800])}\n\nð <b>FREE</b>\nð {html.escape(source)}"
                try:
                    tg(msg,link); seen[k]=int(time.time()); published+=1; time.sleep(3)
                    print("PUBLISHED",title)
                except Exception as e: print("TELEGRAM ERROR",e)
        except Exception as e: print("FEED ERROR",source,e)
    if len(seen)>5000: seen=dict(list(seen.items())[-3500:])
    save(seen); print("DONE",published)

if __name__=="__main__": run()
