import os, re, json, time, html, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.parse import quote
from xml.etree import ElementTree as ET

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN','').strip()
CHANNEL = os.getenv('TELEGRAM_CHANNEL','').strip()
SEEN_FILE = 'seen.json'

GENRE = {'minimal house':8,'deep minimal':9,'rominimal':10,'romanian minimal':10,'minimal techno':7,'minimal tech':7,'deep house':6,'deep tech':7,'tech house':5}
PRODUCT = {'vocal':8,'vocals':8,'acapella':10,'acapellas':10,'serum preset':10,'serum presets':10,'vital preset':10,'vital presets':10,'sample pack':9,'sample packs':9,'drum kit':8,'drum kits':8,'one-shot':7,'one shot':7,'loops':6,'loop pack':8,'free vst':8,'free vst3':8,'vst3':5,'synth':5,'plugin':5,'plugins':5,'royalty-free':6,'royalty free':6,'midi':5}
BAD = ['trial','demo version','free trial','subscription','rent-to-own','rent to own','monthly plan','annual plan','paid only','commercial license required']
LISTICLES = ['best free','top 10','top 20','top 50','50 best','100 best','ultimate list','best platforms','roundup','list of']
CATS = {'vocals':['vocal','vocals','acapella','acapellas'],'presets':['serum preset','serum presets','vital preset','vital presets','preset'],'samples':['sample pack','sample packs','samples','one shot','one-shot','loops'],'drums':['drum kit','drum kits','drums','percussion'],'plugins':['free vst','free vst3','vst3','plugin','plugins','synth'],'midi':['midi']}
SOURCES = [
('Bedroom Producers Blog','https://bedroomproducersblog.com/feed/'),
('Rekkerd','https://rekkerd.org/feed/'),
('MusicRadar','https://www.musicradar.com/feeds'),
('Google: free samples','https://news.google.com/rss/search?q='+quote('"free sample pack" music production')),
('Google: vocals','https://news.google.com/rss/search?q='+quote('"free vocals" OR acapella music production')),
('Google: Serum presets','https://news.google.com/rss/search?q='+quote('"free Serum presets"')),
('Google: Vital presets','https://news.google.com/rss/search?q='+quote('"free Vital presets"')),
('Google: free VST','https://news.google.com/rss/search?q='+quote('"free VST" music production')),
('Google: drum kits','https://news.google.com/rss/search?q='+quote('"free drum kit" music production')),
('Google: minimal house','https://news.google.com/rss/search?q='+quote('"minimal house" free samples OR presets OR vocals')),
('Google: deep minimal','https://news.google.com/rss/search?q='+quote('"deep minimal" free samples OR presets')),
('Google: rominimal','https://news.google.com/rss/search?q='+quote('"rominimal" free samples OR presets'))]

def clean(s):
    s=html.unescape(s or ''); s=re.sub(r'<[^>]+>',' ',s); return re.sub(r'\s+',' ',s).strip()

def load_seen():
    try:
        with open(SEEN_FILE,encoding='utf-8') as f: return set(json.load(f))
    except Exception: return set()

def save_seen(s):
    with open(SEEN_FILE,'w',encoding='utf-8') as f: json.dump(list(s)[-5000:],f,ensure_ascii=False)

def fetch(url):
    req=Request(url,headers={'User-Agent':'GPT-News-Relay/5.0'})
    with urlopen(req,timeout=12) as r: return r.read()

def parse(source,url):
    try: root=ET.fromstring(fetch(url))
    except Exception as e: print(f'FEED ERROR {source}: {e}'); return []
    out=[]
    for n in root.iter():
        if not n.tag.lower().endswith(('item','entry')): continue
        title=desc=link=''
        for c in list(n):
            tag=c.tag.lower().split('}')[-1]; text=clean(c.text or '')
            if tag=='title': title=text
            elif tag in ('description','summary') and not desc: desc=text
            elif tag=='link': link=c.attrib.get('href','') or text
        if title and link: out.append({'source':source,'title':title,'description':desc,'link':link})
    return out[:100]

def score(x):
    t=(x['title']+' '+x['description']).lower(); s=0; g=[]; p=[]
    for k,v in GENRE.items():
        if k in t: s+=v; g.append(k)
    for k,v in PRODUCT.items():
        if k in t: s+=v; p.append(k)
    s += 12 if g and p else 0
    s -= 40*sum(k in t for k in BAD); s -= 18*sum(k in t for k in LISTICLES)
    return s,g,p

def fp(x): return hashlib.sha256((x['title']+'|'+x['link']).encode()).hexdigest()

def cats(x):
    t=(x['title']+' '+x['description']).lower(); return [c for c,terms in CATS.items() if any(z in t for z in terms)][:3] or ['resources']

def post_text(x,s,g,p):
    d=clean(x['description']); d=d[:277].rsplit(' ',1)[0]+'...' if len(d)>280 else d
    tags=' '.join('#'+c for c in cats(x)); genre='🎯 <b>ПОД ТВОЙ ЖАНР</b>\n' if g else ''
    return f'🎛 <b>{html.escape(x["title"])}</b>\n\n🏷 {tags}\n{genre}🔎 {html.escape(", ".join(dict.fromkeys(p[:5])))}\n\n{html.escape(d)}\n\n📡 <i>{html.escape(x["source"])}</i>\n🔗 <a href="{html.escape(x["link"],quote=True)}">Открыть материал</a>'

def send(text):
    data=json.dumps({'chat_id':CHANNEL,'text':text,'parse_mode':'HTML','disable_web_page_preview':False}).encode()
    req=Request(f'https://api.telegram.org/bot{TOKEN}/sendMessage',data=data,headers={'Content-Type':'application/json'},method='POST')
    with urlopen(req,timeout=15) as r:
        if not json.loads(r.read()).get('ok'): raise RuntimeError('Telegram API error')

def main():
    if not TOKEN or not CHANNEL: raise SystemExit('ERROR: Telegram secrets missing')
    print('START FAST MULTI-SOURCE SCAN v5 FINAL')
    seen=load_seen(); all_items=[]
    with ThreadPoolExecutor(max_workers=12) as pool:
        fs={pool.submit(parse,s,u):s for s,u in SOURCES}
        for f in as_completed(fs):
            src=fs[f]
            try:
                a=f.result(); print(f'FOUND {len(a)} from {src}'); all_items+=a
            except Exception as e: print(f'FEED ERROR {src}: {e}')
    unique={fp(x):x for x in all_items}; candidates=[]
    for x in unique.values():
        if fp(x) in seen: continue
        sc,g,p=score(x)
        if sc>=10: candidates.append((sc,x,g,p))
    candidates.sort(reverse=True,key=lambda z:z[0]); posted=errors=0
    for sc,x,g,p in candidates[:20]:
        try: send(post_text(x,sc,g,p)); seen.add(fp(x)); posted+=1; print(f'POSTED [score={sc} genre={len(g)} product={len(p)}] {x["source"]}: {x["title"]}'); time.sleep(.15)
        except Exception as e: errors+=1; print(f'POST ERROR {x["title"]}: {e}')
    save_seen(seen); print(f'DONE published={posted} skipped={len(seen)} candidates={len(candidates)} errors={errors}')

if __name__=='__main__': main()
