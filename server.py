from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import threading
import time
import requests
import json
import os
from datetime import datetime

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    class EWrapper: pass
    class EClient:
        def __init__(self, wrapper): pass
    class Contract: pass

app = Flask(__name__, static_folder='.')
CORS(app)

# ── API Key — env var → disk fallback ─────────────────────────────────────────
TD_KEY = os.environ.get('TD_KEY', '').strip()

_KEY_FILE = os.path.join(os.path.dirname(__file__), '.td_key')
def _load_key():
    global TD_KEY
    if TD_KEY:
        print(f'TD Key from env: {TD_KEY[:6]}...')
        return
    try:
        with open(_KEY_FILE, 'r') as f:
            TD_KEY = f.read().strip()
        if TD_KEY:
            print(f'TD Key loaded from disk: {TD_KEY[:6]}...')
    except FileNotFoundError:
        pass
def _save_key(k):
    global TD_KEY
    TD_KEY = k
    try:
        with open(_KEY_FILE, 'w') as f:
            f.write(k)
    except Exception as e:
        print(f'Could not save TD key: {e}')
_load_key()

# ── טעינת סמלים לזיכרון ───────────────────────────────────────────────────────
SYMBOLS = []
def load_symbols():
    global SYMBOLS
    path = os.path.join(os.path.dirname(__file__), 'symbols.json')
    try:
        with open(path, encoding='utf-8') as f:
            SYMBOLS = json.load(f)
        print(f'Symbols loaded: {len(SYMBOLS)}')
    except FileNotFoundError:
        print('symbols.json not found — run fetch_symbols.py')
load_symbols()

ALL_SYMBOLS = [
    # ── Mega-cap Tech ──────────────────────────────────────────────────────
    'AAPL','MSFT','NVDA','GOOGL','AMZN','META','TSLA','ORCL','ADBE','INTU',
    # ── Semiconductors ─────────────────────────────────────────────────────
    'AMD','INTC','AVGO','QCOM','TXN','AMAT','MU','LRCX','KLAC','MRVL',
    'NXPI','ON','SNPS','CDNS','MCHP','MPWR','SWKS','TER','ENPH','TSM',
    # ── Software & Cloud ───────────────────────────────────────────────────
    'CRM','NOW','WDAY','VEEV','ADSK','DDOG','SNOW','PLTR','MDB','HUBS',
    'OKTA','ZM','DOCU','BILL','TWLO','NET','CFLT','GTLB','SMAR','ZI',
    # ── Cybersecurity ──────────────────────────────────────────────────────
    'PANW','CRWD','ZS','FTNT','S','TENB',
    # ── Hardware & Networking ──────────────────────────────────────────────
    'CSCO','HPQ','HPE','ANET','NTAP','JNPR',
    # ── Internet & E-commerce ─────────────────────────────────────────────
    'NFLX','UBER','ABNB','SHOP','LYFT','DASH','ETSY','EBAY','PINS','RDDT',
    # ── Media & Telecom ────────────────────────────────────────────────────
    'DIS','CMCSA','T','VZ','TMUS','ROKU','SNAP','WBD',
    # ── Megabanks ─────────────────────────────────────────────────────────
    'JPM','BAC','WFC','GS','MS','C','USB','PNC','TFC','BK',
    # ── Cards & Payments ──────────────────────────────────────────────────
    'V','MA','PYPL','AXP','COF','SQ','COIN','HOOD',
    # ── Investment & Asset Management ─────────────────────────────────────
    'SCHW','BLK','SPGI','ICE','CME','MCO','MSCI','FIS','CBOE','NDAQ',
    # ── Insurance ─────────────────────────────────────────────────────────
    'AIG','MET','PRU','ALL','TRV','CB','AON','MMC',
    # ── Healthcare / Pharma ────────────────────────────────────────────────
    'JNJ','UNH','PFE','ABBV','MRK','LLY','BMY','AMGN','GILD','REGN',
    'VRTX','MRNA','BNTX','HUM','CI','CVS','MCK','CAH',
    # ── Medical Devices ────────────────────────────────────────────────────
    'ISRG','MDT','SYK','BSX','ABT','TMO','DHR','DXCM','EW','A',
    # ── Retail ────────────────────────────────────────────────────────────
    'WMT','HD','TGT','COST','LOW','MCD','SBUX','NKE','DG','DLTR',
    # ── Consumer Staples ───────────────────────────────────────────────────
    'PG','KO','PEP','PM','MO','CL','KMB','EL','MDLZ','GIS',
    # ── Energy ────────────────────────────────────────────────────────────
    'XOM','CVX','COP','EOG','MPC','VLO','PSX','OXY','DVN','HAL','SLB',
    # ── Industrial / Aerospace / Defense ─────────────────────────────────
    'BA','GE','CAT','DE','MMM','HON','RTX','LMT','UPS','FDX',
    'NOC','GD','ETN','EMR','ROK','PH','ITW','IR',
    # ── Utilities ─────────────────────────────────────────────────────────
    'NEE','DUK','SO','D','AEP','EXC','XEL',
    # ── Real Estate ───────────────────────────────────────────────────────
    'AMT','PLD','CCI','EQIX','O','PSA','DLR','SBAC','WELL',
    # ── Materials ─────────────────────────────────────────────────────────
    'LIN','APD','ECL','SHW','NEM','FCX','AA','ALB','DD','NUE',
    # ── Auto ──────────────────────────────────────────────────────────────
    'F','GM',
    # ── High-growth & Speculative ─────────────────────────────────────────
    'SMCI','APP','MSTR','AI','ARM','ASML',
    # ── ETFs ──────────────────────────────────────────────────────────────
    'SPY','QQQ','IWM','GLD','TLT','DIA','XLF','XLK','XLV','ARKK',
]

