#!/usr/bin/env python3
"""
🔍 XT Spot Scanner
Condition: Price > EMA(50) | Daily
Market Cap: 1K - 1M USD
"""
import os
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
TELEGRAM_CHAT_IDS = ["your_chat_id"]  # آیدی تلگرامت رو اینجا بذار
CMC_API_KEY = "39478549b7c94ee093d0f3cbe43a39e9"

MIN_MARKET_CAP = 1_000      # 1K USD
MAX_MARKET_CAP = 1_000_000  # 1M USD
DAILY_TF = '1d'
DAILY_LIMIT = 100
EMA_PERIOD = 50

# ================= EXCHANGE =================
try:
    exchange = getattr(ccxt, EXCHANGE_ID)({
        'enableRateLimit': True,
        'timeout': 30000
    })
    exchange_markets = exchange.load_markets()
    print(f"✅ Connected to {EXCHANGE_ID.upper()}")
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

# ================= GET SPOT PAIRS =================
def get_spot_pairs():
    symbol_map = {}
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
    return list(symbol_map.values())

# ================= FETCH DATA =================
def fetch_ohlcv(symbol, timeframe, limit):
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if len(data) < EMA_PERIOD:
            return None
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
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
    except Exception:
        return None

# ================= SCAN SPOT =================
def scan_spot():
    results = []
    pairs = get_spot_pairs()
    print(f"\n🔍 Scanning {len(pairs)} spot pairs...")
    print(f"   Condition: Price > EMA{EMA_PERIOD} (Daily)")
    print(f"   Market Cap: ${MIN_MARKET_CAP/1e3:.1f}K - ${MAX_MARKET_CAP/1e6:.1f}M")
    print("-" * 70, flush=True)
    
    for symbol, info in tqdm(pairs, desc="Scanning"):
        try:
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
            
            # دریافت مارکت‌کپ
            symbol_base = symbol.split('/')[0]
            market_cap = get_market_cap(symbol_base)
            
            if market_cap is None or not (MIN_MARKET_CAP <= market_cap <= MAX_MARKET_CAP):
                continue
            
            results.append({
                'symbol': symbol,
                'symbol_base': symbol_base,
                'price': last['close'],
                'market_cap': market_cap,
                'mkt_type': 'S'
            })
            
        except Exception as e:
            pass
        time.sleep(0.05)
    
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
    footer = f"\n⏰ {now} 🇮\n🤖 XT Spot Scanner"
    
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
            print(f"❌ Telegram Error: {e}")

# ================= MAIN =================
def run():
    print("🚀 Starting XT Spot Scanner...", flush=True)
    results = scan_spot()
    print(f"\n✅ Found {len(results)} symbols", flush=True)
    
    # 🎯 نمایش لیست کامل ارزها در کنسول GitHub
    if results:
        print("\n" + "="*80, flush=True)
        print(f"🎯 FOUND {len(results)} SYMBOLS - COMPLETE LIST:", flush=True)
        print("="*80, flush=True)
        print(f"{'#':<4} {'Symbol':<20} {'Price':<18} {'Market Cap':<15}", flush=True)
        print("-"*80, flush=True)
        
        for i, s in enumerate(results, 1):
            # فرمت مارکت‌کپ
            if s['market_cap'] >= 1e6:
                mc_str = f"${s['market_cap']/1e6:.2f}M"
            elif s['market_cap'] >= 1e3:
                mc_str = f"${s['market_cap']/1e3:.2f}K"
            else:
                mc_str = f"${s['market_cap']:,.0f}"
            
            print(f"{i:<4} {s['symbol']:<20} {s['price']:<18,.6f} {mc_str:<15}", flush=True)
        
        print("="*80, flush=True)
        print(f"\n📊 Total: {len(results)} symbols found and listed above", flush=True)
    else:
        print("\n❌ NO SYMBOLS PASSED THE FILTERS", flush=True)
        print("💡 Possible reasons:", flush=True)
        print("   • Market cap range too narrow (1K - 1M)", flush=True)
        print("   • Price <= EMA50 for most pairs", flush=True)
        print("   • No market cap data from CoinMarketCap", flush=True)
    
    # ارسال به تلگرام
    if TELEGRAM_CHAT_IDS and results:
        print("\n📤 Sending results to Telegram...", flush=True)
        msgs = build_message(results, len(get_spot_pairs()))
        for msg in msgs:
            send_telegram(msg)
            time.sleep(0.3)
        print("✅ Sent to Telegram", flush=True)
    elif not results:
        print("\n⚠️ No results to send to Telegram", flush=True)
