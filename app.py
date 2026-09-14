
import os, json, requests
from flask import Flask, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import yfinance as yf
import pandas as pd

app = Flask(__name__, static_folder='static')
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8752642455:AAEpGTSis6YVij46PrePRZnLqWbQ7OBCZvM")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1033208239")
BUDGET = int(os.getenv("DAILY_BUDGET_SEK", "10000"))
COURTAGE_TYPE = os.getenv("COURTAGE_TYPE", "mini")
MAX_DAILY_LOSS = int(os.getenv("MAX_DAILY_LOSS_SEK", "300"))
DATA_FILE = "/tmp/portfolio.json"

def calc_courtage(a, t="mini"):
    if t=="mini": return max(1, a*0.0025)
    if t=="small": return max(9, a*0.00055)
    return max(1, a*0.0025)

def load_portfolio():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f: return json.load(f)
    except: pass
    return {"start": BUDGET, "current": BUDGET, "trades": [], "total_pnl": 0.0, "total_pnl_after": 0.0, "total_courtage": 0.0, "win_rate": 0, "win_rate_after": 0, "total": 0, "wins": 0, "wins_after": 0, "daily_pnl": 0.0, "last_reset": datetime.now().date().isoformat()}

def save_portfolio(p):
    try:
        with open(DATA_FILE, "w") as f: json.dump(p, f)
    except: pass

portfolio = load_portfolio()
today = datetime.now().date().isoformat()
if portfolio.get("last_reset") != today:
    portfolio["daily_pnl"]=0.0; portfolio["last_reset"]=today; save_portfolio(portfolio)

last_scan = {"time": None, "raketer": [], "status": "Startar...", "portfolio": portfolio, "budget": BUDGET, "max_daily_loss": MAX_DAILY_LOSS, "news": []}

WATCHLIST = [
    {"ticker": "USO", "name": "Olja USO"},
    {"ticker": "GLD", "name": "Guld GLD"},
    {"ticker": "QQQ", "name": "Nasdaq QQQ"},
    {"ticker": "TSLA", "name": "Tesla"},
    {"ticker": "NVDA", "name": "Nvidia"},
    {"ticker": "BTC-USD", "name": "Bitcoin"},
]

def send_tg(m):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": m, "parse_mode": "Markdown"}, timeout=10)
    except: pass


def get_real_news(ticker):
    """Fixad - hanterar svenska aktier som har dålig Yahoo coverage"""
    try:
        t = yf.Ticker(ticker)
        raw_news = t.news
        if not raw_news:
            return []  # Svenska aktier ger ofta tom lista på helg
        seen_titles = set()
        res = []
        for n in raw_news:
            title = n.get('title','').strip()
            # Skippa om titel saknas eller är tom (det var ditt fel - visade bara "-")
            if not title or len(title) < 10:
                continue
            # Deduplicera
            if title in seen_titles:
                continue
            seen_titles.add(title)
            tl = title.lower()
            # Sentiment - mer träffsäkert
            pos_words = ['avtal','forvarv','order','rapport battre','hojer','okar','vinst','samarbete','uppkop','uppgradering','rekord','tillvaxt']
            neg_words = ['forlust','sanker','nedgradering','boter','stamming','varsel','konkurs','saljer av','nedskrivning','varning']
            sent = 'neutral'
            if any(w in tl for w in pos_words): sent = 'pos'
            if any(w in tl for w in neg_words): sent = 'neg'
            # Trump / olja specifikt
            trump_related = any(k in tl for k in ['trump','biden','fed','opec','iran','russia','tariff','inflation','powell'])
            ts = n.get('providerPublishTime')
            time_str = ''
            try:
                time_str = datetime.fromtimestamp(ts).strftime('%H:%M') if ts else ''
            except: pass
            # Skippa gamla nyheter >7 dagar
            if ts and (datetime.now().timestamp() - ts) > 7*24*3600:
                continue
            res.append({
                "ticker": ticker,
                "title": title[:120],
                "publisher": n.get('publisher',''),
                "sentiment": sent,
                "time": time_str,
                "trump_related": trump_related
            })
            if len(res) >= 2:  # Max 2 per ticker
                break
        return res
    except Exception as e:
        print(f"News error {ticker}: {e}")
        return []

