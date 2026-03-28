import sqlite3
import os

DB_PATH = 'trading.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # trades table to track simulated user trades
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            stock_id TEXT,
            entry_price REAL,
            exit_price REAL,
            tp_price REAL,
            sl_price REAL,
            status TEXT, 
            result_type TEXT, 
            theoretical_tp BOOLEAN
        )
    ''')
    
    # recommendations cached for the day
    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_recommendations (
            date TEXT,
            stock_id TEXT,
            score INTEGER,
            win_rate REAL,
            expected_min REAL,
            expected_max REAL,
            recommended_tp REAL,
            sl_price REAL
        )
    ''')
    
    # Store daily market status
    c.execute('''
        CREATE TABLE IF NOT EXISTS market_status (
            date TEXT PRIMARY KEY,
            status TEXT,
            taiex_close REAL,
            up_count INTEGER,
            down_count INTEGER
        )
    ''')
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
