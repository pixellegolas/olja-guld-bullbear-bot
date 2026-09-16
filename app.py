import os
import time
import json
from datetime import datetime, timedelta
from flask import Flask, jsonify, make_response, send_from_directory
import pandas as pd
import numpy as np

# V40.16 LIVE REAL FIXED ULTRA MINIMAL - NO yfinance, NO feedparser at top, GUARANTEED to start on Render
print("V40.16 LIVE REAL FIXED ULTRA MINIMAL starting...", flush=True)

app = Flask(__name__, static_folder='static')

BUDGET=10000.0
POSITION_SIZE=1500
MAX_DAILY_LOSS=500
SPREAD_PCT=0.02
LEVERAGE=1
TRAILING_MODES={"low":{"activate_pct":0.022,"trail_pct":0.009,"label":"Låg +2.2% → -0.9% V40.16 LIVE REAL FIXED"},"mid":{"activate_pct":0.035,"trail_pct":0.014,"label":"Mellan +3.5% → -1.4%"},"high":{"activate_pct":0.05,"trail_pct":0.02,"label":"Hög +5% → -2%"}}

portfolio={"cash":BUDGET,"positions":[],"history":[],"daily_pnl":0,"last_reset":datetime.now().isoformat()}
last_scan={"time":datetime.now().isoformat(),"status":"V40.16 LIVE REAL FIXED ULTRA MINIMAL INIT - mock data, no network","signals":[],"news":[],"log":[],"market_open":True,"cet_time":datetime.now().isoformat(),"cert_universe":[]}
rss_cache={"news":[],"last_fetch":None,"hashes":set()}
RSS_FEEDS={"USO":["https://news.google.com/rss/search?q=oil"],"GLD":["https://news.google.com/rss/search?q=gold"]}

def log_msg(msg):
    try:
        ts=datetime.now().strftime("%H:%M:%S")
        entry=f"{ts} {msg}"
        print(entry, flush=True)
        last_scan["log"].append(entry)
        if len(last_scan["log"])>100:
            last_scan["log"]=last_scan["log"][-100:]
    except:
        pass

def is_market_open():
    # Always open for mock version
    return True, datetime.now()


# Cache for real prices
_real_price_cache={}



# Cache for real prices
_real_price_cache={}

