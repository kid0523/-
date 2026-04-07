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

def fetch_realtime_twse(stock_id: str) -> dict:
    """
    Fetch real-time price and volume from TWSE (handles both TSE and OTC stocks via combined query).
    """
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw|otc_{stock_id}.tw"
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, timeout=5, verify=False)
        data = r.json()
        for item in data.get("msgArray", []):
            if item.get("c") == str(stock_id):
                current_price = item.get("z")
                if current_price == '-':
                    current_price = item.get("b", "_").split("_")[0]
                    if not current_price or current_price == '-':
                        current_price = item.get("y")
                
                return {
                    "price": float(current_price),
                    "volume": float(item.get("v", 0)) * 1000, # TWSE 'v' is in lots (1000 shares)
                    "open": float(item.get("o", current_price)) if item.get("o") != '-' else float(current_price),
                    "high": float(item.get("h", current_price)) if item.get("h") != '-' else float(current_price),
                    "low": float(item.get("l", current_price)) if item.get("l") != '-' else float(current_price)
                }
    except Exception as e:
        print(f"TWSE Realtime fetch error for {stock_id}:", e)
    return None

def fetch_market_status():
    """
    Fetches the TAIEX index (t00.tw) to determine market status.
    Returns HIGH, WEAK, or VOLATILE.
    """
    try:
        url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw"
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, timeout=5, verify=False)
        data = r.json()
        if "msgArray" in data and len(data["msgArray"]) > 0:
            item = data["msgArray"][0]
            current = float(item.get("z", item.get("y", 0)))
            open_idx = float(item.get("o", item.get("y", 0)))
            y_close = float(item.get("y", 0))
            
            # Simple heuristic
            if current > y_close and current >= open_idx:
                status = "STRONG"
            elif current < y_close and current <= open_idx:
                status = "WEAK"
            else:
                status = "VOLATILE"
                
            return {"status": status, "taiex_close": current}
    except Exception as e:
        print(f"Failed to fetch market status: {e}")
    
    return {"status": "UNKNOWN", "taiex_close": 0}

def fetch_institutional_data(stock_id: str, days: int = 30) -> dict:
    """
    Fetches the institutional investors buy/sell over the last 'days' days.
    Returns a dict with net buys for Foreign_Investor and Investment_Trust.
    """
    try:
        start_date = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={stock_id}&start_date={start_date}"
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, timeout=10, verify=False)
        data = r.json()
        
        foreign_net = 0
        trust_net = 0
        
        if data.get('status') == 200 and data.get('data'):
            for item in data['data']:
                buy = int(item.get('buy', 0))
                sell = int(item.get('sell', 0))
                net = buy - sell
                
                name = item.get('name', '')
                if name == 'Foreign_Investor':
                    foreign_net += net
                elif name == 'Investment_Trust':
                    trust_net += net
                    
        return {"foreign_net": foreign_net, "trust_net": trust_net}
    except Exception as e:
        print(f"FinMind Institutional fetch error for {stock_id}: {e}", flush=True)
        return {"foreign_net": 0, "trust_net": 0}
