#!/usr/bin/env python3
"""
🔍 XT Spot Scanner | DEBUG VERSION
Condition: Price > EMA(50) | Daily
Market Cap: 1K - 1M USD
"""
import os
import sys
import time
import ccxt
import pandas as pd
import requests
from datetime import datetime
from html import escape
from tqdm.auto import tqdm

# ================= CONFIG =================
EXCHANGE_ID = 'xt'
TELEGRAM_BOT_TOKEN = "8766406031:AAEK0GuMnw3EFD5BSGgGQ3aPYbYcKXyG59U"
TELEGRAM_CHAT_IDS = ["your_chat_id"]
CMC_API_KEY = "39478549b7c94ee093d0f3cbe43a39e9"

MIN_MARKET_CAP = 1_000
MAX_MARKET_CAP = 1_000_000
DAILY_TF = '1d'
DAILY_LIMIT = 100
EMA_PERIOD = 50

# ================= DEBUG FLAGS =================
DEBUG_MODE = True  # ✅ فعال برای دیدن همه لاگ‌ها

# ================= EXCHANGE =================
print("🔌 Initializing exchange...", flush=True)
try:
    exchange = getattr(ccxt, EXCHANGE_ID)({
        'enableRateLimit': True,
        'timeout': 30000,
        'verbose': DEBUG_MODE  # ✅ لاگ درخواست‌های API
    })
    print(f"📦 Loading markets from {EXCHANGE_ID.upper()}...", flush=True)
    exchange_markets = exchange.load_markets()
    print(f"✅ Connected! Loaded {len(exchange_markets)} markets", flush=True)
