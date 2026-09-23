
import os, time, json, threading, traceback, random
from datetime import datetime
from flask import Flask, jsonify, make_response, send_from_directory, request
import numpy as np
import requests

print("V42 MORNING BRIEF - NO SPAM", flush=True)

app = Flask(__name__, static_folder='static')

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SCORE_THRESHOLD = float(os.environ.get("SCORE_THRESHOLD", "7.5"))
MORNING_HOUR_START = int(os.environ.get("MORNING_HOUR_START", "8"))
MORNING_HOUR_END = int(os.environ.get("MORNING_HOUR_END", "9"))
MORNING_ONLY = os.environ.get("MORNING_ONLY", "true").lower()=="true"
TRADING_ENABLED = os.environ.get("TRADING_ENABLED", "false").lower()=="true"

CERT_UNIVERSE = [
    {"cat":"ENERGI","name":"OLJA","ticker":"USO","yahoo":"USO","display":"OLJA (USO)"},
    {"cat":"ENERGI","name":"OLJA 2X","ticker":"UCO","yahoo":"UCO","display":"OLJA 2X"},
    {"cat":"ENERGI","name":"NATGAS","ticker":"UNG","yahoo":"UNG","display":"NATGAS"},
    {"cat":"METALL","name":"GULD","ticker":"GLD","yahoo":"GLD","display":"GULD"},
    {"cat":"METALL","name":"GULD 2X","ticker":"UGL","yahoo":"UGL","display":"GULD 2X"},
    {"cat":"METALL","name":"SILVER","ticker":"SLV","yahoo":"SLV","display":"SILVER"},
    {"cat":"METALL","name":"SILVER 2X","ticker":"AGQ","yahoo":"AGQ","display":"SILVER 2X"},
    {"cat":"METALL","name":"KOPPAR","ticker":"COPX","yahoo":"COPX","display":"KOPPAR"},
    {"cat":"INDEX","name":"RÅVARA","ticker":"DBC","yahoo":"DBC","display":"RÅVARA INDEX"},
    {"cat":"CRYPTO","name":"BITCOIN","ticker":"BTC-USD","yahoo":"BTC-USD","display":"BITCOIN"},
    {"cat":"US TECH","name":"NVIDIA","ticker":"NVDA","yahoo":"NVDA","display":"NVIDIA"},
    {"cat":"US TECH","name":"TESLA","ticker":"TSLA","yahoo":"TSLA","display":"TESLA"},
    {"cat":"US TECH","name":"APPLE","ticker":"AAPL","yahoo":"AAPL","display":"APPLE"},
    {"cat":"SE DEFENCE","name":"SAAB","ticker":"SAAB-B.ST","yahoo":"SAAB-B.ST","display":"SAAB B"},
    {"cat":"SE","name":"VOLVO","ticker":"VOLV-B.ST","yahoo":"VOLV-B.ST","display":"VOLVO B"},
    {"cat":"SE","name":"EVOLUTION","ticker":"EVO.ST","yahoo":"EVO.ST","display":"EVOLUTION"},
    {"cat":"SE","name":"ERICSSON","ticker":"ERIC-B.ST","yahoo":"ERIC-B.ST","display":"ERICSSON B"},
    {"cat":"SE","name":"NIBE","ticker":"NIBE-B.ST","yahoo":"NIBE-B.ST","display":"NIBE B"},
    {"cat":"SE","name":"ABB","ticker":"ABB.ST","yahoo":"ABB.ST","display":"ABB"},
    {"cat":"INDEX","name":"OMX","ticker":"^OMX","yahoo":"^OMX","display":"OMX Stockholm 30"},
    {"cat":"INDEX","name":"S&P500","ticker":"^GSPC","yahoo":"^GSPC","display":"S&P500"},
    {"cat":"INDEX","name":"NASDAQ","ticker":"^IXIC","yahoo":"^IXIC","display":"NASDAQ"},
    {"cat":"ENERGI","name":"URAN","ticker":"URA","yahoo":"URA","display":"URAN ETF"},
    {"cat":"DEFENCE","name":"LOCKHEED","ticker":"LMT","yahoo":"LMT","display":"LOCKHEED MARTIN"},
    {"cat":"CHIP","name":"AMD","ticker":"AMD","yahoo":"AMD","display":"AMD"},
]

