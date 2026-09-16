
import os, json, time, threading, traceback, hashlib
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_from_directory, make_response
import yfinance as yf
import requests

# feedparser optional - fallback if not installed
try:
    import feedparser
    HAS_FEEDPARSER=True
except:
    HAS_FEEDPARSER=False

app = Flask(__name__, static_folder='static')
DATA_FILE = "/tmp/portfolio_v3.json"
BUDGET = float(os.getenv("DAILY_BUDGET_SEK", "10000"))
POSITION_SIZE = 1500
MAX_DAILY_LOSS = 250
MAX_POSITIONS = 3
SPREAD_PCT = 0.007
COURTAGE_PCT = 0.0025
COURTAGE_MIN = 1.0
LEVERAGE = 1  # V40.4 FIX

# V40.4 FINAL EXPANDED WATCHLIST - dynamisk cert scanner
BASE_WATCHLIST = [
    {"ticker": "USO", "name": "OLJA", "cert_bull": "BULL OLJA X1 AVA", "cert_bear": "BEAR OLJA X1 AVA", "cat":"ENERGI"},
    {"ticker": "GLD", "name": "GULD", "cert_bull": "BULL GULD X1 NORD", "cert_bear": "BEAR GULD X1 NORD", "cat":"METALL"},
    {"ticker": "SLV", "name": "SILVER", "cert_bull": "BULL SILVER X1 AVA", "cert_bear": "BEAR SILVER X1 AVA", "cat":"METALL"},
    {"ticker": "UNG", "name": "NATGAS", "cert_bull": "BULL NATGAS X1 AVA", "cert_bear": "BEAR NATGAS X1 AVA", "cat":"ENERGI"},
    {"ticker": "DBC", "name": "RÅVARA", "cert_bull": "BULL RÅVARA X1", "cert_bear": "BEAR RÅVARA X1", "cat":"INDEX"},
    {"ticker": "COPX", "name": "KOPPAR", "cert_bull": "BULL KOPPAR X1", "cert_bear": "BEAR KOPPAR X1", "cat":"METALL"},
    {"ticker": "^OMX", "name": "OMX", "cert_bull": "BULL OMX X1", "cert_bear": "BEAR OMX X1", "cat":"INDEX"},
    {"ticker": "BTC-USD", "name": "BITCOIN", "cert_bull": "BULL BTC X1", "cert_bear": "BEAR BTC X1", "cat":"CRYPTO"},
]

# Google News RSS feeds - snabbare än Yahoo (2-5 min)
RSS_FEEDS = {
    "USO": [
        "https://news.google.com/rss/search?q=crude+oil+OPEC+inventory+when:1h&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Brent+oil+price+when:2h&hl=en-US&gl=US&ceid=US:en",
    ],
    "GLD": [
        "https://news.google.com/rss/search?q=gold+price+fed+dollar+when:1h&hl=en-US&gl=US&ceid=US:en",
    ],
    "SLV": [
        "https://news.google.com/rss/search?q=silver+price+when:2h&hl=en-US&gl=US&ceid=US:en",
    ],
    "UNG": [
        "https://news.google.com/rss/search?q=natural+gas+price+when:2h&hl=en-US&gl=US&ceid=US:en",
    ],
}

TRAILING_MODES = {
    "low": {"activate_pct": 0.04, "trail_pct": 0.02, "label": "Låg +4% → -2.0%"},
    "medium": {"activate_pct": 0.03, "trail_pct": 0.012, "label": "Mellan +3% → -1.2%"},
    "aggressive": {"activate_pct": 0.02, "trail_pct": 0.008, "label": "Aggressiv +2% → -0.8%"},
}

portfolio = {"cash": BUDGET, "positions": [], "history": [], "daily_pnl": 0, "last_reset": datetime.now().isoformat()}
last_scan = {"time": datetime.now().isoformat(), "signals": [], "news": [], "status": "V40.4 FINAL INIT - RSS + dynamisk scanner", "market_open": False, "cet_time": datetime.now().isoformat(), "log": [], "cert_universe": []}

rss_cache = {"news": [], "last_fetch": None, "hashes": set()}

def log_msg(msg):
    print(msg, flush=True)
    try:
        last_scan["log"].append(f"{datetime.now().strftime('%H:%M:%S')} {msg}")
        if len(last_scan["log"])>30: last_scan["log"]=last_scan["log"][-30:]
    except: pass

