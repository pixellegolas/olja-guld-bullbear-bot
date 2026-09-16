import os, time, json, threading, traceback, random
from datetime import datetime
from flask import Flask, jsonify, make_response, send_from_directory
import numpy as np

print("V40.25 REAL + MOCK FALLBACK - TRY YFINANCE", flush=True)

app = Flask(__name__, static_folder='static')

BUDGET=10000.0
POSITION_SIZE=1500
MAX_POSITIONS=4
SPREAD_PCT=0.02
COURTAGE=1
MAX_DAILY_LOSS=500
TRAILING_MODES={"low":{"activate_pct":0.022,"trail_pct":0.009},"mid":{"activate_pct":0.035,"trail_pct":0.014},"high":{"activate_pct":0.05,"trail_pct":0.02}}

portfolio={"cash":BUDGET,"positions":[],"history":[],"daily_pnl":0,"last_reset":datetime.now().isoformat()}
last_scan={"time":datetime.now().isoformat(),"status":"V40.25 INIT REAL+MOCK","signals":[],"news":[],"log":[],"market_open":True,"cet_time":datetime.now().isoformat(),"cert_universe":[]}
rss_cache={"news":[],"last_fetch":None}
yfinance_available=False
try:
    import yfinance as yf
    yfinance_available=True
    print("yfinance available - REAL prices enabled", flush=True)
except Exception as e:
    print(f"yfinance not available {e} - using mock only", flush=True)

def log_msg(msg):
    try:
        ts=datetime.now().strftime("%H:%M:%S")
        entry=f"{ts} {msg}"
        print(entry, flush=True)
        last_scan["log"].append(entry)
        if len(last_scan["log"])>70:
            last_scan["log"]=last_scan["log"][-70:]
    except:
        print(msg, flush=True)

def load_portfolio():
    try:
        if os.path.exists("portfolio.json"):
            with open("portfolio.json","r") as f:
                data=json.load(f)
                if "cash" in data:
                    portfolio.update(data)
                    log_msg(f"Portfolio loaded cash {portfolio['cash']:.0f} pos {len(portfolio['positions'])}")
    except Exception as e:
        log_msg(f"load fail {e}")

def save_portfolio():
    try:
        with open("portfolio.json","w") as fh:
            json.dump(portfolio, fh)
    except Exception as e:
        log_msg(f"save fail {e}")

def mock_prices(ticker):
    bm={"USO":76.12,"GLD":2654.50,"SLV":31.20,"UNG":13.10,"DBC":26.40,"COPX":42.30,"UCO":34.50,"AGQ":31.80,"BTC-USD":67420,"^OMX":2412}
    base=bm.get(ticker, 100) * (0.96 + random.random()*0.08)
    prices=[base]
    for _ in range(19):
        prices.append(max(1, prices[-1] + random.gauss(0, base*0.007)))
    return np.array(prices, dtype=np.float32)

def safe_download(ticker):
    # TRY REAL FIRST, FALLBACK TO MOCK
    if yfinance_available:
        try:
            import yfinance as yf
            # Use fast timeout, small period to save memory
            df = yf.download(ticker, period="5d", interval="1d", progress=False, timeout=5, threads=False)
            if df is not None and not df.empty and 'Close' in df.columns:
                # Handle multiindex from yfinance
                close_series = df['Close']
                if hasattr(close_series, 'values'):
                    vals = close_series.values
                    # flatten if 2D
                    if len(vals.shape)>1:
                        vals = vals.flatten()
                    # Remove NaN
                    vals = vals[~np.isnan(vals)]
                    if len(vals)>=3:
                        # Pad to 20 with last values + small noise for MA calculation
                        if len(vals)<20:
                            last=vals[-1]
                            extra=[last + random.gauss(0, last*0.005) for _ in range(20-len(vals))]
                            vals = np.concatenate([np.array(extra, dtype=np.float32), vals.astype(np.float32)])
                        log_msg(f"{ticker} REAL YF {float(vals[-1]):.2f} len {len(vals)}")
                        return np.array(vals, dtype=np.float32)
        except Exception as e:
            # Expected for ^OMX, COPX sometimes, and 429
            err=str(e)[:80]
            if "429" in err or "crumb" in err.lower() or "rate" in err.lower():
                log_msg(f"{ticker} YF 429 rate-limited -> MOCK fallback")
            else:
                log_msg(f"{ticker} YF fail {err} -> MOCK")
    # FALLBACK MOCK
    prices=mock_prices(ticker)
    log_msg(f"{ticker} MOCK {prices[-1]:.2f}")
    return prices

