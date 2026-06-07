#!/usr/bin/env python3
"""
🔍 XT Spot Scanner | Price > EMA(50) | Market Cap from XT
✅ Only XT API Data (No CMC, No Volume Proxy)
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
TELEGRAM_CHAT_IDS = ["your_chat_id"]  # آیدی تلگرامت

# فیلترها
DAILY_TF = '1d'
DAILY_LIMIT = 100
EMA_PERIOD = 50
MIN_MARKET_CAP = 1_000      # 1K USD
MAX_MARKET_CAP = 1_000_000  # 1M USD

# ================= EXCHANGE INIT =================
print("🔌 Connecting to XT...", flush=True)
try:
    exchange = getattr(ccxt, EXCHANGE_ID)({
        'enableRateLimit': True,
        'timeout': 30000,
        # هدرها برای جلوگیری از بلاک شدن گیت‌هاب (403)
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'application/json',
            'Origin': 'https://www.xt.com',
            'Referer': 'https://www.xt.com/'
        },
        'options': {'defaultType': 'spot'}
    })
    
    # تلاش برای لود مارکت‌ها
    for attempt in range(3):
        try:
            print(f"📦 Loading markets ({attempt+1}/3)...", flush=True)
            exchange_markets = exchange.load_markets()
            print(f"✅ Loaded {len(exchange_markets)} markets", flush=True)
            break
        except Exception as e:
            print(f"⚠️ Attempt {attempt+1} failed", flush=True)
            if attempt < 2: time.sleep(3)
            else: raise
except Exception as e:
    print(f"❌ Error: {e}", flush=True)
    sys.exit(1)

# ================= GET SPOT PAIRS =================
def get_spot_pairs():
    pairs = []
    for symbol, info in exchange_markets.items():
        if not info.get('active'): continue
        if info.get('quote') != 'USDT': continue
        if info.get('spot', False):
            pairs.append((symbol, info))
    print(f"📊 Found {len(pairs)} active spot USDT pairs", flush=True)
    return pairs

# ================= FETCH DATA =================
def fetch_ohlcv(symbol, timeframe, limit):
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if len(data) < EMA_PERIOD: return None
        df = pd.DataFrame(data, columns=['timestamp','open','high','low','close','volume'])
        df['close'] = df['close'].astype(float)
        return df
    except: return None

# ================= MARKET CAP FROM XT =================
def get_market_cap_from_xt(symbol):
    """
    دریافت مارکت‌کپ مستقیم از داده‌های XT
    اولویت: 1) Info داخل مارکت 2) Info داخل تیکر
    """
    try:
        # 1. بررسی دیتای مارکت (که قبلاً لود شده)
        market_info = exchange.markets[symbol].get('info', {})
        mc = market_info.get('marketCap') or market_info.get('market_cap') or market_info.get('marketCapUsd')
        
        if mc is not None:
            return float(mc)
        
        # 2. اگر نبود، فچ تیکر (دقیق‌تر)
        # نکته: فچ تیکر زمان‌بره، فقط برای کاندیداهای نهایی استفاده میشه یا اگر مارکت نداشت
        ticker = exchange.fetch_ticker(symbol)
        ticker_info = ticker.get('info', {})
        
        # کلیدهای احتمالی در XT
        mc = (ticker_info.get('marketCap') or 
              ticker_info.get('market_cap') or 
              ticker_info.get('marketCapUsd') or
              ticker_info.get('mc'))
              
        if mc is not None:
            return float(mc)
            
        return None
    except Exception as e:
        return None

# ================= SCAN SPOT =================
def scan_spot():
    results = []
    pairs = get_spot_pairs()
    
    print(f"\n🔍 Scanning {len(pairs)} pairs...", flush=True)
    print(f"   Filter 1: Price > EMA{EMA_PERIOD} (Daily)", flush=True)
    print(f"   Filter 2: Market Cap {MIN_MARKET_CAP/1e3:.0f}K - {MAX_MARKET_CAP/1e6:.1f}M (from XT)", flush=True)
    print("-" * 70, flush=True)
    
    for symbol, info in tqdm(pairs, desc="Scanning"):
        try:
            # فیلتر 1: EMA
            df = fetch_ohlcv(symbol, DAILY_TF, DAILY_LIMIT)
            if df is None: continue
            
            df['ema50'] = df['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
            last = df.iloc[-1]
            
            if pd.isna(last['close']) or pd.isna(last['ema50']): continue
            if not (last['close'] > last['ema50']): continue  # شرط قیمت بالاتر از EMA
            
            # فیلتر 2: مارکت‌کپ مستقیم از XT
            # برای کاهش درخواست‌های اضافه، اول چک می‌کنیم ببینیم توی لیست مارکت‌ها هست یا نه
            # اما چون دقیق میخوایم، از تابع اختصاصی استفاده میکنیم
            
            # ⚠️ نکته: اگر بخواهیم سرعت بالا بره، باید مارکت کپ رو چک کنیم
            # اگر صرافی XT مارکت کپ رو توی load_markets برنمیگردونه، این قسمت کند میشه
            # فرض بر این است که XT مارکت کپ رو داره.
            
            market_cap = get_market_cap_from_xt(symbol)
            
            if market_cap is None: 
                # اگر مارکت کپ دیتا نداشت، رد میکنیم (یا میتونی لاجیک رو عوض کنی)
                continue
                
            if not (MIN_MARKET_CAP <= market_cap <= MAX_MARKET_CAP): continue
            
            results.append({
                'symbol': symbol,
                'symbol_base': symbol.split('/')[0],
                'price': last['close'],
                'market_cap': market_cap,
                'mkt_type': 'S'
            })
            
        except: pass
        time.sleep(0.05)  # جلوگیری از ریت لیمیت XT
    
    return results

# ================= BUILD MESSAGE =================
def build_message(signals, total_scanned):
    now = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    header = (
        f" <b>XT Spot Scanner</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Scanned: <code>{total_scanned}</code> | ✅ Found: <code>{len(signals)}</code>\n"
        f"📋 Filter: Price &gt; EMA{EMA_PERIOD} (Daily)\n"
        f"💰 Market Cap (XT Data): ${MIN_MARKET_CAP/1e3:.0f}K - ${MAX_MARKET_CAP/1e6:.1f}M\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    footer = f"\n {now} 🇮🇷\n🤖 XT Spot Scanner"
    
    msgs, body, MAX = [], "", 4000
    for r, s in enumerate(signals, 1):
        tv_link = f"https://www.tradingview.com/chart/?symbol=XT:{s['symbol'].replace('/', '')}"
        
        # فرمت مارکت کپ
        if s['market_cap'] >= 1e6:
            mc_str = f"${s['market_cap']/1e6:.2f}M"
        elif s['market_cap'] >= 1e3:
            mc_str = f"${s['market_cap']/1e3:.2f}K"
        else:
            mc_str = f"${s['market_cap']:,.0f}"
            
        card = f"{r}. <a href='{tv_link}'>{escape(s['symbol_base'])}</a> | 💰{s['price']:,.6f} | 🏛️{mc_str}\n"
        
        if len(header) + len(body) + len(card) + len(footer) > MAX - 100:
            if body.strip(): msgs.append(header + body + footer)
            body = card
        else: body += card
    if body.strip(): msgs.append(header + body + footer)
    if not msgs: msgs.append(f"{header}❌ No symbols found.{footer}")
    return msgs

# ================= TELEGRAM =================
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN: return
    for cid in TELEGRAM_CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={'chat_id': cid, 'text': text, 'parse_mode': 'HTML'},
                timeout=30
            )
        except: pass

# ================= MAIN =================
def run():
    print(" Starting XT Spot Scanner...", flush=True)
    results = scan_spot()
    print(f"\n✅ Found {len(results)} symbols", flush=True)
    
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
    
    if TELEGRAM_CHAT_IDS and results:
        print("📤 Sending to Telegram...", flush=True)
        for msg in build_message(results, len(get_spot_pairs())):
            send_telegram(msg)
            time.sleep(0.3)
        print("✅ Sent to Telegram", flush=True)

if __name__ == "__main__":
    run()