def get_trump_oil_news():
    """Hämtar bredare olja/guld nyheter för att få riktiga headlines även för svenska boten"""
    try:
        # Försök hämta från USO och GLD som har mycket nyheter
        all_news = []
        for t in ["USO", "GLD", "OIL"]:
            try:
                tn = yf.Ticker(t)
                raw = tn.news
                if raw:
                    for n in raw[:2]:
                        title = n.get('title','').strip()
                        if len(title) < 15: continue
                        tl = title.lower()
                        if any(k in tl for k in ['oil','gold','opec','fed','trump','iran','russia','dollar']):
                            all_news.append({
                                "ticker": t,
                                "title": title[:120],
                                "publisher": n.get('publisher',''),
                                "sentiment": 'pos' if any(w in tl for w in ['rise','up','gain','surge','rally']) else 'neg' if any(w in tl for w in ['fall','drop','down','crash']) else 'neutral',
                                "time": datetime.fromtimestamp(n.get('providerPublishTime',0)).strftime('%H:%M') if n.get('providerPublishTime') else '',
                                "trump_related": 'trump' in tl
                            })
            except: continue
        return all_news[:5]
    except: return []


def get_trump_oil_news(ticker):
    """Fixad - hanterar svenska aktier som har dålig Yahoo coverage"""
    try:
        t = yf.Ticker(ticker)
        raw_news = t.news
        if not raw_news:
            return []  # Svenska aktier ger ofta tom lista på helg
        seen_titles = set()
        res = []
        for n in raw_news:
            title = n.get('title','').strip()
            # Skippa om titel saknas eller är tom (det var ditt fel - visade bara "-")
            if not title or len(title) < 10:
                continue
            # Deduplicera
            if title in seen_titles:
                continue
            seen_titles.add(title)
            tl = title.lower()
            # Sentiment - mer träffsäkert
            pos_words = ['avtal','forvarv','order','rapport battre','hojer','okar','vinst','samarbete','uppkop','uppgradering','rekord','tillvaxt']
            neg_words = ['forlust','sanker','nedgradering','boter','stamming','varsel','konkurs','saljer av','nedskrivning','varning']
            sent = 'neutral'
            if any(w in tl for w in pos_words): sent = 'pos'
            if any(w in tl for w in neg_words): sent = 'neg'
            # Trump / olja specifikt
            trump_related = any(k in tl for k in ['trump','biden','fed','opec','iran','russia','tariff','inflation','powell'])
            ts = n.get('providerPublishTime')
            time_str = ''
            try:
                time_str = datetime.fromtimestamp(ts).strftime('%H:%M') if ts else ''
            except: pass
            # Skippa gamla nyheter >7 dagar
            if ts and (datetime.now().timestamp() - ts) > 7*24*3600:
                continue
            res.append({
                "ticker": ticker,
                "title": title[:120],
                "publisher": n.get('publisher',''),
                "sentiment": sent,
                "time": time_str,
                "trump_related": trump_related
            })
            if len(res) >= 2:  # Max 2 per ticker
                break
        return res
    except Exception as e:
        print(f"News error {ticker}: {e}")
        return []

def get_trump_oil_news():
    return []

def get_real_news_old(ticker):
    """Hämtar bredare olja/guld nyheter för att få riktiga headlines även för svenska boten"""
    try:
        # Försök hämta från USO och GLD som har mycket nyheter
        all_news = []
        for t in ["USO", "GLD", "OIL"]:
            try:
                tn = yf.Ticker(t)
                raw = tn.news
                if raw:
                    for n in raw[:2]:
                        title = n.get('title','').strip()
                        if len(title) < 15: continue
                        tl = title.lower()
                        if any(k in tl for k in ['oil','gold','opec','fed','trump','iran','russia','dollar']):
                            all_news.append({
                                "ticker": t,
                                "title": title[:120],
                                "publisher": n.get('publisher',''),
                                "sentiment": 'pos' if any(w in tl for w in ['rise','up','gain','surge','rally']) else 'neg' if any(w in tl for w in ['fall','drop','down','crash']) else 'neutral',
                                "time": datetime.fromtimestamp(n.get('providerPublishTime',0)).strftime('%H:%M') if n.get('providerPublishTime') else '',
                                "trump_related": 'trump' in tl
                            })
            except: continue
        return all_news[:5]
    except: return []