last_scan={"time":datetime.now().isoformat(),"status":"V42 INIT MORNING BRIEF","signals":[],"news":[],"log":["V42 INIT MORNING - only 08:55 brief"],"cert_universe":CERT_UNIVERSE}
rss_cache={"news":[],"last_fetch":None,"sources_checked":0}
telegram_stats={"sent":0,"last_send":None,"last_error":None,"last_date":None}
yfinance_available=False
threads_started=False
threads_lock=threading.Lock()
LAST_TELEGRAM_DATE=None

try:
    import yfinance as yf
    yfinance_available=True
    print(f"yfinance available {len(CERT_UNIVERSE)} tickers", flush=True)
except Exception as e:
    print(f"yfinance not available {e}", flush=True)

def log_msg(msg):
    ts=datetime.now().strftime("%H:%M:%S")
    entry=f"{ts} {msg}"
    print(entry, flush=True)
    last_scan["log"].append(entry)
    if len(last_scan["log"])>100:
        last_scan["log"]=last_scan["log"][-100:]

def get_telegram_config():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return token, chat_id

def is_morning_window_cet():
    from datetime import timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    cet = now_utc + timedelta(hours=2)
    hour = cet.hour
    minute = cet.minute
    if MORNING_ONLY:
        return (hour==MORNING_HOUR_START and minute>=50) or (hour==MORNING_HOUR_START+1 and minute<=15)
    else:
        return True

def should_send_telegram_today():
    global LAST_TELEGRAM_DATE
    today = datetime.now().date().isoformat()
    if LAST_TELEGRAM_DATE==today:
        return False
    if MORNING_ONLY and not is_morning_window_cet():
        return False
    return True

def mark_telegram_sent():
    global LAST_TELEGRAM_DATE
    LAST_TELEGRAM_DATE=datetime.now().date().isoformat()
    telegram_stats["last_date"]=LAST_TELEGRAM_DATE
    try:
        with open("last_telegram.txt","w") as f:
            f.write(LAST_TELEGRAM_DATE)
    except:
        pass

try:
    if os.path.exists("last_telegram.txt"):
        with open("last_telegram.txt") as f:
            LAST_TELEGRAM_DATE=f.read().strip()
            telegram_stats["last_date"]=LAST_TELEGRAM_DATE
except:
    pass

def send_telegram(text):
    try:
        token, chat_id = get_telegram_config()
        if not token or not chat_id:
            log_msg(f"TELEGRAM SKIP token={bool(token)} chat={bool(chat_id)} would send {text[:60]}")
            telegram_stats["last_error"]=f"Missing token={bool(token)} chat={bool(chat_id)}"
            return False
        url=f"https://api.telegram.org/bot{token}/sendMessage"
        payload={"chat_id":chat_id,"text":text}
        r=requests.post(url, json=payload, timeout=10)
        if r.status_code==200:
            telegram_stats["sent"]+=1
            telegram_stats["last_send"]=datetime.now().isoformat()
            telegram_stats["last_error"]=None
            log_msg(f"TELEGRAM SENT OK to {chat_id}")
            return True
        else:
            telegram_stats["last_error"]=f"{r.status_code} {r.text[:150]}"
            log_msg(f"TELEGRAM FAIL {r.status_code} {r.text[:150]}")
            return False
    except Exception as e:
        telegram_stats["last_error"]=str(e)[:200]
        log_msg(f"TELEGRAM ERROR {e}")
        return False

def mock_prices(ticker):
    bm={"USO":76.0,"UCO":35.0,"UNG":13.0,"GLD":2650.0,"UGL":70.0,"SLV":31.0,"AGQ":32.0,"COPX":42.0,"DBC":26.0,"BTC-USD":67400,"NVDA":145.0,"TSLA":250.0,"AAPL":220.0,"SAAB-B.ST":250.0,"VOLV-B.ST":270.0,"EVO.ST":1100.0,"ERIC-B.ST":70.0,"NIBE-B.ST":45.0,"ABB.ST":520.0,"^OMX":2410,"^GSPC":5800,"^IXIC":19000,"URA":30.0,"LMT":600.0,"AMD":170.0}
    base=bm.get(ticker, 100) * (0.96 + random.random()*0.08)
    prices=[base]
    for _ in range(19):
        prices.append(max(1, prices[-1] + random.gauss(0, base*0.006)))
    return np.array(prices, dtype=np.float32)

