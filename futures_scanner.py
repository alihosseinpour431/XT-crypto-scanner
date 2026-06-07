#!/usr/bin/env python3
"""
📊 XT Futures Scanner | 2-Stage Filter + Full Console Output
"""
import os
import sys
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
SCAN_SPOT = False
SCAN_FUTURES = True
DAILY_TF = '1d'
DAILY_LIMIT = 300
HOURLY_TF = '1h'
HOURLY_LIMIT = 300
MIN_BARS_REQUIRED = 200
VOLUME_RATIO_MIN = 1.0
MIN_MARKET_CAP = 5_000_000
MAX_MARKET_CAP = 100_000_000
MIN_RISK = 0.0
MAX_RISK = 5.0
RSI_PERIOD = 30
RSI_MIN = 50
RSI_MAX = 70

# ================= ENV =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS = [cid.strip() for cid in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if cid.strip()]
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
CMC_API_KEY = os.getenv("CMC_PRO_API_KEY", "39478549b7c94ee093d0f3cbe43a39e9")

# ================= EXCHANGE =================
try:
    exchange = getattr(ccxt, EXCHANGE_ID)({
        'enableRateLimit': True,
        'timeout': 30000
    })
    exchange_markets = exchange.load_markets()
    print(f"✅ Connected to {EXCHANGE_ID.upper()}", flush=True)
except Exception as e:
    print(f"❌ Error: {e}", flush=True)
    sys.exit(1)

# ================= FUNCTIONS =================
def get_filtered_pairs():
    symbol_map = {}
    for symbol, info in exchange_markets.items():
        if not info.get('active'): continue
        if info.get('quote') != 'USDT': continue
        is_future = info.get('future', False) or info.get('swap', False)
        if SCAN_FUTURES and is_future:
            base = symbol.split('/')[0].upper()
            if base not in symbol_map:
                symbol_map[base] = (symbol, info)
    return list(symbol_map.values())

def fetch_ohlcv(symbol, timeframe, limit):
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if len(data) < MIN_BARS_REQUIRED: return None
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        return None

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_market_cap_from_cmc(symbol_base):
    try:
        if not CMC_API_KEY: return None
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        params = {'symbol': symbol_base.upper(), 'convert': 'USD'}
        headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY, 'Accepts': 'application/json'}
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if "data" in data and symbol_base.upper() in data["data"]:
            mc = data["data"][symbol_base.upper()].get("quote", {}).get("USD", {}).get("market_cap")
            return float(mc) if mc and mc > 0 else None
        return None
    except Exception:
        return None

def scan_market(pairs):
    results = []
    total = len(pairs)
    
    print(f"\n🔍 Starting scan of {total} futures pairs...", flush=True)
    print(f"   └─ Filter 1: Daily - Price > EMA20 > EMA50", flush=True)
    print(f"   └─ Filter 2: Hourly - Price > EMA20 > EMA50", flush=True)
    print(f"   └─ Filter 3: RSI({RSI_PERIOD}) between {RSI_MIN}-{RSI_MAX}", flush=True)
    print(f"   └─ Filter 4: Volume Ratio >= {VOLUME_RATIO_MIN}x", flush=True)
    print(f"   └─ Filter 5: Market Cap ${MIN_MARKET_CAP/1e6:.0f}M - ${MAX_MARKET_CAP/1e6:.0f}M", flush=True)
    print(f"   └─ Risk: {MIN_RISK}% to {MAX_RISK}%", flush=True)
    print("-" * 70, flush=True)
    
    stage1_count = 0
    stage2_count = 0
    
    for idx, (symbol, info) in enumerate(tqdm(pairs, desc="Scanning", total=total), 1):
        try:
            # Filter 1: Daily
            df_daily = fetch_ohlcv(symbol, DAILY_TF, DAILY_LIMIT)
            if df_daily is None: continue
            df_daily['ema20'] = df_daily['close'].ewm(span=20, adjust=False).mean()
            df_daily['ema50'] = df_daily['close'].ewm(span=50, adjust=False).mean()
            last_daily = df_daily.iloc[-1]
            if pd.isna(last_daily['close']) or not (last_daily['close'] > last_daily['ema20'] > last_daily['ema50']):
                continue
            stage1_count += 1

            # Filter 2: Hourly
            df_hourly = fetch_ohlcv(symbol, HOURLY_TF, HOURLY_LIMIT)
            if df_hourly is None: continue
            df_hourly['ema20'] = df_hourly['close'].ewm(span=20, adjust=False).mean()
            df_hourly['ema50'] = df_hourly['close'].ewm(span=50, adjust=False).mean()
            last_hourly = df_hourly.iloc[-1]
            if pd.isna(last_hourly['close']) or not (last_hourly['close'] > last_hourly['ema20'] > last_hourly['ema50']):
                continue
            stage2_count += 1

            # Filter 3: RSI
            df_hourly['rsi'] = calculate_rsi(df_hourly['close'], RSI_PERIOD)
            last_rsi = df_hourly['rsi'].iloc[-1]
            if pd.isna(last_rsi) or not (RSI_MIN <= last_rsi <= RSI_MAX): continue

            # Filter 4: Volume
            avg_5h = df_hourly['volume'].iloc[-5:].mean()
            avg_200h = df_hourly['volume'].iloc[-200:].mean()
            volume_ratio = avg_5h / avg_200h if avg_200h > 0 else 0
            if volume_ratio < VOLUME_RATIO_MIN: continue

            # Filter 5: Market Cap
            symbol_base = symbol.split('/')[0]
            market_cap = get_market_cap_from_cmc(symbol_base)
            if market_cap is None or not (MIN_MARKET_CAP <= market_cap <= MAX_MARKET_CAP): continue

            # Risk
            risk_pct = ((last_hourly['ema20'] - last_hourly['ema50']) / last_hourly['ema50']) * 100
            if not (MIN_RISK <= risk_pct <= MAX_RISK): continue

            results.append({
                'symbol': symbol, 'symbol_base': symbol_base,
                'price': last_hourly['close'], 'risk_pct': risk_pct,
                'v_alpha': volume_ratio, 'rsi': last_rsi,
                'market_cap': market_cap, 'mkt_type': 'F'
            })
        except Exception as e:
            if DEBUG_MODE: print(f"⚠️ Error {symbol}: {e}", flush=True)
        time.sleep(0.01)
    
    print(f"\n📊 Stage Results:", flush=True)
    print(f"   ├─ Total pairs: {total}", flush=True)
    print(f"   ├─ Passed Stage 1 (Daily): {stage1_count}", flush=True)
    print(f"   ├─ Passed Stage 2 (Hourly): {stage2_count}", flush=True)
    print(f"   └─ Final results: {len(results)}", flush=True)
    
    results.sort(key=lambda x: x['risk_pct'])
    return results

