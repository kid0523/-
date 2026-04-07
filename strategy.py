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
    
    if prev_close == 0:
        return {"candidate": False, "reason": "Data error: prev_close is 0"}
    
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
    
    # Checklist
    checklist = {
        "has_dropped_10": bool(has_dropped_10),
        "no_new_low": bool(no_new_low),
        "vol_surge": bool(vol_surge),
        "above_5ma": bool(above_5ma),
        "gained_2pct": bool(gained_2pct)
    }

    # Phase 1: Candidate Pool Filter
    is_candidate = has_dropped_10 and no_new_low and vol_surge and above_5ma and gained_2pct
    
    if not is_candidate:
        return {"candidate": False, "reason": "未滿足球員初選條件（詳見檢核表）", "checklist": checklist, "current_price": current_close}
        
    # Phase 2: Scoring (Max 100)
    score = 0
    
    # 1. Volume Surge Intensity (Max 30)
    if current_vol > (avg_vol_5 * 3):
        score += 30
    elif current_vol > (avg_vol_5 * 2):
        score += 20
    elif vol_surge: # > 1.5x
        score += 10
        
    # 2. Price Momentum (Max 30)
    if today_change >= 0.07:
        score += 30
    elif today_change >= 0.04:
        score += 20
    elif gained_2pct: # > 2%
        score += 10
        
    # 3. Moving Average Divergence (Max 20)
    bias_5ma = (current_close - ma5) / ma5 if ma5 > 0 else 0
    if bias_5ma <= 0.04:
        score += 20
    elif bias_5ma <= 0.08:
        score += 10
        
    # 4. Trend & RSI (Max 20)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    try:
        current_rsi = float(rsi.iloc[-1])
    except Exception:
        current_rsi = 50.0
    
    ma10 = float(df['Close'].tail(10).mean())
    trend_ok = current_close > ma10
    rsi_ok = current_rsi > 60
    
    if trend_ok and rsi_ok:
        score += 20
    elif trend_ok or current_rsi > 50:
        score += 10
        
    # Rule: 必須達到 60 分才能在首頁推薦
    if score < 60:
        return {"candidate": False, "reason": f"未達推薦標準 (得 {score} 分，門檻 60 分)", "checklist": checklist, "current_price": current_close}
        
    # Phase 3: Convert Score to Probability & Expected Range
    if score >= 90:
        prob = 0.65
        exp_min, exp_max = 0.04, 0.08
        tp = 0.05
    elif score >= 75:
        prob = 0.60
        exp_min, exp_max = 0.03, 0.05
        tp = 0.04
    else: # 60~74
        prob = 0.55
        exp_min, exp_max = 0.02, 0.04
        tp = 0.03

    return {
        "candidate": True,
        "score": score,
        "probability": prob,
        "expected_min": exp_min,
        "expected_max": exp_max,
        "tp": tp,
        "current_price": current_close,
        "sl_price": current_close * 0.98, # -2% fixed stop loss
        "checklist": checklist
    }

def apply_institutional_score(res: dict, inst_data: dict) -> dict:
    """
    Applies score modifications based on institutional investors' net buy/sell.
    """
    if not res.get('candidate'):
        return res
        
    foreign = inst_data.get('foreign_net', 0)
    trust = inst_data.get('trust_net', 0)
    
    foreign_lots = foreign // 1000
    trust_lots = trust // 1000
    
    checklist = res.get('checklist', {})
    
    score_adj = 0
    chip_status = f"籌碼面：近一月外資 {foreign_lots}張 / 投信 {trust_lots}張"
    
    if foreign_lots > 0 and trust_lots > 0:
        score_adj += 20
        checklist[chip_status] = "土洋雙買 (大幅加分)"
    elif foreign_lots > 300 or trust_lots > 300:
        score_adj += 10
        checklist[chip_status] = "強勢法人囤貨 (加分)"
    elif foreign_lots < -1500 or trust_lots < -800:
        score_adj -= 15
        checklist[chip_status] = "遭遇主力倒貨 (高度警戒)"
    else:
        checklist[chip_status] = "籌碼動向無明顯異常"
        
    old_score = res.get('score', 0)
    new_score = old_score + score_adj
    res['score'] = min(new_score, 100) # Cap at 100
    
    if res['score'] < 60:
        res['candidate'] = False
        res['reason'] = f"法人賣壓過重，綜合評價降至 {res['score']} 分而被淘汰。"
        
    return res
