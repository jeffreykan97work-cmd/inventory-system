"""
紀念品倉存管理系統 v3 — SQLite + FastAPI
無需 Google Sheets，全本地自控
"""
import sqlite3, json, hashlib, os
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE = Path(__file__).parent
DB = BASE / "inventory.db"
STATIC = BASE / "static"

app = FastAPI(title="紀念品倉存管理系統 v3")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── DB Init ──
def init_db():
    with sqlite3.connect(str(DB)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                category TEXT DEFAULT '一般宣傳品',
                stock INTEGER DEFAULT 0,
                safe_stock INTEGER DEFAULT 10,
                image_url TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id TEXT UNIQUE NOT NULL,
                applicant TEXT NOT NULL,
                department TEXT NOT NULL,
                category TEXT NOT NULL,
                reason TEXT NOT NULL,
                items_json TEXT NOT NULL,
                status TEXT DEFAULT '待審批',
                approver TEXT DEFAULT '',
                apply_date TEXT DEFAULT (datetime('now','localtime')),
                approve_date TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO settings (key, value) VALUES ('supervisor_password', 'smg2026');
        """)
    # Seed items if empty
    with sqlite3.connect(str(DB)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        if count == 0:
            _seed_items(conn)

def _seed_items(conn):
    items = [
        ('不織布袋(深藍)', '一般宣傳品', 729), ('不織布袋(淺藍)', '一般宣傳品', 304),
        ('帆布袋(雲)', '一般宣傳品', 136), ('摺疊環保袋', '一般宣傳品', 1324),
        ('盒裝積木', '一般宣傳品', 617), ('立體吊飾', '一般宣傳品', 13),
        ('USB', '一般宣傳品', 196), ('晴雨傘', '一般宣傳品', 367),
        ('拉鏈袋', '一般宣傳品', 337), ('便利貼', '一般宣傳品', 562),
        ('風球圖案回型針', '一般宣傳品', 539), ('環保餐具', '一般宣傳品', 64),
        ('筆插筒', '一般宣傳品', 386), ('天氣筆記板', '一般宣傳品', 354),
        ('天氣教學板', '一般宣傳品', 154), ('卡通毛公仔(天兒)', '一般宣傳品', 29),
        ('風暴潮膠擦鉛筆(藍色)', '一般宣傳品', 3), ('風暴潮膠擦鉛筆(黃色)', '一般宣傳品', 6),
        ('風暴潮膠擦鉛筆(橙色)', '一般宣傳品', 6), ('風暴潮膠擦鉛筆(紅色)', '一般宣傳品', 14),
        ('風暴潮膠擦鉛筆(黑色)', '一般宣傳品', 19), ('退休紀念品', '一般宣傳品', 0),
        ('來來超市禮券(MOP100)', '一般宣傳品', 2), ('泰豐超市禮券(MOP100)', '一般宣傳品', 17),
        ('澳門科學館展覽中心門券', '一般宣傳品', 78), ('澳門科學館大文館門券', '一般宣傳品', 78),
        ('運動毛巾(新)', '一般宣傳品', 20), ('卡通索引貼', '一般宣傳品', 0),
        ('便携旅行衣夾', '一般宣傳品', 157), ('數據線收納帶', '一般宣傳品', 14),
        ('3D天氣圖案USB', '一般宣傳品', 0), ('筆記本', '一般宣傳品', 0),
        ('天氣筆記板-舊', '一般宣傳品', 0), ('風球多色原子筆', '一般宣傳品', 0),
        ('手寫亞克力板', '一般宣傳品', 0), ('環保水樽(藍色)', '一般宣傳品', 0),
        ('環保水樽(紅色)', '一般宣傳品', 0), ('拍紙記事本', '一般宣傳品', 0),
        ('環保袋', '一般宣傳品', 0), ('運動毛巾', '一般宣傳品', 0),
        ('便利貼套裝', '一般宣傳品', 0),
    ]
    conn.executemany("INSERT INTO items (name, category, stock) VALUES (?,?,?)", items)

init_db()

# ── Models ──
class AppReq(BaseModel):
    applicant: str
    department: str
    category: str
    reason: str
    items: list

class AuthReq(BaseModel):
    password: str

class ApproveReq(BaseModel):
    app_id: str
    action: str  # approve / reject
    approver: str

class StockReq(BaseModel):
    name: str
    stock: int

# ── Routes ──
@app.get("/")
async def root():
    return FileResponse(str(STATIC / "index.html"))

@app.get("/api/catalog")
async def catalog():
    with sqlite3.connect(str(DB)) as conn:
        rows = conn.execute("SELECT name, image_url FROM items ORDER BY name").fetchall()
    return [{"name": r[0], "image": r[1]} for r in rows]

@app.post("/api/apply")
async def apply(req: AppReq):
    with sqlite3.connect(str(DB)) as conn:
        num = conn.execute("SELECT COUNT(*) FROM applications WHERE app_id LIKE '%/2026'").fetchone()[0] + 1
        app_id = f"{num:03d}/2026"
        conn.execute(
            "INSERT INTO applications (app_id, applicant, department, category, reason, items_json) VALUES (?,?,?,?,?,?)",
            (app_id, req.applicant, req.department, req.category, req.reason, json.dumps(req.items, ensure_ascii=False))
        )
    return {"status": "submitted", "id": app_id, "message": f"申請 {app_id} 已提交，等待主管審批"}

@app.post("/api/login")
async def login(req: AuthReq):
    with sqlite3.connect(str(DB)) as conn:
        pwd = conn.execute("SELECT value FROM settings WHERE key='supervisor_password'").fetchone()
    if pwd and req.password == pwd[0]:
        return {"status": "ok", "role": "supervisor"}
    return {"status": "error", "message": "密碼錯誤"}

@app.get("/api/stock")
async def get_stock(password: str = ""):
    with sqlite3.connect(str(DB)) as conn:
        pwd = conn.execute("SELECT value FROM settings WHERE key='supervisor_password'").fetchone()
    if password != pwd[0]:
        raise HTTPException(403, "Unauthorized")
    with sqlite3.connect(str(DB)) as conn:
        rows = conn.execute("SELECT name, category, stock, safe_stock, image_url FROM items ORDER BY name").fetchall()
    return [{"name": r[0], "category": r[1], "stock": r[2], "safe": r[3], "image": r[4]} for r in rows]

@app.post("/api/stock/update")
async def update_stock(req: StockReq, password: str = ""):
    with sqlite3.connect(str(DB)) as conn:
        pwd = conn.execute("SELECT value FROM settings WHERE key='supervisor_password'").fetchone()
    if password != pwd[0]:
        raise HTTPException(403, "Unauthorized")
    with sqlite3.connect(str(DB)) as conn:
        conn.execute("UPDATE items SET stock=? WHERE name=?", (req.stock, req.name))
    return {"status": "ok"}

@app.get("/api/approvals")
async def approvals(password: str = ""):
    with sqlite3.connect(str(DB)) as conn:
        pwd = conn.execute("SELECT value FROM settings WHERE key='supervisor_password'").fetchone()
    if password != pwd[0]:
        raise HTTPException(403, "Unauthorized")
    with sqlite3.connect(str(DB)) as conn:
        rows = conn.execute("SELECT * FROM applications ORDER BY id DESC LIMIT 50").fetchall()
    return [{
        "app_id": r[1], "applicant": r[2], "department": r[3],
        "category": r[4], "reason": r[5], "items": json.loads(r[6]) if r[6] else [],
        "status": r[7], "approver": r[8], "apply_date": r[9], "approve_date": r[10]
    } for r in rows]

@app.post("/api/approve")
async def approve(req: ApproveReq, password: str = ""):
    with sqlite3.connect(str(DB)) as conn:
        pwd = conn.execute("SELECT value FROM settings WHERE key='supervisor_password'").fetchone()
    if password != pwd[0]:
        raise HTTPException(403, "Unauthorized")
    
    with sqlite3.connect(str(DB)) as conn:
        now = datetime.now().strftime("%Y-%m-%d")
        if req.action == "approve":
            conn.execute("UPDATE applications SET status='已通過', approver=?, approve_date=? WHERE app_id=?",
                        (req.approver, now, req.app_id))
            # Deduct stock
            row = conn.execute("SELECT items_json FROM applications WHERE app_id=?", (req.app_id,)).fetchone()
            if row and row[0]:
                items = json.loads(row[0])
                for it in items:
                    conn.execute("UPDATE items SET stock=MAX(0, stock-?) WHERE name=?", (it["qty"], it["name"]))
        else:
            conn.execute("UPDATE applications SET status='已拒絕', approver=?, approve_date=? WHERE app_id=?",
                        (req.approver, now, req.app_id))
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8760)