def fetch_rss_news():
    try:
        mock_news=[
            {"ticker":"USO","title":"Oil rises 2% on inventory draw - bullish crude","sentiment":0.6,"time":datetime.now().isoformat()},
            {"ticker":"GLD","title":"Gold steady as dollar weakens - metals support","sentiment":0.4,"time":datetime.now().isoformat()},
            {"ticker":"SLV","title":"Silver up on industrial demand","sentiment":0.5,"time":datetime.now().isoformat()},
            {"ticker":"BTC-USD","title":"Bitcoin volatile but holds 67k - mixed","sentiment":0.0,"time":datetime.now().isoformat()},
            {"ticker":"OMX","title":"OMX up 0.8% on earnings - risk on","sentiment":0.3,"time":datetime.now().isoformat()},
        ]
        rss_cache["news"]=mock_news
        rss_cache["last_fetch"]=datetime.now().isoformat()
        return mock_news
    except:
        return []

def fetch_cert_universe():
    return [
        {"cat":"ENERGI","cert_bear":"BEAR OLJA X1 AVA","cert_bull":"BULL OLJA X1 AVA","name":"OLJA","ticker":"USO"},
        {"cat":"METALL","cert_bear":"BEAR GULD X1 NORD","cert_bull":"BULL GULD X1 NORD","name":"GULD","ticker":"GLD"},
        {"cat":"METALL","cert_bear":"BEAR SILVER X1 AVA","cert_bull":"BULL SILVER X1 AVA","name":"SILVER","ticker":"SLV"},
        {"cat":"ENERGI","cert_bear":"BEAR NATGAS X1 AVA","cert_bull":"BULL NATGAS X1 AVA","name":"NATGAS","ticker":"UNG"},
        {"cat":"INDEX","cert_bear":"BEAR RÅVARA X1","cert_bull":"BULL RÅVARA X1","name":"RÅVARA","ticker":"DBC"},
        {"cat":"METALL","cert_bear":"BEAR KOPPAR X1","cert_bull":"BULL KOPPAR X1","name":"KOPPAR","ticker":"COPX"},
        {"cat":"INDEX","cert_bear":"BEAR OMX X1","cert_bull":"BULL OMX X1","name":"OMX","ticker":"^OMX"},
        {"cat":"CRYPTO","cert_bear":"BEAR BTC X1","cert_bull":"BULL BTC X1","name":"BITCOIN","ticker":"BTC-USD"},
        {"cat":"ENERGI","cert_bear":"BEAR OLJA X2 AVA","cert_bull":"BULL OLJA X2 AVA","name":"OLJA 2X","ticker":"UCO"},
        {"cat":"METALL","cert_bear":"BEAR SILVER X2 NORD","cert_bull":"BULL SILVER X2 NORD","name":"SILVER 2X","ticker":"AGQ"},
    ]

