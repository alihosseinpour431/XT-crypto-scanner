#!/usr/bin/env python3
"""
🔍 XT Spot Scanner | Price > EMA50 | Market Cap 1K-1M
"""
import os
import time
import ccxt
import pandas as pd
import numpy as np
import requests
from datetime import datetime
from html import escape
from tqdm.auto import tqdm

# ================= CONFIG =================
EXCHANGE_ID = 'xt'
SCAN_SPOT = True
SCAN_FUTURES = False
DAILY_TF = '1d'
DAILY_LIMIT = 100
MIN_BARS_REQUIRED = 50
MIN_MARKET_CAP = 1_000      # 1K دلار
MAX_MARKET_CAP = 1_000_000  # 1M دلار
DEBUG_MODE = False
CMC_API_KEY = "39478549b7c94ee093d0f3cbe43a39e9"

# Telegram
TELEGRAM_BOT_TOKEN = "8766406031:AAEK0GuMnw3EFD5BSGgGQ3aPYbYcKXyG59U"
TELEGRAM_CHAT_IDS = ["your_chat_id"]  # آیدی تلگرامت رو بذار

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

# ================= GET PAIRS =================
def get_spot_pairs():
    symbol_map = {}
    for symbol, info in exchange_markets.items():
        if not info.get('active'):
            continue
        if info.get('quote') != 'USDT':
            continue
        is_spot = info.get('spot', False)
        if SCAN_SPOT and is_spot:
            base = symbol.split('/')[0].upper()
            if base not in symbol_map:
                symbol_map[base] = (symbol, info)
    return list(symbol_map.values())

# ================= FETCH DATA =================
def fetch_ohlcv(symbol, timeframe, limit):
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if len(data) < MIN_BARS_REQUIRED:
            return None
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Fetch error {symbol}: {e}")
        return None

# ================= MARKET CAP =================
def get_market_cap_from_cmc(symbol_base):
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
            coin_data = data["data"][symbol_base.upper()]
            market_cap = coin_data.get("quote", {}).get("USD", {}).get("market_cap")
            if market_cap is not None and market_cap > 0:
                return float(market_cap)
        return None
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ CMC error for {symbol_base}: {e}")
        return None

# ================= SCAN =================
def scan_spot():
    results = []
    pairs = get_spot_pairs()
    print(f"🔍 Scanning {len(pairs)} spot pairs...")
    print(f"   Filter: Price > EMA50 (Daily)")
    print(f"   Market Cap: ${MIN_MARKET_CAP/1e3:.1f}K - ${MAX_MARKET_CAP/1e6:.1f}M")
    
    for symbol, info in tqdm(pairs, desc="Scanning"):
        try:
            df = fetch_ohlcv(symbol, DAILY_TF, DAILY_LIMIT)
            if df is None:
                continue
            
            df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
            last = df.iloc[-1]
            
            if pd.isna(last['close']) or pd.isna(last['ema50']):
                continue
            
            if not (last['close'] > last['ema50']):
                continue
            
            symbol_base = symbol.split('/')[0]
            market_cap = get_market_cap_from_cmc(symbol_base)
            
            if market_cap is None or not (MIN_MARKET_CAP <= market_cap <= MAX_MARKET_CAP):
                continue
            
            results.append({
                'symbol': symbol,
                'symbol_base': symbol_base,
                'price': last['close'],
                'market_cap': market_cap,
                'volume_24h': float(df['volume'].iloc[-1]),
                'mkt_type': 'S'
            })
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"⚠️ Error {symbol}: {e}")
        time.sleep(0.05)
    
    results.sort(key=lambda x: x['market_cap'] or 0, reverse=True)
    return results

# ================= BUILD MESSAGE =================
def build_message(signals, total_scanned):
    now = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    header = (
        f"🔍 <b>XT Spot Scanner</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Scanned: <code>{total_scanned}</code> | ✅ Found: <code>{len(signals)}</code>\n"
        f"📋 Filter: Price &gt; EMA50 (Daily)\n"
        f"💰 Market Cap: ${MIN_MARKET_CAP/1e3:.1f}K - ${MAX_MARKET_CAP/1e6:.1f}M\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    footer = f"\n⏰ {now} 🇮🇷\n🤖 XT Spot Scanner v1.0"
    
    msgs = []
    body = ""
    MAX = 4000
    
    for r, s in enumerate(signals, 1):
        tv_symbol = s['symbol'].replace('/', '')
        tv_link = f"https://www.tradingview.com/chart/?symbol=XT:{tv_symbol}"
        
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
# ================= MAIN =================
def run():
    print("🚀 Starting XT Spot Scanner...")
    results = scan_spot()
    print(f"✅ Found {len(results)} symbols")
    
    # 🎯 نمایش لیست کامل ارزها در console
    if results:
        print("\n" + "="*70)
        print("🎯 FOUND SYMBOLS (Spot Market):")
        print("="*70)
        print(f"{'#':<4} {'Symbol':<15} {'Price':<15} {'Market Cap':<15} {'Volume 24h':<15}")
        print("-"*70)
        
        for i, s in enumerate(results, 1):
            mc_str = f"${s['market_cap']/1e6:.2f}M" if s['market_cap'] >= 1e6 else f"${s['market_cap']/1e3:.2f}K"
            vol_str = f"${s['volume_24h']/1e6:.2f}M" if s['volume_24h'] >= 1e6 else f"${s['volume_24h']/1e3:.2f}K"
            print(f"{i:<4} {s['symbol']:<15} {s['price']:<15,.6f} {mc_str:<15} {vol_str:<15}")
        
        print("="*70)
        print(f"\n📊 Total: {len(results)} symbols found")
    
    if TELEGRAM_CHAT_IDS:
        msgs = build_message(results, len(get_spot_pairs()))
        for msg in msgs:
            send_telegram(msg)
            time.sleep(0.3)
        print("✅ Sent to Telegram")