def build_message(signals, total_scanned):
    from html import escape
    now = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    header = (
        f"🔍 <b>XT Futures Scanner</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Scanned: <code>{total_scanned}</code> | ✅ Found: <code>{len(signals)}</code>\n"
        f"📋 Filters: Price>EMA20>EMA50 | RSI {RSI_MIN}-{RSI_MAX} | Risk {MIN_RISK}-{MAX_RISK}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    footer = f"\n⏰ {now} 🇮🇷\n🤖 XT Futures Scanner"
    
    msgs = []
    body = ""
    MAX = 4000
    
    for r, s in enumerate(signals, 1):
        tv_link = f"https://www.tradingview.com/chart/?symbol=XT:{s['symbol'].replace('/', '')}"
        mc_str = f"${s['market_cap']/1e6:.2f}M" if s['market_cap'] >= 1e6 else f"${s['market_cap']/1e3:.2f}K"
        card = (
            f"{r}. <a href='{tv_link}'>{escape(s['symbol_base'])}</a> | "
            f"💰{s['price']:,.4f} | 📊RSI:{s['rsi']:.1f} | "
            f"⚠️{s['risk_pct']:.2f}% | 📈{s['v_alpha']:.2f}x | 🏛️{mc_str}\n"
        )
        if len(header) + len(body) + len(card) + len(footer) > MAX - 100:
            msgs.append(header + body + footer)
            body = card
        else:
            body += card
    
    if body.strip(): msgs.append(header + body + footer)
    if not msgs: msgs.append(f"{header}❌ No symbols found.{footer}")
    return msgs

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN: return
    for cid in TELEGRAM_CHAT_IDS:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {'chat_id': cid, 'text': text, 'parse_mode': 'HTML'}
        try: requests.post(url, json=payload, timeout=30)
        except: pass

# ================= MAIN =================
def run():
    print("🚀 Starting XT Futures Scanner...", flush=True)
    pairs = get_filtered_pairs()
    print(f"📊 Total futures pairs: {len(pairs)}", flush=True)
    
    results = scan_market(pairs)
    
    # 🎯 نمایش لیست کامل در کنسول (حتی اگر خالی باشه)
    print("\n" + "="*70, flush=True)
    if results:
        print(f"🎯 FOUND {len(results)} SYMBOLS (Sorted by Risk):", flush=True)
        print("="*70, flush=True)
        print(f"{'#':<4} {'Symbol':<15} {'Price':<12} {'Risk%':<8} {'RSI':<6} {'Vol':<8} {'MarketCap':<12}", flush=True)
        print("-"*70, flush=True)
        for i, s in enumerate(results, 1):
            mc_str = f"${s['market_cap']/1e6:.2f}M" if s['market_cap'] >= 1e6 else f"${s['market_cap']/1e3:.2f}K"
            print(f"{i:<4} {s['symbol']:<15} {s['price']:<12,.4f} {s['risk_pct']:<8,.2f} {s['rsi']:<6,.1f} {s['v_alpha']:<8,.2f}x {mc_str:<12}", flush=True)
    else:
        print("❌ NO SYMBOLS PASSED THE FILTERS", flush=True)
        print("💡 Possible reasons:", flush=True)
        print("   • Filters too strict (try widening RSI/Risk/MarketCap ranges)", flush=True)
        print("   • No active futures pairs on XT with USDT", flush=True)
        print("   • API rate limits or connection issues", flush=True)
    print("="*70 + "\n", flush=True)
    
    # ارسال به تلگرام
    if TELEGRAM_CHAT_IDS and results:
        print("📤 Sending results to Telegram...", flush=True)
        for msg in build_message(results, len(pairs)):
            send_telegram(msg)
            time.sleep(0.3)
        print("✅ Sent to Telegram", flush=True)
    elif not results:
        print("⚠️ No results to send to Telegram", flush=True)

if __name__ == "__main__":
    run()
