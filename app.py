import os, time, json, threading, traceback, random
from datetime import datetime
from flask import Flask, jsonify, make_response, send_from_directory
import pandas as pd
import numpy as np

print("V40.23 TRADE ENABLED - MOCK PRICES + REAL TRADING", flush=True)

app = Flask(__name__, static_folder='static')

BUDGET=10000.0
POSITION_SIZE=1500
MAX_POSITIONS=4
SPREAD_PCT=0.02
COURTAGE=1
MAX_DAILY_LOSS=500
TRAILING_MODES={"low":{"activate_pct":0.022,"trail_pct":0.009,"label":"Låg +2.2% → -0.9%"},"mid":{"activate_pct":0.035,"trail_pct":0.014,"label":"Mellan +3.5% → -1.4%"},"high":{"activate_pct":0.05,"trail_pct":0.02,"label":"Hög +5% → -2%"}}

portfolio={"cash":BUDGET,"positions":[],"history":[],"daily_pnl":0,"last_reset":datetime.now().isoformat()}
last_scan={"time":datetime.now().isoformat(),"status":"V40.23 INIT - trade enabled","signals":[],"news":[],"log":[],"market_open":True,"cet_time":datetime.now().isoformat(),"cert_universe":[]}
rss_cache={"news":[],"last_fetch":None,"hashes":set()}

def log_msg(msg):
    try:
        ts=datetime.now().strftime("%H:%M:%S")
        entry=f"{ts} {msg}"
        print(entry, flush=True)
        last_scan["log"].append(entry)
        if len(last_scan["log"])>400:
            last_scan["log"]=last_scan["log"][-400:]
    except:
        print(f"log fail {msg}", flush=True)

def is_market_open():
    # For testing, always open, but log real CET
    try:
        from datetime import timezone
        import time as tm
        # Simple: always open for V40.23 test, change to real hours later
        now=datetime.now()
        # Real market check would be 08:55-17:30 CET
        # For now allow 00-23 to test trading
        return True, now
    except:
        return True, datetime.now()

def load_portfolio():
    try:
        if os.path.exists("portfolio.json"):
            with open("portfolio.json","r") as f:
                data=json.load(f)
                # Only load if cash exists
                if "cash" in data:
                    portfolio.update(data)
                    log_msg(f"Portfolio loaded cash {portfolio['cash']:.0f} pos {len(portfolio['positions'])} hist {len(portfolio['history'])}")
    except Exception as e:
        log_msg(f"load_portfolio fail {e}")

def save_portfolio():
    try:
        with open("portfolio.json","w") as fh:
            json.dump(portfolio, fh)
    except Exception as e:
        log_msg(f"save_portfolio fail {e}")

def safe_download(ticker, period='1mo'):
    try:
        bm={"USO":76.12,"GLD":2654.50,"SLV":31.20,"UNG":13.10,"DBC":26.40,"COPX":42.30,"UCO":34.50,"AGQ":31.80,"BTC-USD":67420,"BTCUSD":67420,"^OMX":2412,"OMX":2412}
        base=bm.get(ticker, bm.get(ticker.upper().replace("-USD",""), 100))
        base = base * (0.96 + random.random()*0.08)
        dates=pd.date_range(end=pd.Timestamp.now(), periods=40, freq='D')
        prices=[]
        p=base
        for i in range(40):
            p+=float(np.random.randn()*base*0.007)
            prices.append(max(1,p))
        df=pd.DataFrame({'Close':prices,'Open':[x*0.999 for x in prices],'High':[x*1.01 for x in prices],'Low':[x*0.99 for x in prices],'Volume':[1200000]*40}, index=dates)
        log_msg(f"{ticker} MOCK {float(df['Close'].iloc[-1]):.2f}")
        return df
    except Exception as e:
        log_msg(f"{ticker} MOCK FAIL {e}")
        try:
            dates=pd.date_range(end=pd.Timestamp.now(), periods=5, freq='D')
            df=pd.DataFrame({'Close':[100.0,101.0,100.5,101.2,100.8]}, index=dates)
            return df
        except:
            return None