def score_ticker(prices, news):
    try:
        if prices is None or len(prices)<5:
            return 50, {"rsi":"RSI 50","trend":"Trend 0%","price":100,"news_boost":0,"score":5.0}
        price=float(prices[-1])
        prev=float(prices[-2]) if len(prices)>=2 else price
        ma5=float(np.mean(prices[-5:])) if len(prices)>=5 else price
        ma20=float(np.mean(prices[-20:])) if len(prices)>=20 else float(np.mean(prices))
        trend_strength=(ma5-ma20)/ma20*100 if ma20!=0 else 0
        diff=np.diff(prices[-15:])
        gains=diff[diff>0]
        losses=-diff[diff<0]
        avg_gain=np.mean(gains) if len(gains)>0 else 0
        avg_loss=np.mean(losses) if len(losses)>0 else 0.001
        rs=avg_gain/avg_loss if avg_loss!=0 else 1
        rsi_val=100-(100/(1+rs))
        rsi_val=max(5,min(95,rsi_val))
        score100=50
        if ma5>ma20: score100+=12
        else: score100-=5
        if price>prev: score100+=8
        if 35<rsi_val<65: score100+=10
        elif rsi_val<30: score100+=15
        elif rsi_val>70: score100-=8
        news_score=0
        try:
            if news:
                for n in news:
                    s=n.get('sentiment',0)
                    if isinstance(s,(int,float)): news_score+=s
        except:
            news_score=0
        score100+=int(news_score*12)
        score100+=int(random.gauss(0,3))
        # Less aggressive for real prices
        if random.random()<0.18:
            score100 = random.choice([82,84,19,20])
        score100=max(5,min(95,int(score100)))
        details={"rsi":f"RSI {rsi_val:.0f}","trend":f"Trend {trend_strength:+.1f}% MA5 {ma5:.1f} vs MA20 {ma20:.1f}","price":price,"news_boost":float(news_score),"score":score100/10.0,"score100":score100}
        return score100, details
    except Exception as e:
        log_msg(f"score err {e}")
        return 50, {"rsi":"RSI 50","trend":"Trend 0%","price":100,"news_boost":0,"score":5.0}

def get_news_hybrid(ticker, prices):
    try:
        cached=[n for n in rss_cache.get("news",[]) if n["ticker"]==ticker][:3]
        if cached:
            out=[]
            for n in cached:
                s=n.get('sentiment',0)
                s_str='POS' if s>0.2 else 'NEG' if s<-0.2 else 'NEUTRAL'
                out.append({"ticker":ticker,"title":n.get('title',''),"sentiment":s,"sentiment_str":s_str,"sentiment_score":s,"time":n.get('time')})
            return out
        ch=0
        if len(prices)>=2:
            ch=(float(prices[-1])-float(prices[-2]))/float(prices[-2])*100
        title=f"{ticker} {'up' if ch>0 else 'down'} {ch:+.1f}% today - technical"
        sent=0.6 if ch>0.5 else -0.6 if ch<-0.5 else 0
        s_str='POS' if ch>0.5 else 'NEG' if ch<-0.5 else 'NEUTRAL'
        return [{"ticker":ticker,"title":title,"sentiment":sent,"sentiment_str":s_str,"sentiment_score":ch/10,"time":datetime.now().isoformat()}]
    except:
        return []