def is_market_open():
    now = datetime.utcnow()
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    return (h == 13 and m >= 30) or (14 <= h <= 19) or (h == 20 and m == 0)

class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.data = {}
        self.connected = False

    def nextValidId(self, orderId):
        self.connected = True

    def tickPrice(self, reqId, tickType, price, attrib):
        if reqId not in self.data:
            self.data[reqId] = {}
        if tickType == 4:  self.data[reqId]['last']  = price
        if tickType == 9:  self.data[reqId]['close'] = price
        if tickType == 6:  self.data[reqId]['high']  = price
        if tickType == 7:  self.data[reqId]['low']   = price
        if tickType == 14: self.data[reqId]['open']  = price
        if tickType == 1:  self.data[reqId]['bid']   = price
        if tickType == 2:  self.data[reqId]['ask']   = price

    def tickSize(self, reqId, tickType, size):
        if reqId not in self.data:
            self.data[reqId] = {}
        if tickType == 8:  self.data[reqId]['volume']    = int(size)
        if tickType == 21: self.data[reqId]['avgVolume'] = int(size)
        if tickType == 87: self.data[reqId]['high52']    = float(size)
        if tickType == 88: self.data[reqId]['low52']     = float(size)

    def tickString(self, reqId, tickType, value):
        if reqId not in self.data:
            self.data[reqId] = {}
        # RTVolume = last price;last size;last time;total volume;VWAP;single trade
        if tickType == 48:
            try:
                parts = value.split(';')
                if parts[0]: self.data[reqId]['last'] = float(parts[0])
                if parts[3]: self.data[reqId]['volume'] = int(float(parts[3]))
            except: pass

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        if errorCode not in [2104, 2106, 2158, 2119, 2176]:
            print(f'IB {reqId}: {errorCode} {errorString}')

ib_app = IBApp()

def start_ib(host, port):
    global ib_app
    if not IB_AVAILABLE:
        return False
    try:
        ib_app = IBApp()
        ib_app.connect(host, port, clientId=3)
        t = threading.Thread(target=ib_app.run, daemon=True)
        t.start()
        time.sleep(2)
        return ib_app.connected
    except Exception as e:
        print(f'IB error: {e}')
        return False

def fetch_ib(symbols):
    ib_app.data = {}
    req_map = {}
    for i, sym in enumerate(symbols):
        rid = i + 2000
        req_map[rid] = sym
        c = Contract()
        c.symbol = sym
        c.secType = 'STK'
        c.exchange = 'SMART'
        c.currency = 'USD'
        # 233 = RTVolume — עובד בלי מנוי נוסף
        ib_app.reqMktData(rid, c, '233', False, False, [])
    time.sleep(4)
    results = []
    for rid, sym in req_map.items():
        d = ib_app.data.get(rid, {})
        price = d.get('last') or d.get('bid') or d.get('close') or 0
        if price <= 0:
            continue
        prev = d.get('close') or price
        chg  = round(price - prev, 2)
        chgp = round((chg / prev * 100) if prev else 0, 2)
        results.append({
            'ticker': sym, 'name': sym, 'exchange': 'IB',
            'price': round(float(price), 2),
            'change': chg, 'changePercent': chgp,
            'open':  round(float(d.get('open', 0)), 2),
            'high':  round(float(d.get('high', 0)), 2),
            'low':   round(float(d.get('low', 0)), 2),
            'volume': int(d.get('volume', 0)),
            'avgVolume': max(int(d.get('avgVolume', 1)), 1),
            'fiftyTwoWeekHigh': round(float(d.get('high52', 0)), 2),
            'fiftyTwoWeekLow':  round(float(d.get('low52', 0)), 2),
            'marketOpen': is_market_open(),
        })
    for rid in req_map:
        try: ib_app.cancelMktData(rid)
        except: pass
    return results

