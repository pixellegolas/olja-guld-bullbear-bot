
import os, json, time, threading
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_from_directory, make_response
import yfinance as yf
import requests

app = Flask(__name__, static_folder='static')
DATA_FILE = "/tmp/portfolio_v3.json"
BUDGET = float(os.getenv("DAILY_BUDGET_SEK", "10000"))
POSITION_SIZE = 500
MAX_DAILY_LOSS = 250
MAX_POSITIONS = 3
SPREAD_PCT = 0.007
COURTAGE_PCT = 0.0025
COURTAGE_MIN = 1.0
LEVERAGE = 5

WATCHLIST = [
    {"ticker": "USO", "name": "OLJA", "cert_bull": "BULL OLJA X1 AVA", "cert_bear": "BEAR OLJA X1 AVA"},
    {"ticker": "GLD", "name": "GULD", "cert_bull": "BULL GULD X1 NORD", "cert_bear": "BEAR GULD X1 NORD"},
]

TRAILING_MODES = {
    "low": {"activate_pct": 0.04, "trail_pct": 0.02, "label": "Låg +4% → -2.0%"},
    "medium": {"activate_pct": 0.03, "trail_pct": 0.012, "label": "Mellan +3% → -1.2%"},
    "aggressive": {"activate_pct": 0.02, "trail_pct": 0.008, "label": "Aggressiv +2% → -0.8%"},
}

portfolio = {"cash": BUDGET, "positions": [], "history": [], "daily_pnl": 0, "last_reset": datetime.now().isoformat()}
last_scan = {"time": datetime.now().isoformat(), "signals": [], "news": [], "status": "init", "market_open": False, "cet_time": datetime.now().isoformat()}

def courtage(a): return max(a*COURTAGE_PCT, COURTAGE_MIN)
def load_portfolio():
    global portfolio
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE) as f: portfolio=json.load(f)
    except: pass
def save_portfolio():
    try:
        with open(DATA_FILE,'w') as f: json.dump(portfolio,f)
    except: pass

def is_market_open():
    now_utc=datetime.utcnow()
    cet=now_utc+timedelta(hours=2)
    if cet.weekday()>=5: return False,cet
    open_t=cet.replace(hour=8,minute=55,second=0); close_t=cet.replace(hour=17,minute=30,second=0)
    return open_t<=cet<=close_t, cet

def get_news_safe(ticker):
    try:
        t=yf.Ticker(ticker)
        # yfinance news can be empty - try with error handling
        raw = getattr(t, 'news', None) or []
        out=[]
        for n in raw[:6]:
            title=n.get('title','') if isinstance(n, dict) else ''
            if not title: continue
            low=title.lower()
            sentiment='neutral'; boost=0
            if ticker=='USO':
                if any(k in low for k in ['opec','cut','iran','sanction','war','attack','tension','inventory falls','draw']):
                    sentiment='pos'; boost=15
                if any(k in low for k in ['drill','production up','demand weak','inventory up','build']):
                    sentiment='neg'; boost=-15
            if ticker=='GLD':
                if any(k in low for k in ['fed dovish','rate cut','vix','fear','war','safe haven','geopolitical']):
                    sentiment='pos'; boost=15
                if any(k in low for k in ['dollar strong','hawkish','rate hike','yields up']):
                    sentiment='neg'; boost=-15
            out.append({"ticker":ticker,"title":title[:140],"publisher":n.get('publisher','Yahoo') if isinstance(n, dict) else 'Yahoo',"sentiment":sentiment,"boost":boost,"time":datetime.now().strftime('%H:%M')})
        # If still empty, create synthetic news from price move to avoid blank UI
        if not out:
            try:
                df=yf.download(ticker, period='2d', interval='1d', progress=False)
                if not df.empty and len(df)>=2:
                    ch = (df['Close'].iloc[-1]-df['Close'].iloc[-2])/df['Close'].iloc[-2]*100
                    if abs(ch)>0.3:
                        out.append({"ticker":ticker,"title":f"{ticker} {'stiger' if ch>0 else 'faller'} {ch:+.1f}% senaste dygnet - {'momentum upp' if ch>0 else 'press nedåt'}","publisher":"Yahoo Finance","sentiment":'pos' if ch>0 else 'neg',"boost":5 if ch>0 else -5,"time":datetime.now().strftime('%H:%M')})
            except: pass
        return out
    except Exception as e:
        print(f"news error {ticker}: {e}")
        return []