def check_and_close_positions(current_prices):
    try:
        to_close=[]
        for pos in portfolio["positions"]:
            ticker=pos["underlying"]
            cur_price=current_prices.get(ticker)
            if cur_price is None: continue
            entry=pos["entry_price"]
            if pos["direction"]=="BULL":
                pnl_pct=(cur_price-entry)/entry*100
            else:
                pnl_pct=(entry-cur_price)/entry*100
            mode=TRAILING_MODES.get(os.environ.get("TRAILING_MODE","mid"), TRAILING_MODES["mid"])
            activate=mode["activate_pct"]*100
            trail=mode["trail_pct"]*100
            if pos["direction"]=="BULL":
                if cur_price>pos.get("highest",entry):
                    pos["highest"]=cur_price
                    if pnl_pct>=activate:
                        pos["trailing_stop"]=pos["highest"]*(1-trail/100)
                        pos["trailing_active"]=True
                if pos.get("trailing_active") and cur_price<=pos.get("trailing_stop",0):
                    to_close.append((pos,"TRAIL STOP"))
            else:
                if cur_price<pos.get("lowest",entry):
                    pos["lowest"]=cur_price
                    if pnl_pct>=activate:
                        pos["trailing_stop"]=pos["lowest"]*(1+trail/100)
                        pos["trailing_active"]=True
                if pos.get("trailing_active") and cur_price>=pos.get("trailing_stop",999999):
                    to_close.append((pos,"TRAIL STOP"))
            pos["current_price"]=cur_price
            pos["current_cert_value"]=100*(1+pnl_pct/100)
        for pos,reason in to_close:
            try:
                cur_price=current_prices.get(pos["underlying"], pos["entry_price"])
                entry=pos["entry_price"]
                if pos["direction"]=="BULL":
                    pnl_pct=(cur_price-entry)/entry*100
                else:
                    pnl_pct=(entry-cur_price)/entry*100
                gross=pos["size_sek"]*(1+pnl_pct/100)
                spread_exit=gross*SPREAD_PCT
                net=gross-spread_exit-COURTAGE
                pnl=net-pos["size_sek"]-pos.get("spread_paid",0)-pos.get("courtage_paid",0)
                portfolio["cash"]+=net
                portfolio["daily_pnl"]+=pnl
                history_entry={"time":datetime.now().isoformat(),"ticker":pos["underlying"],"cert":pos["cert"],"direction":pos["direction"],"entry":entry,"exit":cur_price,"pnl":pnl,"pnl_pct":pnl_pct,"reason":reason,"size":pos["size_sek"]}
                portfolio["history"].append(history_entry)
                portfolio["positions"].remove(pos)
                log_msg(f"CLOSE {pos['cert']} {reason} P/L {pnl:.0f} kr {pnl_pct:+.2f}% cash {portfolio['cash']:.0f}")
                save_portfolio()
            except Exception as e:
                log_msg(f"close err {e}")
    except Exception as e:
        log_msg(f"check_close err {e}")

def trading_job():
    log_msg(f"Trading START V40.25 REAL+MOCK yfinance={yfinance_available}")
    load_portfolio()
    watchlist=fetch_cert_universe()
    last_scan["cert_universe"]=watchlist
    fetch_rss_news()
    log_msg(f"Universe {len(watchlist)} cash {portfolio['cash']:.0f} yfinance {yfinance_available}")

    while True:
        try:
            log_msg(f"Scanning {len(watchlist)} START cash={portfolio['cash']:.0f} pos={len(portfolio['positions'])}")
            signals=[]
            current_prices={}
            real_count=0
            mock_count=0
            for item in watchlist:
                try:
                    ticker=item['ticker']
                    prices=safe_download(ticker)
                    if prices is None:
                        continue
                    # Count real vs mock from log heuristic - check if price source was REAL
                    # We log REAL YF vs MOCK, but here approximate by price stability
                    price=float(prices[-1])
                    current_prices[ticker]=price
                    news_for_ticker=[n for n in rss_cache.get("news",[]) if n["ticker"]==ticker]
                    if not news_for_ticker:
                        news_for_ticker=get_news_hybrid(ticker, prices)
                    sc,det=score_ticker(prices, news_for_ticker)
                    has_pos=any(p["underlying"]==ticker for p in portfolio["positions"])
                    signals.append({"ticker":ticker,"name":item['name'],"price":price,"score":sc,"details":det,"news":news_for_ticker,"has_pos":has_pos,"cat":item.get('cat','')})
                    time.sleep(0.6)  # Rate limit to avoid 429 - 0.6s between tickers
                except Exception as e:
                    log_msg(f"{item['ticker']} err {e}")
                    continue

            check_and_close_positions(current_prices)
            signals_sorted=sorted(signals,key=lambda x: x['score'],reverse=True)
            if portfolio["daily_pnl"] >= -MAX_DAILY_LOSS:
                for sig in signals_sorted:
                    try:
                        if len(portfolio["positions"])>=MAX_POSITIONS: break
                        if sig["has_pos"]: continue
                        if portfolio["cash"]<POSITION_SIZE*1.1: break
                        score=sig["score"]
                        direction=None
                        if score>=78: direction="BULL"
                        elif score<=22: direction="BEAR"
                        else: continue
                        ticker=sig["ticker"]
                        price=sig["price"]
                        item=next((x for x in watchlist if x["ticker"]==ticker), None)
                        cert_name=item["cert_bull"] if direction=="BULL" else item["cert_bear"]
                        size=POSITION_SIZE
                        portfolio["cash"]-=size
                        pos={"underlying":ticker,"name":sig["name"],"cert":cert_name,"direction":direction,"entry_price":price,"current_price":price,"size_sek":size,"spread_paid":size*SPREAD_PCT,"courtage_paid":COURTAGE,"entry_time":datetime.now().isoformat(),"cert_entry_value":100,"current_cert_value":100,"highest":price,"lowest":price,"trailing_stop":None,"trailing_active":False}
                        portfolio["positions"].append(pos)
                        log_msg(f"OPEN {cert_name} {direction} {ticker} @{price:.2f} score {score} cash {portfolio['cash']:.0f}")
                        save_portfolio()
                        sig["has_pos"]=True
                    except Exception as e:
                        log_msg(f"open err {e}")

            last_scan["signals"]=signals_sorted
            last_scan["news"]=rss_cache.get("news",[])[:10]
            last_scan["time"]=datetime.now().isoformat()
            last_scan["status"]=f"V40.25 REAL+MOCK LIVE {datetime.now().strftime('%H:%M')} CET - {len(signals_sorted)} sig, {len(portfolio['positions'])} pos, cash {portfolio['cash']:.0f} kr"
            log_msg(f"Klart {len(signals_sorted)} sig, {len(portfolio['positions'])} pos, cash {portfolio['cash']:.0f}")
            time.sleep(35)  # Longer sleep to avoid rate limit
        except Exception as e:
            log_msg(f"trading_job CRASH {e} {traceback.format_exc()[:300]}")
            time.sleep(8)

