from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from scraper import fetch_taiex_daily, get_market_status, fetch_stock_history
from strategy import evaluate_stock
from database import init_db, get_db
import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

scheduler = BackgroundScheduler()

# Demo stock list representing the market (since full market is too large to fetch without a premium API)
MARKET_STOCKS = ['2330.TW', '2317.TW', '2454.TW', '3231.TW', '2382.TW'] 

def job_scan_market():
    # 1. Fetch TAIEX & evaluate Market Status
    taiex_data = fetch_taiex_daily()
    market_info = get_market_status(taiex_data)
    
    today = datetime.date.today().isoformat()
    
    # Save Market Status
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO market_status (date, status, taiex_close, up_count, down_count)
        VALUES (?, ?, ?, ?, ?)
    ''', (today, market_info.get('status', 'UNKNOWN'), market_info.get('taiex_close', 0.0), 0, 0)) # simplified up/down count
    conn.commit()
    
    # If Market is WEAK, return immediately, no stocks recommended
    if market_info['status'] == 'WEAK':
        conn.close()
        return
        
    # 2. Fetch stocks
    df_all = fetch_stock_history(MARKET_STOCKS, days=40)
    if not df_all:
        conn.close()
        return
        
    results = []
    for ticker in MARKET_STOCKS:
        try:
            df_ticker = df_all.get(ticker)
            
            if df_ticker is None:
                continue
                
            df_ticker.dropna(inplace=True)
            if df_ticker.empty:
               continue
               
            eval_res = evaluate_stock(df_ticker)
            if eval_res['candidate']:
                eval_res['stock_id'] = ticker
                results.append(eval_res)
        except Exception as e:
            print(f"Error evaluating {ticker}: {e}")
            
    # Sort by probability and keep top 10
    results = sorted(results, key=lambda x: x['probability'], reverse=True)[:10]
    
    # Save to db
    for res in results:
        c.execute('''
            INSERT INTO daily_recommendations 
            (date, stock_id, score, win_rate, expected_min, expected_max, recommended_tp, sl_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (today, res['stock_id'], res['score'], res['probability'], res['expected_min'], res['expected_max'], res['tp'], res['sl_price']))
    
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup_event():
    init_db()
    # Schedule job every 5 mins between 9:00 - 13:30 (simulated)
    scheduler.add_job(job_scan_market, 'interval', minutes=5)
    scheduler.start()
    
    # Run once manually on startup for testing so we have data
    job_scan_market()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

@app.get("/api/market-status")
def api_market_status():
    today = datetime.date.today().isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM market_status WHERE date = ?', (today,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"status": "UNKNOWN", "message": "Market not scanned yet"}

@app.get("/api/recommendations")
def api_recommendations():
    today = datetime.date.today().isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM daily_recommendations WHERE date = ? ORDER BY win_rate DESC LIMIT 10', (today,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows
