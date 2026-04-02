import requests
import pandas as pd
import datetime

def fetch_finmind_data(stock_id: str, days: int = 40) -> pd.DataFrame:
    """
    Helper function to access FinMind API for TaiwanStockPrice.
    """
    try:
        start_date = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id={stock_id}&start_date={start_date}"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get('status') == 200 and data.get('data'):
            df = pd.DataFrame(data['data'])
            # 轉換為大寫首字母以符合原本 yfinance 的相容格式
            df.rename(columns={
                'close': 'Close', 
                'max': 'High', 
                'min': 'Low', 
                'Trading_Volume': 'Volume', 
                'open': 'Open', 
                'date': 'Date'
            }, inplace=True)
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            return df
        return None
    except Exception as e:
        print(f"FinMind fetch error for {stock_id}:", e)
        return None

def fetch_taiex_daily():
    """
    Fetch 0050.TW as a proxy for TAIEX to bypass Yahoo index rate limit,
    now using FinMind open API.
    """
    return fetch_finmind_data("0050", days=20)

def get_market_status(taiex_df: pd.DataFrame) -> dict:
    """
    Determine Market Status: STRONG / WEAK / VOLATILE
    """
    if taiex_df is None or taiex_df.empty:
        return {"status": "UNKNOWN", "reason": "No data"}
        
    close_series = taiex_df['Close']
    if len(close_series.shape) > 1:
        close_series = close_series.iloc[:, 0]
        
    recent = close_series.tail(5)
    if len(recent) < 5:
        return {"status": "UNKNOWN", "reason": "Insufficient data"}
        
    current_close = float(recent.iloc[-1])
    prev_close = float(recent.iloc[-2])
    ma5 = float(recent.mean())
    
    pct_change = (current_close - prev_close) / prev_close
    
    # rule: 站上5MA, 漲跌幅等
    is_above_ma5 = current_close > ma5
    
    if is_above_ma5 and pct_change > 0:
        status = "STRONG"
    elif not is_above_ma5 and pct_change < 0:
        status = "WEAK"
    else:
        status = "VOLATILE"
        
    return {
        "status": status,
        "taiex_close": current_close,
        "ma5": ma5,
        "pct_change": pct_change,
        "is_above_ma5": is_above_ma5
    }

def fetch_stock_history(tickers: list, days: int=40):
    """
    Fetch recent daily data to calculate 20-day heuristics.
    Instead of yfinance MultiIndex, this returns a dictionary mapping ticker to DataFrame.
    """
    results = {}
    for ticker in tickers:
        stock_id = ticker.replace('.TW', '')
        df = fetch_finmind_data(stock_id, days=days)
        if df is not None and not df.empty:
            results[ticker] = df
    
    return results
