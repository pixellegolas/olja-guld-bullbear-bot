# Bull/Bear Bot V41 NEWS INTEL - NO TRADE

## Vad den gör
- **Ingen trading** - bara news + score accuracy
- 25 tickers: SAAB, NVIDIA, guld, olja, BTC, OMX m.fl
- 100+ headlines per scan från 8 källor
- Telegram när score >= 7.5/10 och hög accuracy

## Deploy till Render
1. Push till GitHub main branch
2. Render -> New Web Service -> Connect repo
3. Build: `pip install -r requirements.txt`
4. Start: `gunicorn app:app --config gunicorn.conf.py`
5. Env vars:
   - TELEGRAM_BOT_TOKEN (från @BotFather)
   - TELEGRAM_CHAT_ID (från getUpdates)
   - SCORE_THRESHOLD=7.5

## Testa
- /api/ping -> visar tickers, signals, news count
- /api/telegram/test -> skickar test till Telegram
- /api/status -> full status

## Tickers
USO, UCO, UNG, GLD, UGL, SLV, AGQ, COPX, DBC, BTC-USD, NVDA, TSLA, AAPL, SAAB-B.ST, VOLV-B.ST, EVO.ST, ERIC-B.ST, NIBE-B.ST, ABB.ST, ^OMX, ^GSPC, ^IXIC, URA, LMT, AMD