def td_quote_batch(symbols, batch_size=100):
    """שולח בקשות ל-Twelve Data בחבילות. כל חבילה = בקשת HTTP אחת."""
    if not TD_KEY:
        return []
    all_results = []
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        joined = ','.join(batch)
        try:
            prev_count = len(all_results)
            r = requests.get(
                f'https://api.twelvedata.com/quote?symbol={joined}&apikey={TD_KEY}',
                timeout=30
            )
            data = r.json()
            if 'symbol' in data:
                data = {data['symbol']: data}
            for sym, q in data.items():
                if not q or q.get('status') == 'error':
                    continue
                raw = q.get('close') or q.get('last') or q.get('previous_close')
                if not raw:
                    continue
                price = float(raw)
                prev  = float(q.get('previous_close') or raw)
                chg   = price - prev
                chgp  = (chg / prev * 100) if prev else 0
                all_results.append({
                    'ticker': q.get('symbol', sym),
                    'name': q.get('name', sym),
                    'exchange': q.get('exchange', ''),
                    'price': round(price, 2),
                    'change': round(chg, 2),
                    'changePercent': round(chgp, 2),
                    'open': float(q.get('open', 0)),
                    'high': float(q.get('high', 0)),
                    'low': float(q.get('low', 0)),
                    'volume': int(q.get('volume', 0)),
                    'avgVolume': int(q.get('average_volume', 0)),
                    'fiftyTwoWeekHigh': float((q.get('fifty_two_week') or {}).get('high', 0)),
                    'fiftyTwoWeekLow':  float((q.get('fifty_two_week') or {}).get('low', 0)),
                    'marketOpen': is_market_open(),
                })
            print(f'TD batch {i//batch_size+1}: {len(batch)} סמלים, קיבל {len(all_results)-prev_count} תוצאות')
        except Exception as e:
            print(f'TD batch error: {e}')
    return all_results

@app.route('/')
def index():
    return send_from_directory('.', 'screener.html')

@app.route('/api/connect_ib', methods=['POST'])
def connect_ib():
    data = request.json or {}
    port = int(data.get('port', 7497))
    ok = start_ib('127.0.0.1', port)
    if ok:
        return jsonify({'status': 'ok', 'account': ['מחובר']})
    return jsonify({'status': 'error', 'message': 'לא ניתן להתחבר — ודא TWS פתוח'}), 500

@app.route('/api/ib_status')
def ib_status():
    return jsonify({'connected': ib_app.connected})

@app.route('/api/symbols')
def get_symbols():
    if SYMBOLS:
        return jsonify(SYMBOLS)
    # Fallback: ALL_SYMBOLS שכבר קיים בקוד
    fallback = [{'ticker': s, 'name': s, 'exchange': 'SMART'} for s in ALL_SYMBOLS]
    return jsonify(fallback)