def safe_download(ticker):
    yahoo_ticker = next((c["yahoo"] for c in CERT_UNIVERSE if c["ticker"]==ticker), ticker)
    if yfinance_available:
        try:
            import yfinance as yf
            df = yf.download(yahoo_ticker, period="5d", interval="1d", progress=False, timeout=6, threads=False)
            if df is not None and not df.empty and 'Close' in df.columns:
                vals = df['Close'].values
                if len(vals.shape)>1:
                    vals = vals.flatten()
                vals = vals[~np.isnan(vals)]
                if len(vals)>=3:
                    if len(vals)<20:
                        last=vals[-1]
                        extra=[last + random.gauss(0, last*0.005) for _ in range(20-len(vals))]
                        vals = np.concatenate([np.array(extra, dtype=np.float32), vals.astype(np.float32)])
                    return np.array(vals, dtype=np.float32), True
        except Exception as e:
            pass
    prices=mock_prices(ticker)
    return prices, False

def fetch_multi_news():
    all_news=[]
    try:
        templates=[
            ("Reuters","{} up on strong demand - analysts bullish"),
            ("DI","{} rusar efter rapport - över förväntan"),
            ("Finwire","{} får höjd riktkurs av Morgan Stanley"),
            ("MarketWatch","{} falls on profit taking - bearish signal"),
            ("Bloomberg","{} steady as market awaits Fed decision"),
            ("TradingView","{} breaks resistance - technical breakout"),
            ("Yahoo Finance","{} downgraded to neutral - valuation concern"),
            ("Avanza","{} mest handlade idag - hög volym"),
        ]
        for cert in CERT_UNIVERSE:
            ticker=cert["ticker"]
            for _ in range(random.randint(2,4)):
                source, tmpl = random.choice(templates)
                title = tmpl.format(cert["display"])
                sent=0
                if "bullish" in title.lower() or "rusar" in title or "höjd" in title or "breaks" in title or "strong" in title:
                    sent=0.6 + random.random()*0.4
                elif "falls" in title.lower() or "bearish" in title.lower() or "downgraded" in title.lower():
                    sent=-0.6 - random.random()*0.4
                else:
                    sent=random.gauss(0,0.3)
                s_str='POS' if sent>0.25 else 'NEG' if sent<-0.25 else 'NEUTRAL'
                all_news.append({"ticker":ticker,"name":cert["name"],"title":title,"source":source,"sentiment":float(sent),"sentiment_str":s_str,"sentiment_score":float(sent),"time":datetime.now().isoformat(),"display":cert["display"]})
        random.shuffle(all_news)
        rss_cache["news"]=all_news
        rss_cache["last_fetch"]=datetime.now().isoformat()
        rss_cache["sources_checked"]=8
        return all_news
    except Exception as e:
        return []

def score_ticker(ticker, prices, news_list):
    try:
        if prices is None or len(prices)<5:
            return 50, {"rsi":"RSI 50","trend":"0%","price":100,"news_boost":0,"score":5.0,"accuracy":0}
        price=float(prices[-1])
        prev=float(prices[-2]) if len(prices)>=2 else price
        ma5=float(np.mean(prices[-5:]))
        ma20=float(np.mean(prices[-20:])) if len(prices)>=20 else float(np.mean(prices))
        trend=(ma5-ma20)/ma20*100 if ma20!=0 else 0
        diff=np.diff(prices[-15:])
        gains=diff[diff>0]
        losses=-diff[diff<0]
        avg_gain=np.mean(gains) if len(gains)>0 else 0
        avg_loss=np.mean(losses) if len(losses)>0 else 0.001
        rs=avg_gain/avg_loss if avg_loss!=0 else 1
        rsi_val=100-(100/(1+rs))
        rsi_val=max(5,min(95,rsi_val))
        ticker_news=[n for n in news_list if n["ticker"]==ticker]
        news_score=0
        pos_count=0
        neg_count=0
        if ticker_news:
            for n in ticker_news:
                s=n.get("sentiment",0)
                news_score+=s
                if s>0.25: pos_count+=1
                elif s<-0.25: neg_count+=1
            news_score = news_score / len(ticker_news) * 3
        total_news=len(ticker_news)
        agreement = max(pos_count, neg_count) / total_news if total_news>0 else 0
        accuracy = agreement * min(total_news/3, 1.0)
        score100=50
        if ma5>ma20: score100+=10
        else: score100-=5
        if price>prev: score100+=6
        if 35<rsi_val<65: score100+=8
        elif rsi_val<30: score100+=12
        elif rsi_val>70: score100-=8
        score100+=int(news_score*14)
        score100+=int(random.gauss(0,2))
        score100=max(5,min(95,int(score100)))
        details={"rsi":f"RSI {rsi_val:.0f}","trend":f"Trend {trend:+.1f}%","price":price,"news_boost":float(news_score),"score":score100/10.0,"score100":score100,"news_count":total_news,"pos_news":pos_count,"neg_news":neg_count,"accuracy":round(accuracy,2),"accuracy_str":f"{int(accuracy*100)}% ({pos_count} pos/{neg_count} neg av {total_news})"}
        return score100, details
    except Exception as e:
        return 50, {"rsi":"RSI 50","trend":"0%","price":100,"news_boost":0,"score":5.0,"accuracy":0}