def score_ticker(df, news_list):
    if df.empty or len(df)<30: return 50,{}
    close=df['Close']; sma20=close.rolling(20).mean().iloc[-1]; sma50=close.rolling(50).mean().iloc[-1]
    diff=close.diff(); gain=diff.where(diff>0,0).rolling(14).mean().iloc[-1]; loss=-diff.where(diff<0,0).rolling(14).mean().iloc[-1]
    rsi=100-(100/(1+gain/max(0.001,loss))) if loss!=0 else 50
    atr=(df['High']-df['Low']).rolling(14).mean().iloc[-1]/close.iloc[-1] if close.iloc[-1]!=0 else 0
    price=close.iloc[-1]
    score=50; det={}
    if price>sma20 and sma20>sma50: score+=18; det['trend']='BULL trend 4H'
    elif price<sma20 and sma20<sma50: score-=18; det['trend']='BEAR trend 4H'
    if rsi<38: score+=14; det['rsi']=f'Översåld RSI {rsi:.0f}'
    elif rsi>62: score-=14; det['rsi']=f'Överköpt RSI {rsi:.0f}'
    else: det['rsi']=f'RSI {rsi:.0f}'
    if atr>0.035: det['atr']=f'Hög vola {atr*100:.2f}%'; return None,det
    news_boost=sum(n['boost'] for n in news_list)/10.0
    score+=news_boost*5
    det['news_boost']=news_boost
    return max(5,min(95,score)),det

def send_telegram(msg):
    tok=os.getenv("TELEGRAM_TOKEN"); chat=os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat: return
    try: requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id":chat,"text":msg}, timeout=10)
    except: pass

def trading_job():
    global last_scan
    load_portfolio(); premarket=False
    print("Trading job started")
    while True:
        try:
            last_reset=datetime.fromisoformat(portfolio.get('last_reset',datetime.now().isoformat()))
            if datetime.now().date()>last_reset.date():
                portfolio['daily_pnl']=0; portfolio['last_reset']=datetime.now().isoformat(); save_portfolio(); premarket=False
            is_open,cet=is_market_open(); last_scan['market_open']=is_open; last_scan['cet_time']=cet.isoformat()
            if not is_open:
                last_scan['status']=f"MARKET CLOSED {cet.strftime('%H:%M')} CET - öppnar 08:55"
                # Update positions still
                for p in portfolio['positions']:
                    try:
                        df=yf.download(p['underlying'],period='5d',interval='1d',progress=False)
                        if df.empty: continue
                        cur=float(df['Close'].iloc[-1]); ch=(cur-p['entry_price'])/p['entry_price']
                        if p['direction']=='BEAR': ch=-ch
                        cert=100*(1+ch*LEVERAGE); p['current_cert_value']=cert
                        if cert>p['highest_cert']: p['highest_cert']=cert
                    except: pass
                save_portfolio()
                last_scan['time']=datetime.now().isoformat()
                time.sleep(60)
                continue

            if portfolio['daily_pnl'] <= -MAX_DAILY_LOSS:
                last_scan['status']=f"STOPPAD - daglig förlust -{MAX_DAILY_LOSS}kr nådd"; last_scan['time']=datetime.now().isoformat(); time.sleep(60); continue

            signals=[]; all_news=[]
            for item in WATCHLIST:
                try:
                    df=yf.download(item['ticker'],period='3mo',interval='1d',progress=False)
                    news=get_news_safe(item['ticker']); all_news.extend(news)
                    sc,det=score_ticker(df,news)
                    if sc is None: continue
                    has=any(p['underlying']==item['ticker'] for p in portfolio['positions'])
                    signals.append({"ticker":item['ticker'],"name":item['name'],"price":float(df['Close'].iloc[-1]),"score":sc,"details":det,"news":news,"has_pos":has})
                except Exception as e:
                    print(f"score error {item}: {e}")
                    continue
            signals_sorted=sorted(signals,key=lambda x:x['score'],reverse=True)
            last_scan['time']=datetime.now().isoformat(); last_scan['signals']=signals_sorted; last_scan['news']=all_news[:12]
            last_scan['status']=f"MARKET OPEN {cet.strftime('%H:%M')} - aktiv • scan {datetime.now().strftime('%H:%M:%S')}"

            if cet.hour==8 and 55<=cet.minute<=59 and not premarket and signals_sorted:
                top=[s for s in signals_sorted if s['score']>=70 or s['score']<=30][:3]
                if top:
                    msg=f"Market öppnar 09:00 - {len(top)} signaler:\n"
                    for t in top: msg+=f"{'BULL' if t['score']>=70 else 'BEAR'} {t['name']} {t['score']:.0f}\n"
                    send_telegram(msg); premarket=True

            mode_key=os.getenv("TRAILING_MODE","medium"); mode=TRAILING_MODES.get(mode_key,TRAILING_MODES['medium'])
            # Buy logic
            for s in signals_sorted:
                if len(portfolio['positions'])>=MAX_POSITIONS: break
                if s['has_pos']: continue
                if portfolio['cash']<POSITION_SIZE: continue
                buy=None
                if s['score']>=78: buy='BULL'
                elif s['score']<=22: buy='BEAR'
                if not buy: continue
                spread=POSITION_SIZE*SPREAD_PCT; court=courtage(POSITION_SIZE); tot=POSITION_SIZE+spread+court
                if portfolio['cash']<tot: continue
                portfolio['cash']-=tot
                pos={"id":datetime.now().isoformat(),"underlying":s['ticker'],"name":s['name'],"direction":buy,"cert":next((w[f'cert_{buy.lower()}'] for w in WATCHLIST if w['ticker']==s['ticker']),buy),"entry_price":s['price'],"entry_time":datetime.now().isoformat(),"size_sek":POSITION_SIZE,"cert_entry_value":100.0,"current_cert_value":100.0,"highest_cert":100.0,"trailing_active":False,"trailing_stop":None,"spread_paid":spread,"courtage_paid":court,"score_at_entry":s['score']}
                portfolio['positions'].append(pos); save_portfolio()
                send_telegram(f"KÖP {buy} {s['name']} X5 Score {s['score']:.0f} Pris {s['price']:.2f}")

            # Sell logic
            to_rem=[]
            for p in portfolio['positions']:
                try:
                    df=yf.download(p['underlying'],period='5d',interval='1d',progress=False)
                    if df.empty: continue
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
                    elif p['trailing_active'] and p['trailing_stop'] and cert<=p['trailing_stop']: sell=True; reason=f"Trailing {p['trailing_stop']:.1f} säkrad +{cert-100:.1f}%"
                    elif cert>=106: sell=True; reason=f"TP +6% {cert:.1f}"
                    elif (datetime.now()-datetime.fromisoformat(p['entry_time'])).days>=4: sell=True; reason="Tidsstopp 4d"
                    if sell:
                        exit_v=p['size_sek']*(cert/100); spread_e=exit_v*SPREAD_PCT; court_e=courtage(exit_v); net=exit_v-spread_e-court_e
                        pnl=net-p['size_sek']-p['spread_paid']-p['courtage_paid']
                        portfolio['cash']+=net; portfolio['daily_pnl']+=pnl
                        portfolio['history'].append({**p,"exit_price":cur,"exit_cert":cert,"exit_time":datetime.now().isoformat(),"pnl":pnl,"reason":reason})
                        to_rem.append(p); save_portfolio()
                        send_telegram(f"SÄLJ {p['direction']} {p['name']} | {reason} P/L {pnl:.1f}kr")
                except Exception as e:
                    print(f"sell error {e}")
                    continue
            for r in to_rem:
                if r in portfolio['positions']: portfolio['positions'].remove(r)
            save_portfolio()
        except Exception as e:
            print(f"trading_job error {e}")
            last_scan['status']=f"Error {e}"; last_scan['time']=datetime.now().isoformat()
        # LIVE FIX: 60s when open, 60s when closed (was 900s before = 15min)
        time.sleep(60)