def fetch_rss_news():
    try:
        mock_news=[
            {"ticker":"USO","title":"Oil rises 2% on inventory draw - bullish crude","sentiment":0.6,"sentiment_str":"POS","time":datetime.now().isoformat()},
            {"ticker":"GLD","title":"Gold steady as dollar weakens - metals support","sentiment":0.4,"sentiment_str":"POS","time":datetime.now().isoformat()},
            {"ticker":"SLV","title":"Silver up on industrial demand","sentiment":0.5,"sentiment_str":"POS","time":datetime.now().isoformat()},
            {"ticker":"BTC-USD","title":"Bitcoin volatile but holds 67k - mixed","sentiment":0.0,"sentiment_str":"NEUTRAL","time":datetime.now().isoformat()},
            {"ticker":"OMX","title":"OMX up 0.8% on earnings - risk on","sentiment":0.3,"sentiment_str":"POS","time":datetime.now().isoformat()},
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

def score_ticker(df, news):
    try:
        if df is None or len(df)<5:
            return 50, {"rsi":"RSI 50","trend":"Trend 0%","price":100,"news_boost":0,"score":5.0}
        close=df['Close']
        if isinstance(close, pd.DataFrame):
            close=close.iloc[:,0]
        close=pd.Series(close)
        rsi_val=50
        ma20=100
        ma5=100
        price=100
        prev=100
        trend_strength=0
        try:
            if len(close)>=14:
                delta=close.diff()
                gain=delta.where(delta>0,0).rolling(14).mean()
                loss=(-delta.where(delta<0,0)).rolling(14).mean()
                rs=gain/loss
                rsi=100-(100/(1+rs))
                rv=rsi.iloc[-1]
                if not pd.isna(rv):
                    rsi_val=float(rv)
            ma20=float(close.rolling(min(20,len(close))).mean().iloc[-1])
            ma5=float(close.rolling(min(5,len(close))).mean().iloc[-1])
            price=float(close.iloc[-1])
            prev=float(close.iloc[-2]) if len(close)>=2 else price
            if ma20!=0:
                trend_strength=(ma5-ma20)/ma20*100
        except Exception as ee:
            pass

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
                    elif isinstance(s,str):
                        if s.upper()=='POS': news_score+=0.6
                        elif s.upper()=='NEG': news_score+=-0.6
        except:
            news_score=0
        score100+=int(news_score*12)
        score100+=int(np.random.randn()*5)
        # Make more extreme for testing trades - push some over 78 and under 22
        if random.random()<0.25:
            score100 = random.choice([82,84,85,18,19,20])
        score100=max(5,min(95,int(score100)))
        details={"rsi":f"RSI {rsi_val:.0f}","trend":f"Trend {trend_strength:+.1f}% MA5 {ma5:.1f} vs MA20 {ma20:.1f}","price":price,"news_boost":float(news_score),"score":score100/10.0,"score100":score100}
        return score100, details
    except Exception as e:
        log_msg(f"score outer {e}")
        return 50, {"rsi":"RSI 50","trend":"Trend 0%","price":100,"news_boost":0,"score":5.0}

def get_news_hybrid(ticker, df):
    try:
        cached=[n for n in rss_cache.get("news",[]) if n["ticker"]==ticker][:3]
        if cached:
            out=[]
            for n in cached:
                s=n.get('sentiment',0)
                s_str=n.get('sentiment_str','POS' if s>0.2 else 'NEG' if s<-0.2 else 'NEUTRAL')
                out.append({"ticker":ticker,"title":n.get('title',''),"sentiment":s,"sentiment_str":s_str,"sentiment_score":s,"time":n.get('time')})
            return out
        close=df['Close'] if df is not None else pd.Series([100,101])
        if isinstance(close, pd.DataFrame):
            close=close.iloc[:,0]
        ch=0
        if len(close)>=2:
            ch=(float(close.iloc[-1])-float(close.iloc[-2]))/float(close.iloc[-2])*100
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
            if cur_price is None:
                continue
            entry=pos["entry_price"]
            # P/L %
            if pos["direction"]=="BULL":
                pnl_pct=(cur_price-entry)/entry*100
            else:
                pnl_pct=(entry-cur_price)/entry*100

            # Trailing stop logic
            mode=TRAILING_MODES.get(os.environ.get("TRAILING_MODE","mid"), TRAILING_MODES["mid"])
            activate=mode["activate_pct"]*100
            trail=mode["trail_pct"]*100

            # Update highest/lowest
            if pos["direction"]=="BULL":
                if cur_price>pos.get("highest",entry):
                    pos["highest"]=cur_price
                    # If activated, update trailing stop
                    if pnl_pct>=activate:
                        pos["trailing_stop"]=pos["highest"]*(1-trail/100)
                        pos["trailing_active"]=True
                # Check stop
                if pos.get("trailing_active") and cur_price<=pos.get("trailing_stop",0):
                    to_close.append((pos,"TRAIL STOP"))
            else: # BEAR
                if cur_price<pos.get("lowest",entry):
                    pos["lowest"]=cur_price
                    if pnl_pct>=activate:
                        pos["trailing_stop"]=pos["lowest"]*(1+trail/100)
                        pos["trailing_active"]=True
                if pos.get("trailing_active") and cur_price>=pos.get("trailing_stop",999999):
                    to_close.append((pos,"TRAIL STOP"))

            pos["current_price"]=cur_price
            pos["current_cert_value"]=100*(1+pnl_pct/100)  # mock cert value

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
                log_msg(f"close error {e} {traceback.format_exc()[:200]}")
    except Exception as e:
        log_msg(f"check_close error {e}")

def trading_job():
    log_msg("Trading job STARTED V40.23 TRADE ENABLED")
    load_portfolio()
    watchlist=fetch_cert_universe()
    last_scan["cert_universe"]=watchlist
    fetch_rss_news()
    log_msg(f"Cert universe {len(watchlist)} cash {portfolio['cash']:.0f}")

    while True:
        try:
            is_open,cet=is_market_open()
            # For V40.23 test, allow trading 24h, but log market status
            last_scan["market_open"]=is_open
            last_scan["cet_time"]=cet.isoformat()

            log_msg(f"Scanning {len(watchlist)} START market_open={is_open} cash={portfolio['cash']:.0f} pos={len(portfolio['positions'])}")

            signals=[]
            current_prices={}
            rss_cached=rss_cache.get("news",[])[:20]

            for idx, item in enumerate(watchlist):
                try:
                    ticker=item['ticker']
                    df=safe_download(ticker)
                    if df is None:
                        continue
                    price=float(df['Close'].iloc[-1])
                    current_prices[ticker]=price
                    news_for_ticker=[n for n in rss_cached if n['ticker']==ticker]
                    if not news_for_ticker:
                        news_for_ticker=get_news_hybrid(ticker, df)
                    sc,det=score_ticker(df, news_for_ticker)
                    has_pos=any(p["underlying"]==ticker for p in portfolio["positions"])
                    signals.append({"ticker":ticker,"name":item['name'],"price":price,"score":sc,"details":det,"news":news_for_ticker,"has_pos":has_pos,"cat":item.get('cat','')})
                except Exception as e:
                    log_msg(f"{item['ticker']} loop error {e}")
                    continue

            # Check closes first
            check_and_close_positions(current_prices)

            # Try opens
            signals_sorted=sorted(signals,key=lambda x: x['score'],reverse=True)
            daily_loss=portfolio["daily_pnl"]
            if daily_loss < -MAX_DAILY_LOSS:
                log_msg(f"Daily loss limit {daily_loss:.0f} < -{MAX_DAILY_LOSS} - no new trades today")
            else:
                for sig in signals_sorted:
                    try:
                        if len(portfolio["positions"])>=MAX_POSITIONS:
                            break
                        if sig["has_pos"]:
                            continue
                        if portfolio["cash"]<POSITION_SIZE*1.1:
                            log_msg(f"Not enough cash {portfolio['cash']:.0f} < {POSITION_SIZE}")
                            break
                        score=sig["score"]
                        direction=None
                        if score>=78: direction="BULL"
                        elif score<=22: direction="BEAR"
                        else: continue

                        # Open
                        ticker=sig["ticker"]
                        price=sig["price"]
                        item=next((x for x in watchlist if x["ticker"]==ticker), None)
                        cert_name=item["cert_bull"] if direction=="BULL" else item["cert_bear"]
                        size=POSITION_SIZE
                        spread_paid=size*SPREAD_PCT
                        courtage_paid=COURTAGE
                        # Deduct
                        portfolio["cash"]-=size

                        pos={
                            "underlying":ticker,
                            "name":sig["name"],
                            "cert":cert_name,
                            "direction":direction,
                            "entry_price":price,
                            "current_price":price,
                            "size_sek":size,
                            "spread_paid":spread_paid,
                            "courtage_paid":courtage_paid,
                            "entry_time":datetime.now().isoformat(),
                            "cert_entry_value":100,
                            "current_cert_value":100,
                            "highest":price if direction=="BULL" else price,
                            "lowest":price if direction=="BEAR" else price,
                            "trailing_stop":None,
                            "trailing_active":False
                        }
                        portfolio["positions"].append(pos)
                        log_msg(f"OPEN {cert_name} {direction} {ticker} @{price:.2f} score {score} cash left {portfolio['cash']:.0f}")
                        save_portfolio()
                        # Mark has_pos
                        sig["has_pos"]=True
                    except Exception as e:
                        log_msg(f"open error {e}")

            last_scan["signals"]=signals_sorted
            last_scan["news"]=rss_cache.get("news",[])[:10]
            last_scan["time"]=datetime.now().isoformat()
            last_scan["status"]=f"V40.23 TRADE LIVE {datetime.now().strftime('%H:%M')} CET - {len(signals_sorted)} signaler, {len(portfolio['positions'])} pos, cash {portfolio['cash']:.0f} kr, daily {portfolio['daily_pnl']:+.0f} kr"

            log_msg(f"Scanning klart {len(signals_sorted)} signaler, {len(portfolio['positions'])} pos, cash {portfolio['cash']:.0f}")

            time.sleep(20)
        except Exception as e:
            log_msg(f"trading_job OUTER CRASH {e} {traceback.format_exc()[:500]}")
            time.sleep(5)

def rss_job():
    log_msg("RSS job STARTED V40.23")
    while True:
        try:
            fetch_rss_news()
            time.sleep(90)
        except Exception as e:
            log_msg(f"rss_job {e}")
            time.sleep(30)

threading.Thread(target=trading_job, daemon=True).start()
threading.Thread(target=rss_job, daemon=True).start()
log_msg("Threads started V40.23")

@app.route("/api/ping")
def api_ping():
    return jsonify({"ok":True,"time":datetime.utcnow().isoformat(),"version":"V40.23 TRADE ENABLED"})

@app.route("/api/status")
def api_status():
    try:
        safe_rss={"news":rss_cache.get("news",[])[:14], "last_fetch":rss_cache.get("last_fetch"), "count":len(rss_cache.get("news",[]))}
        safe_scan={k: v for k,v in last_scan.items() if k in ["time","status","market_open","cet_time","signals","news","log","cert_universe"]}
        resp=make_response(jsonify({"portfolio":portfolio,"last_scan":safe_scan,"rss_cache":safe_rss,"config":{"budget":BUDGET,"position":POSITION_SIZE,"max_daily":MAX_DAILY_LOSS,"spread":SPREAD_PCT,"trailing_modes":TRAILING_MODES,"hours":"08:55-17:30 CET (TEST 24h in V40.23)","version":"V40.23 TRADE ENABLED"}}))
        resp.headers['Cache-Control']='no-store'
        return resp
    except Exception as e:
        return jsonify({"error":str(e),"portfolio":portfolio,"last_scan":last_scan}), 200

@app.route("/api/debug")
def api_debug():
    try:
        return jsonify({"last_scan":last_scan,"rss_cache":{"news":rss_cache.get("news",[]),"count":len(rss_cache.get("news",[]))},"portfolio":portfolio,"version":"V40.23"})
    except Exception as e:
        return jsonify({"error":str(e)}), 200

@app.route("/api/logs")
def api_logs():
    return jsonify({"log":last_scan.get('log',[])[-80:], "status":last_scan.get('status'), "time":last_scan.get('time'), "signals_count":len(last_scan.get('signals',[])), "positions":portfolio["positions"]})

@app.route("/api/reset")
def api_reset():
    try:
        portfolio["cash"]=BUDGET
        portfolio["positions"]=[]
        portfolio["history"]=[]
        portfolio["daily_pnl"]=0
        save_portfolio()
        log_msg("PORTFOLIO RESET to 10000 kr")
        return jsonify({"ok":True,"portfolio":portfolio})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/")
def index():
    return send_from_directory('static','index.html')

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