@app.route('/api/hebrew_names')
def get_hebrew_names():
    """מחזיר את מילון שמות החברות בעברית"""
    p = os.path.join(os.path.dirname(__file__), 'hebrew_names.json')
    if not os.path.exists(p):
        return jsonify({})
    with open(p, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/api/disconnect_ib', methods=['POST'])
def disconnect_ib():
    global ib_app
    try:
        ib_app.disconnect()
    except: pass
    ib_app.connected = False
    return jsonify({'status': 'ok'})

@app.route('/api/stocks_ib')
def get_stocks_ib():
    if not ib_app.connected:
        return jsonify({'error': 'לא מחובר ל-IB — לחץ התחבר ל-IB'}), 400
    sym_list = [s['ticker'] for s in SYMBOLS] if SYMBOLS else ALL_SYMBOLS
    default_count = min(len(sym_list), 500)
    count = int(request.args.get('count', default_count))
    syms = sym_list[:count]
    results = []
    BATCH = 50
    for i in range(0, len(syms), BATCH):
        batch = syms[i:i+BATCH]
        r = fetch_ib(batch)
        results += r
    return jsonify({'stocks': results, 'total': len(results), 'source': 'IB'})

@app.route('/api/fetch_symbols', methods=['POST'])
def fetch_symbols_from_api():
    """טעינת כל הסמלים מ-Twelve Data ושמירה ל-symbols.json."""
    global SYMBOLS
    key = (request.json or {}).get('key', TD_KEY).strip()
    if not key:
        return jsonify({'error': 'נדרש API Key'}), 400
    exchanges = ['NASDAQ', 'NYSE', 'AMEX']
    all_syms = []
    for exchange in exchanges:
        try:
            r = requests.get(
                'https://api.twelvedata.com/stocks',
                params={'exchange': exchange, 'apikey': key,
                        'type': 'Common Stock', 'format': 'JSON'},
                timeout=30
            )
            items = r.json().get('data', [])
            for s in items:
                ticker = s.get('symbol', '').strip()
                if ticker and 1 <= len(ticker) <= 6:
                    all_syms.append({
                        'ticker': ticker,
                        'name': s.get('name', ticker).strip(),
                        'exchange': s.get('exchange', exchange).strip(),
                    })
            print(f'  {exchange}: {len(items)} סמלים')
        except Exception as e:
            print(f'fetch_symbols error ({exchange}): {e}')
    seen, unique = set(), []
    for s in all_syms:
        if s['ticker'] not in seen:
            seen.add(s['ticker'])
            unique.append(s)
    unique.sort(key=lambda x: (len(x['ticker']), x['ticker']))
    SYMBOLS = unique
    path = os.path.join(os.path.dirname(__file__), 'symbols.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(unique, f, ensure_ascii=False, separators=(',', ':'))
        print(f'symbols.json נשמר: {len(unique)} סמלים')
    except Exception as e:
        print(f'Save symbols error: {e}')
    return jsonify({'status': 'ok', 'count': len(unique)})

@app.route('/api/key', methods=['POST'])
def set_key():
    """שמירת מפתח בלבד — ללא בדיקה (מהיר, לטעינת עמוד). מחרוזת ריקה מנקה."""
    k = (request.json or {}).get('key', '').strip()
    _save_key(k)
    return jsonify({'status': 'ok'})

@app.route('/api/key/test', methods=['POST'])
def test_key():
    """שמירה + בדיקה עם קריאת API (לכפתור 'שמור ובדוק')."""
    k = (request.json or {}).get('key', '').strip()
    _save_key(k)
    try:
        r = requests.get(
            f'https://api.twelvedata.com/price?symbol=AAPL&apikey={TD_KEY}',
            timeout=8
        )
        j = r.json()
        if j.get('price'):
            return jsonify({'status': 'ok', 'price': j['price']})
        return jsonify({'status': 'error', 'message': j.get('message', 'Key שגוי')}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/stocks')
def get_stocks():
    if not TD_KEY:
        return jsonify({'error': 'אין API Key'}), 400
    # Use full SYMBOLS from symbols.json if available, else fallback to hardcoded list
    if SYMBOLS:
        sym_list = [s['ticker'] for s in SYMBOLS]
    else:
        sym_list = ALL_SYMBOLS
    # Default: fetch up to 500 quotes (rate-limit friendly); caller can override with ?count=N
    default_count = min(len(sym_list), 500)
    count = int(request.args.get('count', default_count))
    syms = sym_list[:count]
    print(f'/api/stocks: fetching quotes for {len(syms)} symbols (total available: {len(sym_list)})')
    results = td_quote_batch(syms)
    return jsonify({'stocks': results, 'total': len(results), 'available': len(sym_list)})

@app.route('/api/search')
def search():
    sym = request.args.get('symbol', '').upper().strip()
    if not sym:
        return jsonify({'error': 'חסר symbol'}), 400
    if ib_app.connected:
        try:
            r = fetch_ib([sym])
            if r:
                return jsonify(r[0])
        except: pass
    if TD_KEY:
        try:
            r = requests.get(
                f'https://api.twelvedata.com/quote?symbol={sym}&apikey={TD_KEY}',
                timeout=8
            )
            q = r.json()
            if q.get('status') == 'error':
                return jsonify({'error': q.get('message', 'לא נמצא')}), 404
            raw   = q.get('close') or q.get('last') or q.get('previous_close')
            price = float(raw or 0)
            if price == 0:
                return jsonify({'error': f'אין מחיר זמין עבור {sym}'}), 404
            prev  = float(q.get('previous_close') or raw)
            chg   = price - prev
            chgp  = (chg / prev * 100) if prev else 0
            return jsonify({
                'ticker': q.get('symbol', sym),
                'name': q.get('name', sym),
                'exchange': q.get('exchange', ''),
                'price': round(price, 2),
                'change': round(chg, 2),
                'changePercent': round(chgp, 2),
                'open': float(q.get('open', 0)),
                'high': float(q.get('high', 0)),
                'low': float(q.get('low', 0)),
                'volume': int(q.get('volume', 0)),
                'avgVolume': int(q.get('average_volume', 0)),
                'fiftyTwoWeekHigh': float((q.get('fifty_two_week') or {}).get('high', 0)),
                'fiftyTwoWeekLow':  float((q.get('fifty_two_week') or {}).get('low', 0)),
                'marketOpen': is_market_open(),
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'error': 'הכנס API Key של Twelve Data'}), 400

if __name__ == '__main__':
    print("=" * 50)
    print("  סורק מניות — שרת פועל!")
    port = int(os.environ.get('PORT', 5000))
    print(f"  פתח Chrome ב: http://localhost:{port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)