#!/usr/bin/env python3
"""
📊 XT Futures Scanner | 2-Stage Filter
Stage 1: Daily - Price > EMA(50)
Stage 2: Hourly - Price > EMA(50) > EMA(200)
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

DAILY_TF = '1d'
DAILY_LIMIT = 100
HOURLY_TF = '1h'
HOURLY_LIMIT = 250
EMA_50 = 50
EMA_200 = 200

# ================= EXCHANGE =================
try:
    exchange = getattr(ccxt, EXCHANGE_ID)({
        'enableRateLimit': True,
        'timeout': 30000
    })
    exchange_markets = exchange.load_markets()
    print(f"✅ Connected to {EXCHANGE_ID.upper()} Futures")
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

# ================= GET FUTURES PAIRS =================
def get_futures_pairs():
    symbol_map = {}
    for symbol, info in exchange_markets.items():
        if not info.get('active'):
            continue
        if info.get('quote') != 'USDT':
            continue
        is_future = info.get('future', False) or info.get('swap', False)
        if is_future:
            base = symbol.split('/')[0].upper()
            if base not in symbol_map:
                symbol_map[base] = (symbol, info)
    return list(symbol_map.values())

# ================= FETCH DATA =================
def fetch_ohlcv(symbol, timeframe, limit):
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if len(data) < EMA_200:
            return None
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        return None

# ================= STAGE 1: DAILY =================
def stage1_filter(pairs):
    """Filter 1: Daily - Price > EMA(50)"""
    passed = []
    print(f"\n📊 Stage 1: Daily Filter (Price &gt; EMA{EMA_50})", flush=True)
    
    for symbol, info in tqdm(pairs, desc="Stage 1"):
        try:
            df = fetch_ohlcv(symbol, DAILY_TF, DAILY_LIMIT)
            if df is None:
                continue
            
            df['ema50'] = df['close'].ewm(span=EMA_50, adjust=False).mean()
            last = df.iloc[-1]
            
            if pd.isna(last['close']) or pd.isna(last['ema50']):
                continue
            
            # شرط: Price > EMA50
            if last['close'] > last['ema50']:
                passed.append((symbol, info))
                
        except Exception as e:
            pass
        time.sleep(0.05)
    
    print(f"✅ Stage 1: {len(passed)}/{len(pairs)} passed", flush=True)
    return passed

# ================= STAGE 2: HOURLY =================
def stage2_filter(pairs):
    """Filter 2: Hourly - Price > EMA(50) > EMA(200)"""
    results = []
    print(f"\n📊 Stage 2: Hourly Filter (Price &gt; EMA{EMA_50} &gt; EMA{EMA_200})", flush=True)
    
    for symbol, info in tqdm(pairs, desc="Stage 2"):
        try:
            df = fetch_ohlcv(symbol, HOURLY_TF, HOURLY_LIMIT)
            if df is None:
                continue
            
            df['ema50'] = df['close'].ewm(span=EMA_50, adjust=False).mean()
            df['ema200'] = df['close'].ewm(span=EMA_200, adjust=False).mean()
            last = df.iloc[-1]
            
            if pd.isna(last['close']) or pd.isna(last['ema50']) or pd.isna(last['ema200']):
                continue
            
            # شرط: Price > EMA50 > EMA200
            if last['close'] > last['ema50'] > last['ema200']:
                results.append({
                    'symbol': symbol,
                    'symbol_base': symbol.split('/')[0],
                    'price': last['close'],
                    'mkt_type': 'F'
                })
                
        except Exception as e:
            pass
        time.sleep(0.05)
    
    print(f"✅ Stage 2: {len(results)} passed", flush=True)
    return results

# ================= BUILD MESSAGE =================
def build_message(signals, stage1_count, total_scanned):
    now = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    header = (
        f"📊 <b>XT Futures Scanner | 2-Stage</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Total: <code>{total_scanned}</code> | Stage1: <code>{stage1_count}</code> | ✅ Final: <code>{len(signals)}</code>\n"
        f"📋 Stage 1: Price &gt; EMA{EMA_50} (Daily)\n"
        f"📋 Stage 2: Price &gt; EMA{EMA_50} &gt; EMA{EMA_200} (Hourly)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    footer = f"\n⏰ {now} 🇮🇷\n🤖 XT Futures Scanner"
    
    msgs = []
    body = ""
    MAX = 4000
    
    for r, s in enumerate(signals, 1):
        tv_link = f"https://www.tradingview.com/chart/?symbol=XT:{s['symbol'].replace('/', '')}"
        
        card = (
            f"{r}. <a href='{tv_link}'>{escape(s['symbol_base'])}</a> | "
            f"💰{s['price']:,.6f}\n"
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
    print("🚀 Starting XT Futures Scanner (2-Stage)...", flush=True)
    pairs = get_futures_pairs()
    print(f"📊 Total futures pairs: {len(pairs)}", flush=True)
    
    stage1_passed = stage1_filter(pairs)
    results = stage2_filter(stage1_passed)
    
    print(f"\n✅ Final: {len(results)} symbols", flush=True)
    
    # نمایش لیست در کنسول
    if results:
        print("\n" + "="*70, flush=True)
        print(f"🎯 FOUND {len(results)} SYMBOLS:", flush=True)
        print("="*70, flush=True)
        print(f"{'#':<4} {'Symbol':<20} {'Price':<15}", flush=True)
        print("-"*70, flush=True)
        for i, s in enumerate(results, 1):
            print(f"{i:<4} {s['symbol']:<20} {s['price']:<15,.6f}", flush=True)
        print("="*70 + "\n", flush=True)
    
    # ارسال به تلگرام
    if TELEGRAM_CHAT_IDS:
        print("📤 Sending to Telegram...", flush=True)
        msgs = build_message(results, len(stage1_passed), len(pairs))
        for msg in msgs:
            send_telegram(msg)
            time.sleep(0.3)
        print("✅ Sent to Telegram", flush=True)

if __name__ == "__main__":
    run()