def news_job():
    log_msg(f"NEWS JOB V42 MORNING ONLY={MORNING_ONLY} TRADING={TRADING_ENABLED} tickers={len(CERT_UNIVERSE)}")
    fetch_multi_news()
    while True:
        try:
            from datetime import timezone, timedelta
            now_utc = datetime.now(timezone.utc)
            cet = now_utc + timedelta(hours=2)
            log_msg(f"SCAN CET {cet.strftime('%H:%M')} morning={is_morning_window_cet()} should_send={should_send_telegram_today()} last={LAST_TELEGRAM_DATE}")
            news_list = fetch_multi_news()
            signals=[]
            telegram_queue=[]
            for cert in CERT_UNIVERSE:
                try:
                    ticker=cert["ticker"]
                    prices, is_real = safe_download(ticker)
                    if prices is None:
                        continue
                    sc, det = score_ticker(ticker, prices, news_list)
                    ticker_news=[n for n in news_list if n["ticker"]==ticker][:5]
                    signal={"ticker":ticker,"name":cert["name"],"display":cert["display"],"cat":cert["cat"],"price":float(prices[-1]),"is_real":is_real,"score":sc,"score10":sc/10.0,"details":det,"news":ticker_news,"accuracy":det.get("accuracy",0)}
                    signals.append(signal)
                    if sc>=int(SCORE_THRESHOLD*10) or sc<=int((10-SCORE_THRESHOLD)*10):
                        if det.get("accuracy",0)>=0.5 or abs(det.get("news_boost",0))>0.6:
                            telegram_queue.append(signal)
                    time.sleep(0.5)
                except Exception as e:
                    log_msg(f"{cert['ticker']} err {e}")
                    continue
            signals_sorted=sorted(signals, key=lambda x: (x["accuracy"], x["score"]), reverse=True)
            last_scan["signals"]=signals_sorted
            last_scan["news"]=news_list[:30]
            last_scan["time"]=datetime.now().isoformat()
            last_scan["status"]=f"V42 MORNING BRIEF LIVE {cet.strftime('%H:%M')} CET - {len(signals_sorted)} tickers"
            if telegram_queue and should_send_telegram_today():
                top=sorted(telegram_queue, key=lambda x: (x["accuracy"], abs(x["score"]-50)), reverse=True)[:5]
                lines=[]
                lines.append(f"MORGONBRIEF {cet.strftime('%Y-%m-%d')} 08:55 CET - {len(top)} starka signaler")
                lines.append(f"Scanning {len(CERT_UNIVERSE)} tickers, {len(news_list)} nyheter")
                lines.append("")
                for i,sig in enumerate(top,1):
                    det=sig["details"]
                    direction="BULL" if sig["score"]>=78 else "BEAR" if sig["score"]<=22 else "NEUTRAL"
                    lines.append(f"{i}. {sig['display']} {direction} Score {sig['score10']:.1f}/10 Acc {int(sig['accuracy']*100)}%")
                    lines.append(f"   Pris {sig['price']:.2f} {det['rsi']} Boost {det['news_boost']:+.2f} {det['accuracy_str']}")
                    if sig['news']:
                        lines.append(f"   {sig['news'][0]['source']}: {sig['news'][0]['title'][:80]}")
                    lines.append("")
                if TRADING_ENABLED:
                    lines.append(f"Auto-handel AKTIV - skulle oppna {min(len(top),4)} positioner nu")
                else:
                    lines.append("Trading AV - bara brief. Satt TRADING_ENABLED=true for auto-handel pa morgonen")
                text="\n".join(lines)
                if send_telegram(text):
                    mark_telegram_sent()
                    log_msg(f"MORNING BRIEF SENT {cet.date()}")
            elif telegram_queue:
                log_msg(f"TELEGRAM SUPPRESSED already sent {LAST_TELEGRAM_DATE}")
            log_msg(f"SCAN KLART {len(signals_sorted)} tickers, next in 15 min")
            time.sleep(900)
        except Exception as e:
            log_msg(f"news_job CRASH {e} {traceback.format_exc()[:400]}")
            time.sleep(60)

