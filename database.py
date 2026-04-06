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
            sl_price REAL,
            checklist TEXT DEFAULT '{}'
        )
    ''')
    
    # Store daily market status
    c.execute('''
        CREATE TABLE IF NOT EXISTS market_status (
            date TEXT PRIMARY KEY,
            status TEXT,
            taiex_close REAL,
            recommendation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            checklist_json TEXT DEFAULT '{}'
        )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS scan_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        last_index INTEGER DEFAULT 0
    )
    ''')
    
    # Initialize the single row for state if it doesn't exist
    c.execute('INSERT OR IGNORE INTO scan_state (id, last_index) VALUES (1, 0)')
    
    conn.commit()
    conn.close()

def get_scan_index():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT last_index FROM scan_state WHERE id = 1')
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def update_scan_index(idx: int):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE scan_state SET last_index = ? WHERE id = 1', (idx,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