@app.route("/")
def index():
    return send_from_directory('static','index.html')

@app.route("/api/ping")
def ping():
    is_open,cet=is_market_open()
    resp=make_response(jsonify({"ok":True,"time":datetime.utcnow().isoformat(),"cet":cet.isoformat(),"market_open":is_open,"last_scan":last_scan['time'],"note":"Ping var 5e min i UptimeRobot. Trading 08:55-17:30 CET"}))
    resp.headers['Cache-Control']='no-store'
    return resp

@app.route("/api/status")
def status():
    resp=make_response(jsonify({"portfolio":portfolio,"last_scan":last_scan,"config":{"budget":BUDGET,"position":POSITION_SIZE,"max_daily":MAX_DAILY_LOSS,"spread":SPREAD_PCT,"trailing_modes":TRAILING_MODES,"hours":"08:55-17:30 CET"}}))
    resp.headers['Cache-Control']='no-store, no-cache, must-revalidate'
    return resp

@app.route("/api/scan-now")
def scan():
    return jsonify(last_scan)

@app.route("/api/set-trailing/<mode>")
def set_trail(mode):
    if mode in TRAILING_MODES:
        os.environ["TRAILING_MODE"]=mode
        return jsonify({"ok":True,"mode":TRAILING_MODES[mode]})
    return jsonify({"ok":False}),400

@app.route("/api/reset-daily")
def reset():
    portfolio['daily_pnl']=0; portfolio['last_reset']=datetime.now().isoformat(); save_portfolio(); return jsonify({"ok":True})

load_portfolio()
threading.Thread(target=trading_job,daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
