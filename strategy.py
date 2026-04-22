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
    
    # ---------------- 核心選股 (T+0 當沖強勢動能版) ---------------- #
    # 條件 1：接近 20 日高點 (距離最高點不到 5%)，確保為強勢股
    max_20 = float(recent_20['High'].max())
    near_high = (current_close >= max_20 * 0.95)
    
    # 條件 2：今日為強勢實體紅K，且收在相對高點 (收盤價為今日波動之上半部)
    current_open = float(recent_20['Open'].iloc[-1])
    current_high = float(recent_20['High'].iloc[-1])
    current_low = float(recent_20['Low'].iloc[-1])
    is_red_candle = (current_close > current_open) and (current_close > prev_close)
    if current_high > current_low:
        close_position = (current_close - current_low) / (current_high - current_low)
    else:
        close_position = 0.0
    closing_strong = close_position > 0.6  # 留上影線不可太長
    
    # 條件 3：具備基本流動性 (5日均量 > 500 張 = 500000 股)
    avg_vol_5 = float(recent_5['Volume'].mean()) 
    liquid_enough = avg_vol_5 > 500000

    # 條件 4：避免追高接盤（過濾已連續兩天上漲之標的）
    # 日線資料 df 結算至昨日(T-1)。若 T-1 與 T-2 兩天皆呈現連漲，今日(T日)買進極易遭遇獲利了結賣壓。
    prev2_close = float(recent_20['Close'].iloc[-3])
    t1_gain = (current_close - prev_close) / prev_close
    t2_gain = (prev_close - prev2_close) / prev2_close
    
    # 定義連續爆拉：連兩天大於 2%，或連兩天皆漲且累積漲幅 > 8%
    is_consecutive_surge = (t1_gain > 0.02 and t2_gain > 0.02) or \
                           (t1_gain > 0 and t2_gain > 0 and (current_close - prev2_close) / prev2_close > 0.08)
    not_overextended = not is_consecutive_surge
    
    # Checklist
    checklist = {
        "near_high": bool(near_high),
        "is_red_candle": bool(is_red_candle),
        "closing_strong": bool(closing_strong),
        "not_overextended": bool(not_overextended)
    }

    # Phase 1: Candidate Pool Filter - T+0 強勢動能改版
    is_candidate = near_high and is_red_candle and closing_strong and liquid_enough and not_overextended
    
    if not is_candidate:
        return {"candidate": False, "reason": "未滿足球員初選條件（未呈現逼近創高且強勢收盤之動能特徵）", "checklist": checklist, "current_price": current_close}
        
    # Phase 2: Scoring (Max 100)
    score = 0
    
    # 1. 爆出天量，當沖流動性最重要 (Max 30)
    current_vol = float(recent_20['Volume'].iloc[-1])
    if current_vol > (avg_vol_5 * 2.5):
        score += 30
    elif current_vol > (avg_vol_5 * 1.5):
        score += 15
        
    # 2. 強勢跳升力道 (Max 30)
    today_change = (current_close - prev_close) / prev_close
    if today_change >= 0.06:
        score += 30
    elif today_change >= 0.04:
        score += 20
    elif today_change >= 0.02:
        score += 10
        
    # 3. 均線多頭排列 (底部剛放量突破) (Max 20)
    ma5 = float(recent_5['Close'].mean())
    ma10 = float(df['Close'].tail(10).mean())
    ma20 = float(recent_20['Close'].mean())
    if ma5 > ma10 and ma10 > ma20:
        score += 20
    elif ma5 > ma10:
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
    
    if current_rsi > 70:
        score += 20
    elif current_rsi > 60:
        score += 10
        
    # Rule: 必須達到 60 分才能在首頁推薦
    if score < 60:
        return {"candidate": False, "reason": f"未達推薦標準 (得 {score} 分，門檻 60 分)", "checklist": checklist, "current_price": current_close}
        
    # Phase 3: Convert Score to Probability & Expected Range (原有高目標)
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
    
    # 【使用者要求】：三大法人也沒有持續賣出 (若大幅度拋售則直接淘汰)
    if foreign_lots < -1500 or trust_lots < -800:
        res['candidate'] = False
        res['reason'] = f"遭遇法人持續倒貨賣出，不宜抄底而被淘汰。"
        return res
        
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

def apply_margin_score(res: dict, stock_id: str, margin_cache: dict) -> dict:
    """
    Applies score modifications based on Margin Trading data from TWSE OpenAPI.
    """
    if not res.get('candidate'):
        return res
        
    stock_margin = margin_cache.get(str(stock_id)) if margin_cache else None
    
    if not stock_margin:
        return res
        
    short_bal = stock_margin.get('short_balance', 0)
    margin_ratio = stock_margin.get('margin_ratio', 0)
    
    checklist = res.get('checklist', {})
    score_adj = 0
    margin_status = f"融資券：融資使用率 {margin_ratio*100:.1f}% / 融券餘額 {short_bal}張"
    
    # 短線上融券餘額偏高容易醞釀軋空
    if short_bal > 3000:
        score_adj += 20
        checklist[margin_status] = "高融券具潛在軋空動能 (大幅加分)"
    elif short_bal > 1000:
        score_adj += 10
        checklist[margin_status] = "融券偏高有軋空機會 (加分)"
        
    # 融資使用率過大代表散戶多、籌碼凌亂
    if margin_ratio > 0.6:
        score_adj -= 15
        checklist[margin_status] = "融資浮額過高、籌碼凌亂 (高度警戒)"
    elif margin_ratio > 0.4:
        score_adj -= 5
        checklist[margin_status] = "融資使用偏多、留意賣壓 (扣分)"
    elif margin_ratio < 0.2:
        score_adj += 5
        checklist[margin_status] = "融資低水位、籌碼乾淨 (加分)"
        
    if margin_status not in checklist:
        checklist[margin_status] = "融資券表現平穩無異常"
        
    old_score = res.get('score', 0)
    new_score = old_score + score_adj
    res['score'] = min(max(new_score, 0), 100) # Cap at 100, floor at 0
    
    if res['score'] < 60:
        res['candidate'] = False
        res['reason'] = f"融資籌碼凌亂，綜合評價降至 {res['score']} 分而被淘汰。"
        
    return res