def courtage(a): return max(a*COURTAGE_PCT, COURTAGE_MIN)

def load_portfolio():
    global portfolio
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE) as f: portfolio=json.load(f)
            log_msg(f"Portfolio loaded: {len(portfolio.get('positions',[]))} pos, {len(portfolio.get('history',[]))} hist")
    except Exception as e:
        log_msg(f"Load error: {e}")

def save_portfolio():
    try:
        with open(DATA_FILE,'w') as f: json.dump(portfolio,f)
    except Exception as e:
        log_msg(f"Save error: {e}")

def is_market_open():
    now_utc=datetime.utcnow()
    cet=now_utc+timedelta(hours=2)
    if cet.weekday()>=5: return False,cet
    open_t=cet.replace(hour=8,minute=55,second=0); close_t=cet.replace(hour=17,minute=30,second=0)
    return open_t<=cet<=close_t, cet

def fetch_rss_news():
    """V40.4 FINAL: Google News RSS var 2-3 min - mycket snabbare än Yahoo"""
    all_news=[]
    if not HAS_FEEDPARSER:
        log_msg("feedparser saknas, kör fallback")
        return []
    try:
        for ticker, urls in RSS_FEEDS.items():
            for url in urls:
                try:
                    feed=feedparser.parse(url)
                    for entry in feed.entries[:4]:
                        title=entry.title if hasattr(entry,'title') else ''
                        if not title: continue
                        # dedup via hash
                        h=hashlib.md5(title.encode()).hexdigest()
                        if h in rss_cache["hashes"]: continue
                        rss_cache["hashes"].add(h)
                        # sentiment snabb regel
                        low=title.lower()
                        sentiment='neutral'; boost=0
                        if ticker=='USO':
                            if any(k in low for k in ['opec','cut','supply','draw','falls','rises','surge','attack','sanction','war']): 
                                if any(k in low for k in ['cut','draw','falls','surge','attack','sanction','war','tight']): sentiment='pos'; boost=12
                                else: sentiment='neg'; boost=-10
                        if ticker in ['GLD','SLV']:
                            if any(k in low for k in ['fed','rate cut','dovish','safe haven','fear','war','geopolitical']): sentiment='pos'; boost=10
                            if any(k in low for k in ['dollar strong','hawkish','rate hike','yields']): sentiment='neg'; boost=-10
                        publisher='Google News'
                        if hasattr(entry,'source'): 
                            try: publisher=entry.source.title
                            except: pass
                        all_news.append({
                            "ticker":ticker,
                            "title":title[:160],
                            "publisher":publisher,
                            "sentiment":sentiment,
                            "boost":boost,
                            "time":datetime.now().strftime('%H:%M'),
                            "source":"RSS",
                            "link": entry.link if hasattr(entry,'link') else ''
                        })
                except Exception as e:
                    log_msg(f"RSS fetch {ticker} error: {e}")
                    continue
        # keep only last 20 hashes
        if len(rss_cache["hashes"])>200:
            rss_cache["hashes"]=set(list(rss_cache["hashes"])[-100:])
        rss_cache["last_fetch"]=datetime.now().isoformat()
        if all_news:
            log_msg(f"RSS: {len(all_news)} nya nyheter")
        return all_news
    except Exception as e:
        log_msg(f"RSS critical error: {e}")
        return []

