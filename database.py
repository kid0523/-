import sqlite3
import os

DB_PATH = 'trading.db'

def is_postgres():
    return bool(os.environ.get("DATABASE_URL"))

def get_db():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        import psycopg2
        from psycopg2.extras import DictCursor
        conn = psycopg2.connect(db_url)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def execute_query(conn, query, params=()):
    """
    Abstracts differences in parameter formatting (sqlite uses ?, postgres uses %s).
    Also attaches a dictionary-like cursor.
    """
    _is_pg = is_postgres()
    
    if _is_pg:
        import psycopg2.extras
        c = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        query = query.replace('?', '%s')
    else:
        c = conn.cursor()
        
    c.execute(query, params)
    return c

def init_db():
    conn = get_db()
    _is_pg = is_postgres()
    
    # We must use execute_query to get a cursor, but creating tables doesn't need DictCursor.
    c = conn.cursor()
    
    id_col = "id SERIAL PRIMARY KEY" if _is_pg else "id INTEGER PRIMARY KEY AUTOINCREMENT"
    
    # trades table to track simulated user trades
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS trades (
            {id_col},
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
    if _is_pg:
        c.execute('INSERT INTO scan_state (id, last_index) VALUES (1, 0) ON CONFLICT DO NOTHING')
    else:
        c.execute('INSERT OR IGNORE INTO scan_state (id, last_index) VALUES (1, 0)')
    
    conn.commit()
    conn.close()

def get_scan_index():
    conn = get_db()
    c = execute_query(conn, 'SELECT last_index FROM scan_state WHERE id = 1')
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def update_scan_index(idx: int):
    conn = get_db()
    c = execute_query(conn, 'UPDATE scan_state SET last_index = ? WHERE id = 1', (idx,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()