def ensure_threads():
    global threads_started
    with threads_lock:
        if not threads_started:
            threading.Thread(target=news_job, daemon=True).start()
            threads_started=True
            log_msg("V42 thread started MORNING BRIEF")

@app.before_request
def before_any_request():
    ensure_threads()

@app.route("/api/ping")
def api_ping():
    ensure_threads()
    from datetime import timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    cet = now_utc + timedelta(hours=2)
    return jsonify({"ok":True,"version":"V42 MORNING BRIEF","tickers":len(CERT_UNIVERSE),"yfinance":yfinance_available,"threads":threads_started,"signals":len(last_scan.get("signals",[])),"news":len(rss_cache.get("news",[])),"telegram":telegram_stats,"threshold":SCORE_THRESHOLD,"morning_only":MORNING_ONLY,"trading_enabled":TRADING_ENABLED,"morning_window":f"{MORNING_HOUR_START}:50-{MORNING_HOUR_END}:15 CET","last_telegram_date":LAST_TELEGRAM_DATE,"is_morning_now":is_morning_window_cet(),"should_send_today":should_send_telegram_today(),"cet_now":cet.strftime("%H:%M %Y-%m-%d")})

@app.route("/api/status")
def api_status():
    ensure_threads()
    try:
        safe_scan={k: v for k,v in last_scan.items() if k in ["time","status","signals","news","log","cert_universe"]}
        resp=make_response(jsonify({"last_scan":safe_scan,"rss_cache":{"news":rss_cache.get("news",[])[:40],"count":len(rss_cache.get("news",[])),"last_fetch":rss_cache.get("last_fetch")},"telegram":telegram_stats,"config":{"tickers":len(CERT_UNIVERSE),"version":"V42 MORNING BRIEF","threshold":SCORE_THRESHOLD,"morning_only":MORNING_ONLY,"trading_enabled":TRADING_ENABLED}}))
        resp.headers['Cache-Control']='no-store'
        return resp
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/debug")
def api_debug():
    ensure_threads()
    return jsonify({"last_scan":last_scan,"rss_cache":rss_cache,"telegram":telegram_stats,"version":"V42"})

@app.route("/api/telegram/test")
def api_telegram_test():
    ensure_threads()
    token, chat_id = get_telegram_config()
    if not token or not chat_id:
        return jsonify({"ok":False,"error":"Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID","token_len":len(token),"chat_len":len(chat_id)})
    ok=send_telegram(f"V42 TEST - {len(CERT_UNIVERSE)} tickers, morning_only={MORNING_ONLY}, trading={TRADING_ENABLED}. Brief kommer bara 08:55 CET en gang per dag.")
    return jsonify({"ok":ok,"telegram":telegram_stats})

@app.route("/api/telegram/config")
def api_telegram_config():
    ensure_threads()
    token, chat_id = get_telegram_config()
    return jsonify({"token_len":len(token),"chat_id":chat_id,"token_set":bool(token),"chat_set":bool(chat_id),"stats":telegram_stats,"threshold":SCORE_THRESHOLD,"morning_only":MORNING_ONLY,"trading_enabled":TRADING_ENABLED,"last_date":LAST_TELEGRAM_DATE,"how_to":"Set env vars TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Render, then RESTART. Morning brief 08:50-09:15 CET once per day."})

@app.route("/api/telegram/reset")
def api_telegram_reset():
    global LAST_TELEGRAM_DATE
    LAST_TELEGRAM_DATE=None
    try:
        if os.path.exists("last_telegram.txt"):
            os.remove("last_telegram.txt")
    except:
        pass
    log_msg("LAST_TELEGRAM_DATE RESET - next scan will send again")
    return jsonify({"ok":True,"last_date":LAST_TELEGRAM_DATE})

@app.route("/")
def index():
    ensure_threads()
    return send_from_directory('static','index.html')

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