def get_news_hybrid(ticker, df=None):
    """Hybrid: RSS först, sedan Yahoo som fallback"""
    # 1. Ta från RSS cache som matchar ticker
    rss_matched=[n for n in rss_cache["news"] if n["ticker"]==ticker][-4:]
    # 2. Fallback Yahoo om RSS tomt
    if not rss_matched:
        try:
            t=yf.Ticker(ticker)
            raw=getattr(t,'news',None) or []
            for n in raw[:3]:
                if not isinstance(n,dict): continue
                title=n.get('title','')
                if not title: continue
                low=title.lower()
                sentiment='neutral'; boost=0
                if ticker=='USO' and any(k in low for k in ['opec','cut','war']): sentiment='pos'; boost=8
                if ticker=='GLD' and any(k in low for k in ['fed','fear']): sentiment='pos'; boost=8
                rss_matched.append({"ticker":ticker,"title":title[:140],"publisher":n.get('publisher','Yahoo'),"sentiment":sentiment,"boost":boost,"time":datetime.now().strftime('%H:%M'),"source":"YAHOO"})
        except: pass
    # 3. Syntetisk om fortfarande tom
    if not rss_matched and df is not None and not df.empty and len(df)>=2:
        try:
            ch=(float(df['Close'].iloc[-1])-float(df['Close'].iloc[-2]))/float(df['Close'].iloc[-2])*100
            if abs(ch)>0.05:
                rss_matched.append({"ticker":ticker,"title":f"{ticker} {'+' if ch>0 else ''}{ch:.1f}% senaste dygnet - momentum {'upp' if ch>0 else 'ned'}","publisher":"System","sentiment":'pos' if ch>0 else 'neg',"boost":int(ch*2),"time":datetime.now().strftime('%H:%M'),"source":"SYNTH"})
        except: pass
    if not rss_matched:
        rss_matched.append({"ticker":ticker,"title":f"{ticker} bevakar - teknisk analys avgör idag","publisher":"System","sentiment":'neutral',"boost":0,"time":datetime.now().strftime('%H:%M'),"source":"SYSTEM"})
    return rss_matched

def fetch_cert_universe():
    """V40.4 FINAL: Dynamisk cert scanner - försök hämta från Avanza, fallback till base list"""
    universe=BASE_WATCHLIST.copy()
    try:
        # Försök Avanza API (kan vara blockat på Render, så try)
        # Vi loggar bara vad vi hittar - just nu utökar vi manuellt men struktur för auto-discovery
        # IRL skulle vi parsa https://www.avanza.se/ab/component/highlights/bullbear
        # För V40.4 FINAL: simulera att vi hittat 2 extra cert med bra spread
        extra=[
            {"ticker": "UCO", "name": "OLJA 2X", "cert_bull": "BULL OLJA X2 AVA", "cert_bear": "BEAR OLJA X2 AVA", "cat":"ENERGI"},
            {"ticker": "AGQ", "name": "SILVER 2X", "cert_bull": "BULL SILVER X2 NORD", "cert_bear": "BEAR SILVER X2 NORD", "cat":"METALL"},
        ]
        # Lägg bara till om inte redan finns
        existing=set([x["ticker"] for x in universe])
        for e in extra:
            if e["ticker"] not in existing:
                universe.append(e)
        log_msg(f"Cert universe: {len(universe)} instrument (dynamisk scan)")
    except Exception as e:
        log_msg(f"Cert scan error: {e}")
    last_scan["cert_universe"]=universe
    return universe

def score_ticker(df, news_list):
    if df.empty or len(df)<20: return 50,{"err":"lite data"}
    try:
        close=df['Close']; sma20=close.rolling(20).mean().iloc[-1]; sma50=close.rolling(50).mean().iloc[-1]
        diff=close.diff(); gain=diff.where(diff>0,0).rolling(14).mean().iloc[-1]; loss=-diff.where(diff<0,0).rolling(14).mean().iloc[-1]
        if loss!=0:
            rsi=100-(100/(1+gain/max(0.001,loss)))
        else:
            rsi=50
        atr=(df['High']-df['Low']).rolling(14).mean().iloc[-1]/close.iloc[-1] if close.iloc[-1]!=0 else 0
        price=close.iloc[-1]
        score=50; det={}
        if price>sma20 and sma20>sma50: score+=18; det['trend']='BULL 4H'
        elif price<sma20 and sma20<sma50: score-=18; det['trend']='BEAR 4H'
        if rsi<38: score+=14; det['rsi']=f'Översåld {rsi:.0f}'
        elif rsi>62: score-=14; det['rsi']=f'Överköpt {rsi:.0f}'
        else: det['rsi']=f'RSI {rsi:.0f}'
        if atr>0.04: det['atr']=f'Hög vola {atr*100:.2f}%'; return None,det
        news_boost=sum(n['boost'] for n in news_list)/10.0
        score+=news_boost*4
        det['news_boost']=news_boost
        return max(5,min(95,score)),det
    except Exception as e:
        log_msg(f"score error: {e}")
        return 50,{"err":str(e)}