def safe_download(ticker, period='1mo'):
    global _real_price_cache
    import time
    try:
        cached=_real_price_cache.get(ticker)
        if cached and (time.time()-cached['ts'])<600 and cached['df'] is not None:
            log_msg(f"{ticker} CACHED REAL {float(cached['df']['Close'].iloc[-1]):.2f}")
            return cached['df']
    except Exception as e:
        log_msg(f"{ticker} cache check {e}")

    def _bg_fetch():
        try:
            import requests, pandas as pd
            from io import StringIO
            sm={"USO":"uso.us","GLD":"gld.us","SLV":"slv.us","UNG":"ung.us","DBC":"dbc.us","COPX":"copx.us","UCO":"uco.us","AGQ":"agq.us","BTC-USD":"btcusd","BTCUSD":"btcusd","^OMX":"omx.st","OMX":"omx.st"}
            sym=sm.get(ticker, ticker.split("-")[0].lower()+".us")
            url=f"https://stooq.com/q/d/l/?s={sym}&i=d"
            try:
                r=requests.get(url, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
                if r.status_code==200 and "Date" in r.text and len(r.text)>200:
                    df=pd.read_csv(StringIO(r.text))
                    if len(df)>=10:
                        df['Date']=pd.to_datetime(df['Date'])
                        df=df.set_index('Date')
                        df=df.sort_index()
                        _real_price_cache[ticker]={'df':df,'ts':time.time()}
                        log_msg(f"{ticker} BG REAL STOOQ cached {len(df)} bars {float(df['Close'].iloc[-1]) if not isinstance(df['Close'], pd.DataFrame) else float(df['Close'].iloc[:,0].iloc[-1]):.2f}")
                        return
            except Exception as e:
                log_msg(f"{ticker} BG STOOQ fail {e}")

            try:
                import yfinance as yf
                df=yf.download(ticker, period="1mo", interval="1d", progress=False, timeout=10, auto_adjust=True)
                if df is not None and not df.empty and len(df)>=3:
                    # Fix MultiIndex columns from new yfinance
                    if isinstance(df.columns, pd.MultiIndex):
                        # Flatten: take Close column
                        try:
                            if 'Close' in df.columns.get_level_values(0):
                                close_df=df['Close']
                                if isinstance(close_df, pd.DataFrame):
                                    close_df=close_df.iloc[:,0]
                                df=pd.DataFrame({'Close':close_df,'Open':df['Open'].iloc[:,0] if isinstance(df['Open'], pd.DataFrame) else df['Open'],'High':df['High'].iloc[:,0] if isinstance(df['High'], pd.DataFrame) else df['High'],'Low':df['Low'].iloc[:,0] if isinstance(df['Low'], pd.DataFrame) else df['Low'],'Volume':df['Volume'].iloc[:,0] if 'Volume' in df.columns and isinstance(df['Volume'], pd.DataFrame) else df.get('Volume',0)})
                        except Exception as ee:
                            log_msg(f"{ticker} MultiIndex fix {ee}")
                            # Fallback: take first level
                            df.columns=df.columns.droplevel(1) if isinstance(df.columns, pd.MultiIndex) else df.columns
                    _real_price_cache[ticker]={'df':df,'ts':time.time()}
                    try:
                        price=float(df['Close'].iloc[-1]) if not isinstance(df['Close'], pd.DataFrame) else float(df['Close'].iloc[:,0].iloc[-1]) if not isinstance(df['Close'], pd.DataFrame) else float(df['Close'].iloc[:,0].iloc[-1])
                    except:
                        price=0
                    log_msg(f"{ticker} BG REAL YF cached {len(df)} price {price:.2f}")
            except Exception as e:
                log_msg(f"{ticker} BG YF fail {e}")
        except Exception as e:
            log_msg(f"{ticker} BG outer {e}")

    try:
        import threading
        threading.Thread(target=_bg_fetch, daemon=True).start()
    except:
        pass

    try:
        import pandas as pd
        import numpy as np
        # Return cached if exists
        cached=_real_price_cache.get(ticker)
        if cached and cached['df'] is not None:
            # Ensure simple columns
            df=cached['df']
            if isinstance(df.columns, pd.MultiIndex):
                try:
                    close_series=df['Close']
                    if isinstance(close_series, pd.DataFrame):
                        close_series=close_series.iloc[:,0]
                    df=pd.DataFrame({'Close':close_series})
                except:
                    pass
            log_msg(f"{ticker} CACHED REAL {float(df['Close'].iloc[-1]) if not isinstance(df['Close'], pd.DataFrame) else float(df['Close'].iloc[:,0].iloc[-1]):.2f} used")
            return df

        bm={"USO":76.12,"GLD":2654.50,"SLV":31.20,"UNG":13.10,"DBC":26.40,"COPX":42.30,"UCO":34.50,"AGQ":31.80,"BTC-USD":67420,"BTCUSD":67420,"^OMX":2412,"OMX":2412,"BTC":67420}
        base_price=bm.get(ticker, bm.get(ticker.upper(), 100))
        dates=pd.date_range(end=pd.Timestamp.now(), periods=30, freq='D')
        prices=[]
        p=base_price
        for i in range(30):
            p+=float(np.random.randn()*base_price*0.006)
            prices.append(p)
        df=pd.DataFrame({'Close':prices,'Open':[x*0.999 for x in prices],'High':[x*1.01 for x in prices],'Low':[x*0.99 for x in prices],'Volume':[1200000]*30}, index=dates)
        log_msg(f"{ticker} MOCK {float(df['Close'].iloc[-1]) if not isinstance(df['Close'], pd.DataFrame) else float(df['Close'].iloc[:,0].iloc[-1]):.2f} (real fetching in BG)")
        return df
    except Exception as e:
        log_msg(f"{ticker} MOCK fail {e}")
        return None


def fetch_rss_news():
    try:
        # Try real RSS
        try:
            import feedparser
            news=[]
            for tk in ["USO","GLD","SLV","UNG","BTC-USD"]:
                try:
                    url=f"https://news.google.com/rss/search?q={tk}+commodity+OR+oil+OR+gold&hl=en-US&gl=US&ceid=US:en"
                    feed=feedparser.parse(url)
                    for e in feed.entries[:2]:
                        title=getattr(e,'title','')
                        if not title: continue
                        h=hash(title)
                        if h in rss_cache["hashes"]:
                            continue
                        rss_cache["hashes"].add(h)
                        if len(rss_cache["hashes"])>400:
                            rss_cache["hashes"]=set(list(rss_cache["hashes"])[-200:])
                        lt=title.lower()
                        sent=0
                        if any(w in lt for w in ["surge","rise","jump","bull","gain","rally","up","high"]): sent=0.6
                        if any(w in lt for w in ["fall","drop","bear","loss","crash","down","low","cut"]): sent=-0.6
                        sent_str='POS' if sent>0.2 else 'NEG' if sent<-0.2 else 'NEUTRAL'
                        news.append({"ticker":tk,"title":title[:120],"sentiment":sent,"sentiment_str":sent_str,"time":datetime.now().isoformat()})
                except Exception as ee:
                    log_msg(f"RSS {tk} {ee}")
            if news:
                rss_cache["news"]=news[:20]
                rss_cache["last_fetch"]=datetime.now().isoformat()
                log_msg(f"RSS REAL {len(news)} headlines")
                return news
        except Exception as ee:
            log_msg(f"RSS real fail {ee}")

        # Mock fallback
        mock_news=[
            {"ticker":"USO","title":"Oil rises on inventory draw - bullish for crude","sentiment":0.6,"sentiment_str":"POS","time":datetime.now().isoformat()},
            {"ticker":"GLD","title":"Gold steady as dollar weakens","sentiment":0.4,"sentiment_str":"POS","time":datetime.now().isoformat()},
            {"ticker":"BTC-USD","title":"Bitcoin volatile - risk mixed","sentiment":0.0,"sentiment_str":"NEUTRAL","time":datetime.now().isoformat()},
        ]
        rss_cache["news"]=mock_news
        rss_cache["last_fetch"]=datetime.now().isoformat()
        log_msg(f"RSS MOCK {len(mock_news)}")
        return mock_news
    except Exception as e:
        log_msg(f"RSS mock fail {e}")
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
            return None, {}
        import pandas as pd
        close=df['Close']
        if isinstance(close, pd.DataFrame):
            close=close.iloc[:,0]
        if not isinstance(close, pd.Series):
            close=pd.Series(close)
        try:
            rsi_val=50
            if len(close)>=14:
                delta=close.diff()
                gain=delta.where(delta>0,0).rolling(14).mean()
                loss=(-delta.where(delta<0,0)).rolling(14).mean()
                rs=gain/loss
                rsi=100-(100/(1+rs))
                try:
                    rsi_val=float(rsi.iloc[-1])
                    if pd.isna(rsi_val): rsi_val=50
                except:
                    rsi_val=50
            ma_len20=min(20,len(close))
            ma_len5=min(5,len(close))
            ma20=float(close.rolling(ma_len20).mean().iloc[-1])
            ma5=float(close.rolling(ma_len5).mean().iloc[-1])
            price=float(close.iloc[-1])
            prev=float(close.iloc[-2]) if len(close)>=2 else price
            # trend calc
            trend_strength=(ma5-ma20)/ma20*100 if ma20!=0 else 0
        except Exception as ee:
            log_msg(f"score calc {ee}")
            try:
                price=float(close.iloc[-1])
            except:
                price=100
            ma20=price
            ma5=price
            rsi_val=50
            prev=price
            trend_strength=0

        # Score 0-100 internally
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

        # Convert to 0-10 for frontend (divide by 10)
        score10=score100/10.0

        details={
            "rsi":f"RSI {rsi_val:.0f}",
            "trend":f"Trend {trend_strength:+.1f}% MA5 {ma5:.1f} vs MA20 {ma20:.1f}",
            "price":price,
            "news":f"{len(news)} nyheter" if news else "no news",
            "news_boost":float(news_score),
            "score":score10,
            "score100":score100
        }
        return score100, details
    except Exception as e:
        log_msg(f"score error {e}")
        try:
            import pandas as pd
            close=df['Close'] if df is not None and 'Close' in df.columns else None
            if isinstance(close, pd.DataFrame):
                close=close.iloc[:,0]
            price=float(close.iloc[-1]) if close is not None and len(close)>=1 else 100
        except:
            price=100
        return 50, {"rsi":"RSI 50","trend":"Trend 0%","price":price,"news_boost":0,"score":5.0}

def get_news_hybrid(ticker, df):
    # Return cached RSS + generate sentiment news from price action if empty
    cached=[n for n in rss_cache.get("news",[]) if n["ticker"]==ticker][:3]
    if cached:
        # Convert to format expected by frontend (sentiment string + boost)
        formatted=[]
        for n in cached:
            s=n.get('sentiment',0)
            sent_str='POS' if s>0.2 else 'NEG' if s<-0.2 else 'NEUTRAL'
            formatted.append({"ticker":ticker,"title":n.get('title',''),"sentiment":sent_str,"sentiment_score":s,"time":n.get('time')})
        return formatted
    # Generate fake news from price momentum if no RSS
    try:
        if df is not None and len(df)>=2:
            close=df['Close']
            if isinstance(close, pd.DataFrame):
                close=close.iloc[:,0]
            ch=(float(close.iloc[-1])-float(close.iloc[-2]))/float(close.iloc[-2])*100
            title=f"{ticker} {'up' if ch>0 else 'down'} {ch:+.1f}% today - technical"
            sent='POS' if ch>0.5 else 'NEG' if ch<-0.5 else 'NEUTRAL'
            return [{"ticker":ticker,"title":title,"sentiment":sent,"sentiment_score":ch/10,"time":datetime.now().isoformat()}]
    except:
        pass
    return []


def get_news_hybrid(ticker, df):
    return [n for n in rss_cache.get("news",[]) if n["ticker"]==ticker][:3]

def load_portfolio():
    try:
        if os.path.exists("portfolio.json"):
            with open("portfolio.json","r") as f:
                data=json.load(f)
                portfolio.update(data)
    except:
        pass

def save_portfolio():
    try:
        with open("portfolio.json","w") as fh:
            json.dump(portfolio, fh)
    except:
        pass

def trading_job():
    global last_scan
    log_msg("Trading job STARTED V40.16 LIVE REAL FIXED ULTRA MINIMAL")
    load_portfolio()
    watchlist=fetch_cert_universe()
    last_scan["cert_universe"]=watchlist
    log_msg(f"Cert universe: {len(watchlist)} instrument (static)")
    while True:
        try:
            log_msg(f"Scanning {len(watchlist)} instrument... START")
            signals=[]
            rss_cached=rss_cache["news"][:20]
            for item in watchlist:
                try:
                    df=safe_download(item['ticker'], period='1mo')
                    if df is None: continue
                    news_for_ticker=[n for n in rss_cached if n['ticker']==item['ticker']]
                    sc,det=score_ticker(df, news_for_ticker)
                    if sc is None: continue
                    has=False
                    signals.append({"ticker":item['ticker'],"name":item['name'],"price":float(df['Close'].iloc[-1]) if not isinstance(df['Close'], pd.DataFrame) else float(df['Close'].iloc[:,0].iloc[-1]),"score":sc,"details":det,"news":news_for_ticker,"has_pos":has,"cat":item.get('cat','')})
                except Exception as e:
                    log_msg(f"{item['ticker']} error {e}")
                    continue
            signals_sorted=sorted(signals,key=lambda x:x['score'],reverse=True)
            last_scan["signals"]=signals_sorted
            last_scan["news"]=rss_cache.get("news",[])[:10]
            last_scan["time"]=datetime.now().isoformat()
            last_scan["status"]=f"V40.16 LIVE REAL FIXED SIMPLE MARKET OPEN {datetime.now().strftime('%H:%M')} CET - MOCK aktiv, {len(signals_sorted)} signaler"
            log_msg(f"Scanning klart {len(signals_sorted)} signaler")
            time.sleep(30)
        except Exception as e:
            log_msg(f"trading_job error {e}")
            time.sleep(10)

def rss_job():
    log_msg("RSS job STARTED V40.16 LIVE REAL FIXED")
    while True:
        try:
            fetch_rss_news()
            time.sleep(120)
        except Exception as e:
            log_msg(f"rss_job {e}")
            time.sleep(30)

import threading
threading.Thread(target=trading_job, daemon=True).start()
threading.Thread(target=rss_job, daemon=True).start()
log_msg("Threads started V40.16 LIVE REAL FIXED")

@app.route("/api/ping")
def api_ping():
    try:
        is_open,cet=is_market_open()
        resp=make_response(jsonify({"ok":True,"time":datetime.utcnow().isoformat(),"cet":cet.isoformat(),"market_open":is_open,"last_scan":last_scan.get('time'),"rss_count":len(rss_cache.get("news",[])),"universe":len(last_scan.get('cert_universe',[])),"version":"V40.16 LIVE REAL FIXED SIMPLE FINAL"}))
        resp.headers['Cache-Control']='no-store'
        return resp
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}), 200