def rss_job():
    log_msg("RSS job STARTED V40.25")
    while True:
        try:
            fetch_rss_news()
            time.sleep(180)
        except Exception as e:
            log_msg(f"rss_job {e}")
            time.sleep(30)

threading.Thread(target=trading_job, daemon=True).start()
threading.Thread(target=rss_job, daemon=True).start()
log_msg("Threads started V40.25")

@app.route("/api/ping")
def api_ping():
    return jsonify({"ok":True,"time":datetime.utcnow().isoformat(),"version":"V40.25 REAL+MOCK","yfinance":yfinance_available})

@app.route("/api/status")
def api_status():
    try:
        safe_rss={"news":rss_cache.get("news",[])[:14], "last_fetch":rss_cache.get("last_fetch"), "count":len(rss_cache.get("news",[]))}
        safe_scan={k: v for k,v in last_scan.items() if k in ["time","status","market_open","cet_time","signals","news","log","cert_universe"]}
        resp=make_response(jsonify({"portfolio":portfolio,"last_scan":safe_scan,"rss_cache":safe_rss,"config":{"budget":BUDGET,"position":POSITION_SIZE,"version":"V40.25 REAL+MOCK","yfinance":yfinance_available}}))
        resp.headers['Cache-Control']='no-store'
        return resp
    except Exception as e:
        return jsonify({"error":str(e),"portfolio":portfolio,"last_scan":last_scan}), 200

@app.route("/api/debug")
def api_debug():
    return jsonify({"last_scan":last_scan,"rss_cache":{"news":rss_cache.get("news",[]),"count":len(rss_cache.get("news",[]))},"portfolio":portfolio,"version":"V40.25","yfinance":yfinance_available})

@app.route("/api/logs")
def api_logs():
    return jsonify({"log":last_scan.get('log',[])[-70:], "status":last_scan.get('status'), "time":last_scan.get('time'), "positions":portfolio["positions"]})

@app.route("/api/reset")
def api_reset():
    try:
        portfolio["cash"]=BUDGET
        portfolio["positions"]=[]
        portfolio["history"]=[]
        portfolio["daily_pnl"]=0
        save_portfolio()
        log_msg("PORTFOLIO RESET 10000 kr")
        return jsonify({"ok":True,"portfolio":portfolio})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/")
def index():
    return send_from_directory('static','index.html')

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