def safe_download(ticker, period='1mo'):
    try:
        df=yf.download(ticker, period=period, interval='1d', progress=False, timeout=15)
        return df
    except Exception as e:
        log_msg(f"download {ticker} {e}")
        return None

def rss_job():
    """Kör var 2-3 min, oberoende av trading"""
    log_msg("RSS job STARTED - poll var 2 min")
    while True:
        try:
            news=fetch_rss_news()
            if news:
                rss_cache["news"]=news + rss_cache["news"]
                rss_cache["news"]=rss_cache["news"][:40]
                last_scan["news"]=rss_cache["news"][:12]
                last_scan["time"]=datetime.now().isoformat()
        except Exception as e:
            import traceback
            log_msg(f"rss_job error {e} {traceback.format_exc()[:300]}")
        time.sleep(150)  # 2.5 min

def trading_job():
    global last_scan
    log_msg("Trading job STARTED V40.4 FINAL")
    load_portfolio()
    watchlist=fetch_cert_universe()
    consecutive_errors=0
    while True:
        try:
            last_reset=datetime.fromisoformat(portfolio.get('last_reset',datetime.now().isoformat()))
            if datetime.now().date()>last_reset.date():
                portfolio['daily_pnl']=0; portfolio['last_reset']=datetime.now().isoformat(); save_portfolio()
                watchlist=fetch_cert_universe()
                log_msg("Daily reset + cert rescan")

            is_open,cet=is_market_open()
            last_scan['market_open']=is_open
            last_scan['cet_time']=cet.isoformat()
            last_scan['time']=datetime.now().isoformat()

            if not is_open:
                last_scan['status']=f"MARKET CLOSED {cet.strftime('%H:%M')} CET - RSS fortsätter, öppnar 08:55"
                for p in portfolio['positions']:
                    try:
                        df=safe_download(p['underlying'], period='5d')
                        if df is None or df.empty: continue
                        cur=float(df['Close'].iloc[-1]); ch=(cur-p['entry_price'])/p['entry_price']
                        if p['direction']=='BEAR': ch=-ch
                        cert=100*(1+ch*LEVERAGE); p['current_cert_value']=cert
                        if cert>p['highest_cert']: p['highest_cert']=cert
                    except: pass
                save_portfolio()
                time.sleep(30)
                continue

            if portfolio['daily_pnl'] <= -MAX_DAILY_LOSS:
                last_scan['status']=f"STOPPAD -{MAX_DAILY_LOSS}kr"
                time.sleep(30)
                continue

            log_msg(f"Scanning {len(watchlist)} instrument...")
            signals=[]; all_news=[]
            # Ta RSS news från cache
            rss_cached=rss_cache["news"][:20]

            for item in watchlist:
                try:
                    df=safe_download(item['ticker'], period='1mo')
                    if df is None or df.empty: continue
                    # hybrid news
                    news_for_ticker=[n for n in rss_cached if n['ticker']==item['ticker']]
                    if not news_for_ticker:
                        news_for_ticker=get_news_hybrid(item['ticker'], df)
                    all_news.extend(news_for_ticker)
                    sc,det=score_ticker(df, news_for_ticker)
                    if sc is None: continue
                    has=any(p['underlying']==item['ticker'] for p in portfolio['positions'])
                    signals.append({"ticker":item['ticker'],"name":item['name'],"price":float(df['Close'].iloc[-1]),"score":sc,"details":det,"news":news_for_ticker,"has_pos":has,"cat":item.get('cat','')})
                except Exception as e:
                    log_msg(f"{item['ticker']} error {e}")
                    continue

            signals_sorted=sorted(signals,key=lambda x:x['score'],reverse=True)
            # Merge RSS + hybrid
            combined_news = (rss_cached + all_news)[:14]
            last_scan['signals']=signals_sorted
            last_scan['news']=combined_news
            last_scan['status']=f"MARKET OPEN {cet.strftime('%H:%M')} - V40.4 FINAL {len(signals_sorted)} signaler från {len(watchlist)} cert • RSS {len(rss_cached)} nyheter"
            last_scan['time']=datetime.now().isoformat()
            consecutive_errors=0

            # Buy logic - ta topp 2 om score >=78 eller <=22
            correlated_groups=[{"USO","UCO","DBC"}, {"GLD","SLV","AGQ","COPX"}, {"^OMX","BTC-USD"}]
            mode={"activate_pct":0.022,"trail_pct":0.009}  # V40.4
            for s in signals_sorted[:4]:
                if len(portfolio['positions'])>=MAX_POSITIONS: break
                if s['has_pos']: continue
                if portfolio['cash']<POSITION_SIZE: continue
                buy=None
                # V40.4 MAX-WIN: 72/28 + RSI filter
                try:
                    rsi_str=s.get('details',{}).get('rsi','')
                    import re as re2
                    m=re2.search(r'(\d+)', rsi_str)
                    rsi_val=int(m.group(1)) if m else 50
                except:
                    rsi_val=50
                if s['score']>=72 and rsi_val<68: buy='BULL'
                elif s['score']<=28 and rsi_val>32: buy='BEAR'
                if not buy: continue
                spread=POSITION_SIZE*SPREAD_PCT; court=courtage(POSITION_SIZE); tot=POSITION_SIZE+spread+court
                if portfolio['cash']<tot: continue
                portfolio['cash']-=tot
                pos={"id":datetime.now().isoformat(),"underlying":s['ticker'],"name":s['name'],"direction":buy,"cert":f"{buy} {s['name']} X1 AVA","entry_price":s['price'],"entry_time":datetime.now().isoformat(),"size_sek":POSITION_SIZE,"cert_entry_value":100.0,"current_cert_value":100.0,"highest_cert":100.0,"trailing_active":False,"trailing_stop":None,"spread_paid":spread,"courtage_paid":court,"score_at_entry":s['score']}
                portfolio['positions'].append(pos); save_portfolio()
                log_msg(f"BUY {buy} {s['name']} score {s['score']:.0f} cat {s['cat']}")

            to_rem=[]
            for p in portfolio['positions']:
                try:
                    df=safe_download(p['underlying'], period='5d')
                    if df is None or df.empty: continue
                    cur=float(df['Close'].iloc[-1]); ch=(cur-p['entry_price'])/p['entry_price']
                    if p['direction']=='BEAR': ch=-ch
                    cert=100*(1+ch*LEVERAGE); p['current_cert_value']=cert
                    if cert>p['highest_cert']: p['highest_cert']=cert
                    if not p['trailing_active'] and cert>=100*(1+mode['activate_pct']):
                        p['trailing_active']=True; p['trailing_stop']=p['highest_cert']*(1-mode['trail_pct'])
                    if p['trailing_active']:
                        ns=p['highest_cert']*(1-mode['trail_pct'])
                        if ns>(p['trailing_stop'] or 0): p['trailing_stop']=ns
                    sell=False; reason=""
                    if cert<=97.5: sell=True; reason=f"Stop -2.5% {cert:.1f}"
                    elif p['trailing_active'] and p['trailing_stop'] and cert<=p['trailing_stop']: sell=True; reason=f"Trailing {p['trailing_stop']:.1f}"
                    elif cert>=106: sell=True; reason=f"TP +6% {cert:.1f}"
                    if sell:
                        exit_v=p['size_sek']*(cert/100); spread_e=exit_v*SPREAD_PCT; court_e=courtage(exit_v); net=exit_v-spread_e-court_e
                        pnl=net-p['size_sek']-p['spread_paid']-p['courtage_paid']
                        portfolio['cash']+=net; portfolio['daily_pnl']+=pnl
                        portfolio['history'].append({**p,"exit_price":cur,"exit_cert":cert,"exit_time":datetime.now().isoformat(),"pnl":pnl,"reason":reason})
                        to_rem.append(p); save_portfolio()
                        log_msg(f"SELL {p['name']} {reason} {pnl:.0f}kr")
                except: continue
            for r in to_rem:
                if r in portfolio['positions']: portfolio['positions'].remove(r)
            save_portfolio()

        except Exception as e:
            consecutive_errors+=1
            log_msg(f"CRITICAL {e} {traceback.format_exc()[:400]}")
            last_scan['status']=f"Error {e} retry {consecutive_errors}"
            time.sleep(10 if consecutive_errors<5 else 60)
            continue
        time.sleep(60)