@app.route("/api/status")
def api_status():
    try:
        safe_rss={"news":rss_cache.get("news",[])[:14], "last_fetch":rss_cache.get("last_fetch"), "count":len(rss_cache.get("news",[]))}
        safe_scan={k: v for k,v in last_scan.items() if k in ["time","status","market_open","cet_time","signals","news","log","cert_universe"]}
        resp=make_response(jsonify({"portfolio":portfolio,"last_scan":safe_scan,"rss_cache":safe_rss,"config":{"budget":BUDGET,"position":POSITION_SIZE,"max_daily":MAX_DAILY_LOSS,"spread":SPREAD_PCT,"trailing_modes":TRAILING_MODES,"hours":"08:55-17:30 CET","has_feedparser":False,"version":"V40.16 LIVE REAL FIXED SIMPLE FINAL"}}))
        resp.headers['Cache-Control']='no-store'
        return resp
    except Exception as e:
        return jsonify({"error":str(e),"portfolio":portfolio,"last_scan":{"status":f"Error {e}","time":datetime.now().isoformat(),"signals":[],"news":[],"log":last_scan.get('log',[])[-10:]}}), 200

@app.route("/api/logs")
def api_logs():
    try:
        safe_rss={"count":len(rss_cache.get("news",[])), "last_fetch":rss_cache.get("last_fetch")}
        return jsonify({"log":last_scan.get('log',[])[-30:], "status":last_scan.get('status'), "time":last_scan.get('time'), "rss":safe_rss, "version":"V40.16 LIVE REAL FIXED SIMPLE FINAL"})
    except Exception as e:
        return jsonify({"error":str(e),"log":last_scan.get('log',[])[-20:]}), 200

@app.route("/api/scan-now")
def api_scan_now():
    try:
        return jsonify({"time":last_scan.get('time'), "status":last_scan.get('status'), "signals":last_scan.get('signals',[])[:8], "news":last_scan.get('news',[])[:6], "version":"V40.16 LIVE REAL FIXED"})
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

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