def score_v3(df, news_items):
    try:
        if len(df)<50: return 0,[],{}, None
        close=df['Close']; price=float(close.iloc[-1])
        sma20=close.rolling(20).mean().iloc[-1]; sma50=close.rolling(50).mean().iloc[-1]
        delta=close.diff(); gain=delta.where(delta>0,0).rolling(14).mean(); loss=-delta.where(delta<0,0).rolling(14).mean()
        rs=gain/loss; rsi=100-(100/(1+rs)); rsi_val=float(rsi.iloc[-1])
        vol=df['Volume'].iloc[-1]; vol_avg=df['Volume'].rolling(20).mean().iloc[-1]; vol_ratio=vol/vol_avg if vol_avg>0 else 1
        s=0; rsns=[]; news_flag=None
        if price>sma20: s+=15; rsns.append("Over SMA20")
        if sma20>sma50: s+=15; rsns.append("SMA20>SMA50")
        if 50<rsi_val<70: s+=15; rsns.append(f"RSI {rsi_val:.0f}")
        if vol_ratio>1.2: s+=15; rsns.append(f"Vol {vol_ratio:.1f}x")
        if close.iloc[-1]>close.iloc[-5]: s+=15; rsns.append("Mom+")
        if news_items:
            for n in news_items:
                if n['sentiment']=='pos': s+=10; news_flag=n['title'][:40]; rsns.append(f"News +")
                if n['sentiment']=='neg': s-=15; news_flag=n['title'][:40]; rsns.append(f"News -")
        pos=BUDGET*0.2; cost=calc_courtage(pos, COURTAGE_TYPE)*2 + pos*0.002; cost_pct=cost/pos*100
        details={"price": price, "cost_pct": cost_pct}
        if cost_pct>1.5 and s<80: s-=10
        if price<5: s-=15
        return max(0,min(100,s)), rsns, details, news_flag
    except: return 0,[],{}, None

def get_data(t):
    try:
        df=yf.Ticker(t).history(period="6mo", auto_adjust=True)
        return None if df.empty else df
    except: return None

