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
async def health_check():
    return {"status": "ok"}


scheduler = BackgroundScheduler(timezone="Asia/Taipei")

def clear_old_recommendations():
    print(f"[{datetime.datetime.now()}] 15:00 PM Trigger: Clearing yesterday's data & Resetting Scan Index to 0", flush=True)
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM daily_recommendations')
    conn.commit()
    conn.close()
    update_scan_index(0)
    print(f"[{datetime.datetime.now()}] 舊的有價證券推薦清單已清空。", flush=True)

def intraday_survival_check():
    print(f"[{datetime.datetime.now()}] 09:30 AM Trigger: Intraday Survival Check Started", flush=True)
    from scraper import fetch_realtime_twse
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT stock_id FROM daily_recommendations WHERE score > 0")
    rows = c.fetchall()
    
    eliminated = 0
    for row in rows:
        ticker = row['stock_id']
        rt = fetch_realtime_twse(ticker)
        if rt:
            # Rule 1: Falling below Open price (Black candle out)
            # Rule 2: Fall from intraday high > 3%
            if rt['price'] < rt['open'] or (rt['high'] > 0 and (rt['price'] / rt['high']) < 0.97):
                c.execute("UPDATE daily_recommendations SET score = -50 WHERE stock_id = ?", (ticker,))
                print(f"Eliminated {ticker}: weakness detected. Price: {rt['price']}, Open: {rt['open']}", flush=True)
                eliminated += 1
                
    conn.commit()
    conn.close()
    print(f"[{datetime.datetime.now()}] Survival check complete. Eliminated {eliminated} dropping stocks.", flush=True)

def job_scan_market():
    """
    Midnight Rolling Scanner: 
    Every 15 minutes, fetch next 50 stocks from tickers.json.
    """
    try:
        with open('tickers.json', 'r') as f:
            tickers = json.load(f)
    except Exception as e:
        print("無法讀取 tickers.json：", e, flush=True)
        return
        
    total_tickers = len(tickers)
    if total_tickers == 0: return
    
    current_idx = get_scan_index()
    if current_idx >= total_tickers:
        print(f"[{datetime.datetime.now()}] Daily scan finished. Resting until 15:00 tomorrow.", flush=True)
        return
        
    end_idx = current_idx + 50
    batch = tickers[current_idx:end_idx]
    
    print(f"[{datetime.datetime.now()}] Rolling Scan Started: {current_idx} to {end_idx-1} (Total: {total_tickers})", flush=True)
    
    for ticker in batch:
        import time
        time.sleep(1.0) # 加上 1 秒延遲，避免連續請求造成 FinMind API 超時
        try:
            df = fetch_finmind_data(ticker, days=40)
            if df is not None and not df.empty:
                from strategy import evaluate_stock, apply_institutional_score
                from scraper import fetch_institutional_data
                
                res = evaluate_stock(df)
                if res.get('candidate'):
                    # Optimized: Only fetch chip data if technicals pass
                    inst_data = fetch_institutional_data(ticker, days=30)
                    res = apply_institutional_score(res, inst_data)
                    
                    if res.get('candidate'):
                        conn = get_db()
                        c = conn.cursor()
                        today = datetime.date.today().isoformat()
                        c.execute('''
                            INSERT INTO daily_recommendations (date, stock_id, score, win_rate, expected_max, recommended_tp, sl_price, checklist)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            today,
                            ticker,
                            res.get('score', 0),
                            res['probability'],
                            res['expected_max'],
                            res['tp'],
                            res['sl_price'],
                            json.dumps(res.get('checklist', {}))
                        ))
                        conn.commit()
                        conn.close()
                        print(f"[!] 發現強烈推薦潛力股：{ticker}", flush=True)
        except Exception as e:
            print(f"Error evaluating ticker {ticker}: {e}", flush=True)

    new_idx = end_idx
    update_scan_index(new_idx)
    print(f"[{datetime.datetime.now()}] Batch Scan Completed. Next start index: {new_idx}", flush=True)

@app.on_event("startup")
def startup_event():
    init_db()
    # Schedule job every 15 mins
    scheduler.add_job(job_scan_market, 'interval', minutes=15)
    scheduler.add_job(clear_old_recommendations, 'cron', hour=15, minute=0)
    scheduler.add_job(intraday_survival_check, 'cron', hour=9, minute=30)
    
    # Run once manually on startup in the background (prevent blocking Uvicorn startup)
    scheduler.add_job(job_scan_market, 'date', run_date=datetime.datetime.now())
    
    scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

@app.get("/api/market-status")
def api_market_status():
    from scraper import fetch_market_status
    return fetch_market_status()

@app.get("/api/recommendations")
def api_recommendations():
    # Because we do midnight scanning, "today's" recommendations might be generated yesterday night 
    # or today morning. Since we DELETE at 15:00, we can just return ALL rows currently in the tabel!
    conn = get_db()
    c = conn.cursor()
    # Read only surviving recommendations (score > 0)
    c.execute('SELECT * FROM daily_recommendations WHERE score > 0 ORDER BY score DESC, expected_max DESC LIMIT 10')
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
        
        # Smart Volume Projection Intraday!
        import datetime as dt
        # Use timezone without external pytz dependency
        taipei_tz = dt.timezone(dt.timedelta(hours=8))
        now = dt.datetime.now(taipei_tz)
        market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        market_close = now.replace(hour=13, minute=30, second=0, microsecond=0)
        
        vol = rt_data['volume']
        if market_open <= now <= market_close:
            elapsed_minutes = (now - market_open).total_seconds() / 60.0
            if elapsed_minutes > 0:
                projected_vol = vol * (270.0 / elapsed_minutes)
                vol = projected_vol # Substitute with projected final volume
                print(f"[Volume Prediction] {stock_code}: real={rt_data['volume']}, projected={vol}", flush=True)

        df.loc[today_ts] = {
            'Close': rt_data['price'],
            'Volume': vol,
            'Open': rt_data['open'],
            'High': rt_data['high'],
            'Low': rt_data['low']
        }
        
    from strategy import evaluate_stock, apply_institutional_score
    res = evaluate_stock(df)
    
    if res.get('candidate'):
        from scraper import fetch_institutional_data
        inst_data = fetch_institutional_data(stock_code, days=30)
        res = apply_institutional_score(res, inst_data)
        
    res['stock_id'] = stock_id
    return res
