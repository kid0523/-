import yfinance as yf
import pandas as pd
import datetime


def fetch_taiex_daily():
    """
    Fetch 0050.TW as a proxy for TAIEX to bypass Yahoo index rate limit.
    """
    try:
        taiex = yf.download("0050.TW", period="1mo", interval="1d", auto_adjust=True, progress=False)
        if taiex.empty or len(taiex) < 5:
            return None
        return taiex
    except Exception as e:
        print("TaiEx fetch error:", e)
        return None

def get_market_status(taiex_df: pd.DataFrame) -> dict:
    """
    Determine Market Status: STRONG / WEAK / NEUTRAL
    """
    if taiex_df is None or taiex_df.empty:
        return {"status": "UNKNOWN", "reason": "No data"}
        
    # extract Close correctly. If multi-index, we access the 'Close' 
    # For a single ticker, it's a simple column 'Close' or multi-index depending on yfinance version.
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
    
    # 簡易判斷：若漲>0% 且 站上5MA 考慮強勢；跌<0 且 跌破5MA 弱勢
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

def fetch_stock_history(tickers: list, days: int=30):
    """
    Fetch recent daily data to calculate 20-day historically 
    like Momentum, 5MA, Volume, Reversal.
    """
    try:
        data = yf.download(tickers, period="2mo", interval="1d", group_by="ticker", auto_adjust=True, progress=False)
        return data
    except Exception as e:
        print("Fetch history error:", e)
        return pd.DataFrame()