def job(force=False):
    now=datetime.now()
    today=now.date().isoformat()
    if portfolio.get("last_reset")!=today:
        portfolio["daily_pnl"]=0.0; portfolio["last_reset"]=today; save_portfolio(portfolio)
    if portfolio.get("daily_pnl",0) <= -MAX_DAILY_LOSS:
        last_scan["status"]=f"STOPPAD Max forlust {portfolio['daily_pnl']:.0f}kr / -{MAX_DAILY_LOSS}kr"
        last_scan["portfolio"]=portfolio; return
    if not force and not (7 <= now.hour < 11):
        last_scan["status"]=f"Vilar {now.strftime('%H:%M')} UTC - Daily {portfolio.get('daily_pnl',0):.0f}kr"
        last_scan["portfolio"]=portfolio; return
    all_news=[]; rak=[]
    for item in WATCHLIST:
        df=get_data(item['ticker'])
        if df is None: continue
        news=get_real_news(item['ticker'])
        all_news.extend(news)
        sc,rs,det,news_flag=score_v3(df, news)
        if sc>=65:
            rak.append({**item, "score": sc, "price": det.get("price",0), "reasons": rs, "news": news_flag, "details": det})
            pos=BUDGET*0.2
            if portfolio["current"]>=pos and not any(tr["ticker"]==item["ticker"] and tr.get("sell_price") is None for tr in portfolio["trades"]):
                cb=calc_courtage(pos, COURTAGE_TYPE)
                tr={"ticker": item["ticker"], "name": item["name"], "buy_price": det.get("price",0), "buy_time": now.isoformat(), "score": sc, "position": pos, "courtage_buy": cb, "sell_price": None}
                portfolio["trades"].append(tr); portfolio["current"]-=(pos+cb); portfolio["total_courtage"]+=cb; save_portfolio(portfolio)
    for tr in portfolio["trades"]:
        if tr["sell_price"] is None:
            df=get_data(tr["ticker"])
            if df is None: continue
            cp=float(df['Close'].iloc[-1]); pct=(cp-tr["buy_price"])/tr["buy_price"]; days=(now-datetime.fromisoformat(tr["buy_time"])).days
            if pct>=0.04 or pct<=-0.025 or days>=4:
                cs=calc_courtage(tr["position"], COURTAGE_TYPE); gross=(cp-tr["buy_price"])*(tr["position"]/tr["buy_price"]); net=gross-tr["courtage_buy"]-cs
                tr["sell_price"]=cp; tr["courtage_sell"]=cs; tr["pnl"]=gross; tr["pnl_after"]=net; tr["pnl_pct"]=pct*100
                portfolio["total_pnl"]+=gross; portfolio["total_pnl_after"]+=net; portfolio["daily_pnl"]=portfolio.get("daily_pnl",0)+net; portfolio["total_courtage"]+=cs; portfolio["total"]+=1
                if gross>0: portfolio["wins"]+=1
                if net>0: portfolio["wins_after"]+=1
                if portfolio["total"]>0:
                    portfolio["win_rate"]=portfolio["wins"]/portfolio["total"]*100
                    portfolio["win_rate_after"]=portfolio["wins_after"]/portfolio["total"]*100
                portfolio["current"]+=tr["position"]+gross-cs; save_portfolio(portfolio)
    rak.sort(key=lambda x: x["score"], reverse=True)
    last_scan["time"]=now.isoformat(); last_scan["raketer"]=rak; last_scan["portfolio"]=portfolio; last_scan["news"]=all_news[:12]
    last_scan["status"]=f"V3 {len(rak)} raketer P/L efter {portfolio['total_pnl_after']:.1f}kr Daily {portfolio.get('daily_pnl',0):.0f}kr News {len(all_news)}"
    if rak:
        msg=f"V3 {len(rak)} raketer P/L efter {portfolio['total_pnl_after']:.1f}kr Daily {portfolio.get('daily_pnl',0):.0f}kr"
        send_tg(msg)

sched=BackgroundScheduler(); sched.add_job(lambda: job(force=False), 'interval', minutes=5); sched.start(); job(force=True)

@app.route("/")
def idx(): return send_from_directory('static','index.html')
@app.route("/manifest.json")
def man(): return send_from_directory('static','manifest.json')
@app.route("/icon-192.png")
def i192(): return send_from_directory('static','icon-192.png')
@app.route("/icon-512.png")
def i512(): return send_from_directory('static','icon-512.png')
@app.route("/api/status")
def st(): return jsonify(last_scan)
@app.route("/api/portfolio")
def pf(): return jsonify(portfolio)
@app.route("/api/news")
def news_api(): return jsonify({"news": last_scan.get("news",[]), "time": last_scan.get("time")})
@app.route("/api/courtage")
def ct():
    res=[]
    for a in [1000,2000,5000,10000]:
        c=calc_courtage(a, COURTAGE_TYPE)
        res.append({"amount": a, "one_way": c, "both": c*2, "pct": c*2/a*100})
    return jsonify({"type": COURTAGE_TYPE, "examples": res})
@app.route("/api/test-telegram")
def tt(): send_tg(f"V3 med RIKTIGA NYHETER + DYNAMISK PRESTANDA + TEMA\nP/L efter {portfolio['total_pnl_after']:.1f}kr Daily {portfolio.get('daily_pnl',0):.0f}kr"); return jsonify({"ok": True})
@app.route("/api/scan-now")
def sn(): job(force=True); return jsonify(last_scan)
@app.route("/api/reset-daily")
def reset_daily(): portfolio["daily_pnl"]=0.0; portfolio["last_reset"]=datetime.now().date().isoformat(); save_portfolio(portfolio); return jsonify({"ok": True})

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
