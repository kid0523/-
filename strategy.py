import pandas as pd

def evaluate_stock(df: pd.DataFrame) -> dict:
    """
    Evaluate a single stock's historical DataFrame.
    Returns: dict {"candidate": bool, "score": int, "probability": float, ...}
    """
    if df is None or len(df) < 20:
        return {"candidate": False, "reason": "Not enough data"}
        
    recent_20 = df.tail(20)
    recent_5 = df.tail(5)
    recent_3 = df.tail(3)
    
    current_close = float(recent_20['Close'].iloc[-1])
    prev_close = float(recent_20['Close'].iloc[-2])
    
    # Condition 1: 近20天曾下跌10%
    max_20 = float(recent_20['High'].max())
    min_20 = float(recent_20['Low'].min())
    drop_pct = (min_20 - max_20) / max_20
    has_dropped_10 = drop_pct <= -0.10
    
    # Condition 2: 最近3天未創新低
    min_3 = float(recent_3['Low'].min())
    old_min = float(df.iloc[-20:-3]['Low'].min()) if len(df) >= 20 else min_20
    no_new_low = min_3 >= old_min
    
    # Condition 3: 今日成交量 > 5日均量 * 1.5
    current_vol = float(recent_20['Volume'].iloc[-1])
    avg_vol_5 = float(recent_5['Volume'].mean()) 
    vol_surge = current_vol > (avg_vol_5 * 1.5)
    
    # Condition 4: 股價站上5MA
    ma5 = float(recent_5['Close'].mean())
    above_5ma = current_close > ma5
    
    # Condition 5: 今日漲幅 > 2%
    today_change = (current_close - prev_close) / prev_close
    gained_2pct = today_change > 0.02
    
    # Phase 1: Candidate Pool Filter
    is_candidate = has_dropped_10 and no_new_low and vol_surge and above_5ma and gained_2pct
    
    if not is_candidate:
        return {"candidate": False, "reason": "Filter conditions not met"}
        
    # Phase 2: Scoring
    score = 0
    if vol_surge: score += 20
    if above_5ma: score += 20
    if gained_2pct: score += 20
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    current_rsi = float(rsi.iloc[-1])
    if current_rsi > 50:
        score += 20
        
    # Trend
    ma10 = float(df['Close'].tail(10).mean())
    if current_close > ma10:
        score += 20
        
    # Phase 3: Convert Score to Probability & Expected Range
    if score >= 80:
        prob = 0.60
        exp_min, exp_max = 0.04, 0.08
        tp = 0.05
    elif score >= 70:
        prob = 0.55
        exp_min, exp_max = 0.02, 0.05
        tp = 0.03
    elif score >= 60:
        prob = 0.50
        exp_min, exp_max = 0.01, 0.03
        tp = 0.02
    else:
        prob = 0.0
        exp_min, exp_max = 0.0, 0.0
        tp = 0.0
        
    # Rule: 只保留機率 >= 55%
    if prob < 0.55:
        return {"candidate": False, "reason": "Probability < 55%"}

    return {
        "candidate": True,
        "score": score,
        "probability": prob,
        "expected_min": exp_min,
        "expected_max": exp_max,
        "tp": tp,
        "current_price": current_close,
        "sl_price": current_close * 0.98 # -2% fixed stop loss
    }