except Exception as e:
    print(f"❌ CRITICAL ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ================= GET SPOT PAIRS =================
def get_spot_pairs():
    symbol_map = {}
    print("🔍 Filtering spot pairs...", flush=True)
    
    for symbol, info in exchange_markets.items():
        if not info.get('active'):
            continue
        if info.get('quote') != 'USDT':
            continue
        is_spot = info.get('spot', False)
        if is_spot:
            base = symbol.split('/')[0].upper()
            if base not in symbol_map:
                symbol_map[base] = (symbol, info)
    
    pairs = list(symbol_map.values())
    print(f"📊 Found {len(pairs)} active spot pairs with USDT", flush=True)
    
    # ✅ نمایش 10 نمونه اول برای دیباگ
    if DEBUG_MODE and pairs:
        print("📋 Sample pairs:", flush=True)
        for i, (s, _) in enumerate(pairs[:10], 1):
            print(f"   {i}. {s}", flush=True)
    
    return pairs

# ================= FETCH DATA =================
def fetch_ohlcv(symbol, timeframe, limit):
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if len(data) < EMA_PERIOD:
            if DEBUG_MODE:
                print(f"⚠️ {symbol}: Only {len(data)} bars (need {EMA_PERIOD})", flush=True)
            return None
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Fetch error {symbol}: {e}", flush=True)
        return None

# ================= MARKET CAP =================
def get_market_cap(symbol_base):
    try:
        if not CMC_API_KEY:
            return None
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        params = {'symbol': symbol_base.upper(), 'convert': 'USD'}
        headers = {
            'X-CMC_PRO_API_KEY': CMC_API_KEY,
            'Accepts': 'application/json'
        }
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if "data" in data and symbol_base.upper() in data["data"]:
            mc = data["data"][symbol_base.upper()].get("quote", {}).get("USD", {}).get("market_cap")
            return float(mc) if mc and mc > 0 else None
        return None
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ CMC error for {symbol_base}: {e}", flush=True)
        return None

# ================= SCAN SPOT =================
def scan_spot():
    results = []
    pairs = get_spot_pairs()
    
    if not pairs:
        print("❌ NO SPOT PAIRS FOUND - Check exchange connection or USDT filter", flush=True)
        return []
    
    print(f"\n🔍 Starting scan of {len(pairs)} spot pairs...", flush=True)
    print(f"   Condition: Price > EMA{EMA_PERIOD} (Daily)", flush=True)
    print(f"   Market Cap: ${MIN_MARKET_CAP/1e3:.1f}K - ${MAX_MARKET_CAP/1e6:.1f}M", flush=True)
    print("-" * 70, flush=True)
    
    scanned = 0
    passed_ema = 0
    passed_mc = 0
    
    for symbol, info in tqdm(pairs, desc="Scanning", disable=not DEBUG_MODE):
        try:
            scanned += 1
            
            # دریافت داده‌های روزانه
            df = fetch_ohlcv(symbol, DAILY_TF, DAILY_LIMIT)
            if df is None:
                continue
            
            # محاسبه EMA50
            df['ema50'] = df['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
            last = df.iloc[-1]
            
            if pd.isna(last['close']) or pd.isna(last['ema50']):
                continue
            
            # بررسی شرط: Price > EMA50
            if not (last['close'] > last['ema50']):
                continue
            passed_ema += 1
            
            # دریافت مارکت‌کپ
            symbol_base = symbol.split('/')[0]
            market_cap = get_market_cap(symbol_base)
            
            if market_cap is None:
                if DEBUG_MODE and scanned % 50 == 0:
                    print(f"⚠️ {symbol_base}: No market cap data", flush=True)
                continue
            
            if not (MIN_MARKET_CAP <= market_cap <= MAX_MARKET_CAP):
                continue
            passed_mc += 1
            
            results.append({
                'symbol': symbol,
                'symbol_base': symbol_base,
                'price': last['close'],
                'market_cap': market_cap,
                'mkt_type': 'S'
            })
            
            if DEBUG_MODE and len(results) <= 5:
                mc_str = f"${market_cap/1e6:.2f}M" if market_cap >= 1e6 else f"${market_cap/1e3:.2f}K"
                print(f"✅ MATCH: {symbol} | Price: {last['close']:.6f} | MC: {mc_str}", flush=True)
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"❌ Error processing {symbol}: {e}", flush=True)
                import traceback
                traceback.print_exc()
        time.sleep(0.05)
    
    print(f"\n📊 Scan Summary:", flush=True)
    print(f"   ├─ Total pairs: {len(pairs)}", flush=True)
    print(f"   ├─ Scanned: {scanned}", flush=True)
    print(f"   ├─ Passed EMA50: {passed_ema}", flush=True)
    print(f"   ├─ Passed Market Cap: {passed_mc}", flush=True)
    print(f"   └─ Final results: {len(results)}", flush=True)
    
    return results

# ================= BUILD MESSAGE =================
def build_message(signals, total_scanned):
    now = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    header = (
        f"🔍 <b>XT Spot Scanner</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Scanned: <code>{total_scanned}</code> | ✅ Found: <code>{len(signals)}</code>\n"
        f"📋 Filter: Price &gt; EMA{EMA_PERIOD} (Daily)\n"
        f"💰 Market Cap: ${MIN_MARKET_CAP/1e3:.1f}K - ${MAX_MARKET_CAP/1e6:.1f}M\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    footer = f"\n⏰ {now} 🇮🇷\n🤖 XT Spot Scanner"
    
    msgs = []
    body = ""
    MAX = 4000
    
    for r, s in enumerate(signals, 1):
        tv_link = f"https://www.tradingview.com/chart/?symbol=XT:{s['symbol'].replace('/', '')}"
        if s['market_cap'] >= 1e6:
            mc_str = f"${s['market_cap']/1e6:.2f}M"
        elif s['market_cap'] >= 1e3:
            mc_str = f"${s['market_cap']/1e3:.2f}K"
        else:
            mc_str = f"${s['market_cap']:,.0f}"
        
        card = (
            f"{r}. <a href='{tv_link}'>{escape(s['symbol_base'])}</a> | "
            f"💰{s['price']:,.6f} | "
            f"🏛️{mc_str}\n"
        )
        
        if len(header) + len(body) + len(card) + len(footer) > MAX - 100:
            msgs.append(header + body + footer)
            body = card
        else:
            body += card
    
    if body.strip():
        msgs.append(header + body + footer)
    
    if not msgs:
        msgs.append(f"{header}❌ No symbols found.{footer}")
    
    return msgs

# ================= TELEGRAM =================
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN:
        return
    for cid in TELEGRAM_CHAT_IDS:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': cid,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': False
        }
        try:
            requests.post(url, json=payload, timeout=30)
        except Exception as e:
            print(f"❌ Telegram Error: {e}", flush=True)

# ================= MAIN =================
def run():
    print("🚀 Starting XT Spot Scanner (DEBUG MODE)...", flush=True)
    
    results = scan_spot()
    
    # نمایش لیست در کنسول
    if results:
        print("\n" + "="*70, flush=True)
        print(f"🎯 FOUND {len(results)} SYMBOLS:", flush=True)
        print("="*70, flush=True)
        print(f"{'#':<4} {'Symbol':<20} {'Price':<18} {'Market Cap':<15}", flush=True)
        print("-"*70, flush=True)
        for i, s in enumerate(results, 1):
            mc_str = f"${s['market_cap']/1e6:.2f}M" if s['market_cap'] >= 1e6 else f"${s['market_cap']/1e3:.2f}K"
            print(f"{i:<4} {s['symbol']:<20} {s['price']:<18,.6f} {mc_str:<15}", flush=True)
        print("="*70 + "\n", flush=True)
    else:
        print("\n❌ NO RESULTS - Possible causes:", flush=True)
        print("   • No spot pairs with USDT on XT", flush=True)
        print("   • Price <= EMA50 for all pairs", flush=True)
        print("   • Market cap filter too narrow (1K-1M)", flush=True)
        print("   • CoinMarketCap API returned no data", flush=True)
    
    # ارسال به تلگرام
    if TELEGRAM_CHAT_IDS and results:
        print("📤 Sending to Telegram...", flush=True)
        for msg in build_message(results, len(get_spot_pairs())):
            send_telegram(msg)
            time.sleep(0.3)
        print("✅ Sent to Telegram", flush=True)
    elif not results:
        print("\n⚠️ No results to send", flush=True)

if __name__ == "__main__":
    run()