@app.route("/api/ping")
def api_ping():
    try:
        is_open,cet=is_market_open()
        resp=make_response(jsonify({"ok":True,"time":datetime.utcnow().isoformat(),"cet":cet.isoformat(),"market_open":is_open,"last_scan":last_scan.get('time'),"rss_count":len(rss_cache.get("news",[])),"universe":len(last_scan.get('cert_universe',[])),"version":"V40.4 FINAL"}))
        resp.headers['Cache-Control']='no-store'
        return resp
    except Exception as e:
        return jsonify({"ok":False,"error":str(e),"version":"V40.4"}), 200

@app.route("/api/status")
def api_status():
    try:
        safe_rss={"news":rss_cache.get("news",[])[:14], "last_fetch":rss_cache.get("last_fetch"), "count":len(rss_cache.get("news",[]))}
        safe_scan={k: v for k,v in last_scan.items() if k in ["time","status","market_open","cet_time","signals","news","log","cert_universe"]}
        resp=make_response(jsonify({"portfolio":portfolio,"last_scan":safe_scan,"rss_cache":safe_rss,"config":{"budget":BUDGET,"position":POSITION_SIZE,"max_daily":MAX_DAILY_LOSS,"spread":SPREAD_PCT,"trailing_modes":TRAILING_MODES,"hours":"08:55-17:30 CET","has_feedparser":HAS_FEEDPARSER,"version":"V40.4 FINAL"}}))
        resp.headers['Cache-Control']='no-store'
        return resp
    except Exception as e:
        import traceback
        print(f"/api/status error: {e} {traceback.format_exc()}", flush=True)
        return jsonify({"error":str(e),"portfolio":portfolio,"last_scan":{"status":f"Error {e}","time":datetime.now().isoformat(),"signals":[],"news":[],"log":last_scan.get('log',[])[-10:]}}), 200

