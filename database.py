"""
庫存管理系統 — SQLite + FastAPI
Replaces Google Sheets version (blocked by corporate network)
"""
import sqlite3, os, json
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path

# On Render, DB lives on persistent disk at /data
DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "inventory.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    sku TEXT UNIQUE,
    quantity INTEGER NOT NULL DEFAULT 0,
    unit TEXT DEFAULT '件',
    unit_price REAL DEFAULT 0,
    min_stock INTEGER DEFAULT 5,
    location TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    type TEXT NOT NULL CHECK(type IN ('in','out','adjust')),
    quantity INTEGER NOT NULL,
    note TEXT DEFAULT '',
    application_id INTEGER REFERENCES applications(id),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_type TEXT NOT NULL CHECK(app_type IN ('withdraw','deposit')),
    department TEXT NOT NULL DEFAULT '',
    applicant_name TEXT NOT NULL DEFAULT '',
    reason TEXT DEFAULT '',
    items_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    processed_by TEXT DEFAULT 'AI',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- Default categories
INSERT OR IGNORE INTO categories (name) VALUES ('未分類');
INSERT OR IGNORE INTO categories (name) VALUES ('食品');
INSERT OR IGNORE INTO categories (name) VALUES ('飲品');
INSERT OR IGNORE INTO categories (name) VALUES ('日用品');
INSERT OR IGNORE INTO categories (name) VALUES ('電子產品');
INSERT OR IGNORE INTO categories (name) VALUES ('其他');
"""

@contextmanager
def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)

if __name__ == "__main__":
    init_db()
    print("Database initialized:", DB_PATH)
