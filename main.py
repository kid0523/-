from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from scraper import fetch_taiex_daily, get_market_status, fetch_stock_history, fetch_finmind_data
from strategy import evaluate_stock
from database import init_db, get_db, get_scan_index, update_scan_index
import datetime
import json
import sqlite3

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.api_route("/", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok"}


scheduler = BackgroundScheduler()

def clear_old_recommendations():
    print(f"[{datetime.datetime.now()}] 15:00 PM Trigger: Clearing yesterday's data & Resetting Scan Index to 0")
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM daily_recommendations')
    conn.commit()
    conn.close()
    update_scan_index(0)
    print(f"[{datetime.datetime.now()}] 舊的有價證券推薦清單已清空。")

def job_scan_market():
    """
    Midnight Rolling Scanner: 
    Every 15 minutes, fetch next 50 stocks from tickers.json.
    """
    try:
        with open('tickers.json', 'r') as f:
            tickers = json.load(f)
    except Exception as e:
        print("無法讀取 tickers.json：", e)
        return
        
    total_tickers = len(tickers)
    if total_tickers == 0: return
    
    current_idx = get_scan_index()
    if current_idx >= total_tickers:
        print(f"[{datetime.datetime.now()}] Daily scan finished. Resting until 15:00 tomorrow.")
        return
        
    end_idx = current_idx + 50
    batch = tickers[current_idx:end_idx]
    
    print(f"[{datetime.datetime.now()}] Rolling Scan Started: {current_idx} to {end_idx-1} (Total: {total_tickers})")
    
    for ticker in batch:
        try:
            df = fetch_finmind_data(ticker, days=40)
            if df is not None and not df.empty:
                res = evaluate_stock(df)
                if res.get('candidate'):
                    conn = get_db()
                    c = conn.cursor()
                    today = datetime.date.today().isoformat()
                    c.execute('''
                        INSERT INTO daily_recommendations (date, stock_id, score, win_rate, expected_max, recommended_tp, sl_price)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        today,
                        ticker,
                        res.get('score', 0),
                        res['probability'],
                        res['expected_max'],
                        res['tp'],
                        res['sl_price']
                    ))
                    conn.commit()
                    conn.close()
                    print(f"[!] 發現強烈推薦潛力股：{ticker}")
        except Exception as e:
            print(f"Error evaluating ticker {ticker}: {e}")

    new_idx = end_idx
    update_scan_index(new_idx)
    print(f"[{datetime.datetime.now()}] Batch Scan Completed. Next start index: {new_idx}")

@app.on_event("startup")
def startup_event():
    init_db()
    # Schedule job every 5 mins between 9:00 - 13:30 (simulated)
    scheduler.add_job(job_scan_market, 'interval', minutes=15)
    scheduler.add_job(clear_old_recommendations, 'cron', hour=15, minute=0)
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
    # Because we do midnight scanning, "today's" recommendations might be generated yesterday night 
    # or today morning. Since we DELETE at 15:00, we can just return ALL rows currently in the tabel!
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM daily_recommendations ORDER BY win_rate DESC LIMIT 30')
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

@app.api_route("/api/evaluate/{stock_id}", methods=["GET"])
def api_evaluate_stock(stock_id: str):
    """
    On-Demand stock evaluator. Fetches 40 days history and returns the report card.
    """
    import pandas as pd
    from scraper import fetch_realtime_twse
    
    stock_code = stock_id.replace('.TW', '')
    df = fetch_finmind_data(stock_code, days=40)
    if df is None or df.empty:
        return {"error": "無法取得該股票的歷史資料", "candidate": False}
        
    # Inject Real-time Data
    rt_data = fetch_realtime_twse(stock_code)
    if rt_data:
        # FinMind usually fetches up to yesterday closing, or today closing if market closed.
        # We enforce injecting the realtime price as "today"
        today_ts = pd.Timestamp(datetime.date.today())
        
        df.loc[today_ts] = {
            'Close': rt_data['price'],
            'Volume': rt_data['volume'],
            'Open': rt_data['open'],
            'High': rt_data['high'],
            'Low': rt_data['low']
        }
        
    res = evaluate_stock(df)
    res['stock_id'] = stock_id
    return res