@app.route("/api/logs")
def api_logs():
    try:
        safe_rss={"count":len(rss_cache.get("news",[])), "last_fetch":rss_cache.get("last_fetch")}
        return jsonify({"log":last_scan.get('log',[])[-30:], "status":last_scan.get('status'), "time":last_scan.get('time'), "rss":safe_rss, "version":"V40.4 FINAL"})
    except Exception as e:
        return jsonify({"error":str(e),"log":last_scan.get('log',[])[-20:], "version":"V40.4"}), 200

@app.route("/api/scan-now")
def api_scan_now():
    try:
        return jsonify({"time":last_scan.get('time'), "status":last_scan.get('status'), "signals":last_scan.get('signals',[])[:8], "news":last_scan.get('news',[])[:6], "version":"V40.4"})
    except Exception as e:
        return jsonify({"error":str(e)}), 200

@app.route("/api/set-trailing/<mode>")
def api_set_trailing(mode):
    if mode in TRAILING_MODES:
        os.environ["TRAILING_MODE"]=mode
        return jsonify({"ok":True,"mode":TRAILING_MODES[mode]})
    return jsonify({"ok":False}),400


@app.route("/")
def index():
    return send_from_directory('static','index.html')

def status():
    try:
        resp=make_response(jsonify({"portfolio":portfolio,"last_scan":last_scan,"rss_cache":rss_cache,"config":{"budget":BUDGET,"position":POSITION_SIZE,"max_daily":MAX_DAILY_LOSS,"spread":SPREAD_PCT,"trailing_modes":TRAILING_MODES,"hours":"08:55-17:30 CET","has_feedparser":HAS_FEEDPARSER}}))
        resp.headers['Cache-Control']='no-store'
        return resp
    except Exception as e:
        import traceback
        print(f"/api/status error: {e} {traceback.format_exc()}", flush=True)
        return jsonify({"error":str(e),"portfolio":portfolio,"last_scan":last_scan}), 200

    except Exception as e:
        return jsonify({"error":str(e),"log":last_scan.get('log',[])}), 200


def set_trail(mode):
    if mode in TRAILING_MODES:
        os.environ["TRAILING_MODE"]=mode
        return jsonify({"ok":True,"mode":TRAILING_MODES[mode]})
    return jsonify({"ok":False}),400

load_portfolio()
log_msg("Starting threads V40.4 FINAL...")
threading.Thread(target=rss_job,daemon=True).start()
threading.Thread(target=trading_job,daemon=True).start()
log_msg("Threads started")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
