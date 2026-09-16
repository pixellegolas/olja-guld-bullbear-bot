import os, time, json, threading, traceback
from datetime import datetime
from flask import Flask, jsonify, make_response, send_from_directory
import pandas as pd
import numpy as np

print("V40.20 FINAL MOCK ONLY - GUARANTEED 10 SIGNALS", flush=True)

app = Flask(__name__, static_folder='static')

BUDGET=10000.0
POSITION_SIZE=1500
TRAILING_MODES={"low":{"activate_pct":0.022,"trail_pct":0.009,"label":"Låg"},"mid":{"activate_pct":0.035,"trail_pct":0.014,"label":"Mellan"},"high":{"activate_pct":0.05,"trail_pct":0.02,"label":"Hög"}}

portfolio={"cash":BUDGET,"positions":[],"history":[],"daily_pnl":0,"last_reset":datetime.now().isoformat()}
last_scan={"time":datetime.now().isoformat(),"status":"V40.20 INIT - mock only guaranteed","signals":[],"news":[],"log":[],"market_open":True,"cet_time":datetime.now().isoformat(),"cert_universe":[]}
rss_cache={"news":[],"last_fetch":None,"hashes":set()}

def log_msg(msg):
    try:
        ts=datetime.now().strftime("%H:%M:%S")
        entry=f"{ts} {msg}"
        print(entry, flush=True)
        last_scan["log"].append(entry)
        if len(last_scan["log"])>300:
            last_scan["log"]=last_scan["log"][-300:]
    except:
        print(f"log fail {msg}", flush=True)

def safe_download(ticker, period='1mo'):
    # ABSOLUTELY NO NETWORK, NO THREADING, ONLY MOCK
    try:
        bm={"USO":76.12,"GLD":2654.50,"SLV":31.20,"UNG":13.10,"DBC":26.40,"COPX":42.30,"UCO":34.50,"AGQ":31.80,"BTC-USD":67420,"BTCUSD":67420,"^OMX":2412,"OMX":2412,"BTC":67420}
        base=bm.get(ticker, bm.get(ticker.upper().replace("-USD",""), 100))
        # Make price slightly different each scan
        import random
        base = base * (0.98 + random.random()*0.04)
        dates=pd.date_range(end=pd.Timestamp.now(), periods=30, freq='D')
        prices=[]
        p=base
        for i in range(30):
            p+=float(np.random.randn()*base*0.006)
            prices.append(max(1,p))
        df=pd.DataFrame({'Close':prices,'Open':[x*0.999 for x in prices],'High':[x*1.01 for x in prices],'Low':[x*0.99 for x in prices],'Volume':[1200000]*30}, index=dates)
        log_msg(f"{ticker} MOCK {float(df['Close'].iloc[-1]):.2f}")
        return df
    except Exception as e:
        log_msg(f"{ticker} MOCK CRITICAL FAIL {e} {traceback.format_exc()[:200]}")
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
        log_msg(f"RSS MOCK {len(mock_news)} headlines")
        return mock_news
    except Exception as e:
        log_msg(f"RSS fail {e}")
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
        if df is None or len(df)<3:
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
            log_msg(f"score inner {ee}")

        score100=50
        if ma5>ma20: score100+=12
        else: score100-=5
        if price>prev: score100+=8
        if 35<rsi_val<65: score100+=10
        elif rsi_val<30: score100+=15
        elif rsi_val>70: score100-=8
        news_score=sum([n.get('sentiment',0) for n in news]) if news else 0
        score100+=int(news_score*12)
        score100+=int(np.random.randn()*3)
        score100=max(5,min(95,int(score100)))
        details={"rsi":f"RSI {rsi_val:.0f}","trend":f"Trend {trend_strength:+.1f}% MA5 {ma5:.1f} vs MA20 {ma20:.1f}","price":price,"news_boost":float(news_score),"score":score100/10.0,"score100":score100}
        return score100, details
    except Exception as e:
        log_msg(f"score outer {e} {traceback.format_exc()[:200]}")
        return 50, {"rsi":"RSI 50","trend":"Trend 0%","price":100,"news_boost":0,"score":5.0}

def get_news_hybrid(ticker, df):
    try:
        cached=[n for n in rss_cache.get("news",[]) if n["ticker"]==ticker][:3]
        if cached:
            out=[]
            for n in cached:
                s=n.get('sentiment',0)
                s_str=n.get('sentiment_str','POS' if s>0.2 else 'NEG' if s<-0.2 else 'NEUTRAL')
                out.append({"ticker":ticker,"title":n.get('title',''),"sentiment":s_str,"sentiment_score":s,"time":n.get('time')})
            return out
        # generate from price
        close=df['Close'] if df is not None else pd.Series([100,101])
        if isinstance(close, pd.DataFrame):
            close=close.iloc[:,0]
        ch=0
        if len(close)>=2:
            ch=(float(close.iloc[-1])-float(close.iloc[-2]))/float(close.iloc[-2])*100
        title=f"{ticker} {'up' if ch>0 else 'down'} {ch:+.1f}% today - technical"
        sent='POS' if ch>0.5 else 'NEG' if ch<-0.5 else 'NEUTRAL'
        return [{"ticker":ticker,"title":title,"sentiment":sent,"sentiment_score":ch/10,"time":datetime.now().isoformat()}]
    except Exception as e:
        log_msg(f"get_news_hybrid {e}")
        return []

def trading_job():
    log_msg("Trading job STARTED V40.20 FINAL MOCK ONLY")
    watchlist=fetch_cert_universe()
    last_scan["cert_universe"]=watchlist
    log_msg(f"Cert universe: {len(watchlist)} instrument")
    fetch_rss_news()
    while True:
        try:
            log_msg(f"Scanning {len(watchlist)} instrument... START")
            signals=[]
            rss_cached=rss_cache.get("news",[])[:20]
            for idx, item in enumerate(watchlist):
                try:
                    ticker=item['ticker']
                    log_msg(f"-> {idx+1}/{len(watchlist)} {ticker} downloading...")
                    df=safe_download(ticker)
                    if df is None:
                        log_msg(f"{ticker} no df - emergency")
                        df=pd.DataFrame({'Close':[100.0,101.0]}, index=pd.date_range(end=pd.Timestamp.now(), periods=2, freq='D'))
                    news_for_ticker=[n for n in rss_cached if n['ticker']==ticker]
                    if not news_for_ticker:
                        news_for_ticker=get_news_hybrid(ticker, df)
                    sc,det=score_ticker(df, news_for_ticker)
                    price_val=det.get("price",100)
                    signals.append({"ticker":ticker,"name":item['name'],"price":float(price_val),"score":int(sc),"details":det,"news":news_for_ticker,"has_pos":False,"cat":item.get('cat','')})
                    log_msg(f"{ticker} scored {sc} price {price_val:.2f}")
                except Exception as e:
                    log_msg(f"{item['ticker']} CRASH in loop {e} {traceback.format_exc()[:300]}")
                    try:
                        signals.append({"ticker":item['ticker'],"name":item['name'],"price":100,"score":50,"details":{"rsi":"RSI 50","trend":"Trend 0%","price":100,"news_boost":0,"score":5.0},"news":[],"has_pos":False,"cat":item.get('cat','')})
                    except:
                        pass
                    continue
            signals_sorted=sorted(signals,key=lambda x: x['score'],reverse=True)
            last_scan["signals"]=signals_sorted
            last_scan["news"]=rss_cache.get("news",[])[:10]
            last_scan["time"]=datetime.now().isoformat()
            last_scan["status"]=f"V40.20 FINAL MOCK LIVE {datetime.now().strftime('%H:%M')} CET - {len(signals_sorted)} signaler, {len(rss_cache.get('news',[]))} nyheter"
            log_msg(f"Scanning klart {len(signals_sorted)} signaler - STATUS UPDATED")
            time.sleep(30)
        except Exception as e:
            log_msg(f"trading_job OUTER CRASH {e} {traceback.format_exc()[:500]}")
            try:
                if len(last_scan.get("signals",[]))==0:
                    last_scan["signals"]=[{"ticker":"USO","name":"OLJA","price":76.12,"score":65,"details":{"rsi":"RSI 55","trend":"Trend +1.2%","price":76.12,"news_boost":0.6,"score":6.5},"news":[],"has_pos":False,"cat":"ENERGI"}]
                    last_scan["status"]=f"V40.20 EMERGENCY {datetime.now().strftime('%H:%M')} - after crash"
            except:
                pass
            time.sleep(5)

def rss_job():
    log_msg("RSS job STARTED V40.20")
    while True:
        try:
            fetch_rss_news()
            time.sleep(120)
        except Exception as e:
            log_msg(f"rss_job {e}")
            time.sleep(30)

threading.Thread(target=trading_job, daemon=True).start()
threading.Thread(target=rss_job, daemon=True).start()
log_msg("Threads started V40.20")

@app.route("/api/ping")
def api_ping():
    return jsonify({"ok":True,"time":datetime.utcnow().isoformat(),"version":"V40.20 FINAL MOCK"})

@app.route("/api/status")
def api_status():
    try:
        safe_rss={"news":rss_cache.get("news",[])[:14], "last_fetch":rss_cache.get("last_fetch"), "count":len(rss_cache.get("news",[]))}
        safe_scan={k: v for k,v in last_scan.items() if k in ["time","status","market_open","cet_time","signals","news","log","cert_universe"]}
        resp=make_response(jsonify({"portfolio":{"cash":BUDGET,"positions":[],"history":[],"daily_pnl":0},"last_scan":safe_scan,"rss_cache":safe_rss,"config":{"budget":BUDGET,"position":POSITION_SIZE,"trailing_modes":TRAILING_MODES,"version":"V40.20 FINAL MOCK"}}))
        resp.headers['Cache-Control']='no-store'
        return resp
    except Exception as e:
        return jsonify({"error":str(e),"last_scan":last_scan}), 200

@app.route("/api/debug")
def api_debug():
    try:
        return jsonify({"last_scan":last_scan,"rss_cache":{"news":rss_cache.get("news",[]),"count":len(rss_cache.get("news",[]))},"version":"V40.20"})
    except Exception as e:
        return jsonify({"error":str(e)}), 200

@app.route("/api/logs")
def api_logs():
    return jsonify({"log":last_scan.get('log',[])[-50:], "status":last_scan.get('status'), "time":last_scan.get('time'), "signals_count":len(last_scan.get('signals',[]))})

@app.route("/")
def index():
    return send_from_directory('static','index.html')

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
