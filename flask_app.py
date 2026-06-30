"""
DMA 紀念品庫存管理系統 — Flask Backend (WSGI-native for PythonAnywhere)
"""
import sqlite3, json, re, io, csv, os, base64, urllib.request
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, send_file, make_response, g

BASE = Path(__file__).parent
DB = BASE / "inventory.db"
STATIC = BASE / "static"
UPLOAD_DIR = BASE / "uploads"
IMAGES_DIR = STATIC / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dma-souvenir-2026-secret")

# ── Supervisor password (stored in DB) ──
STAFF_PASSWORD = "smg2026"

# ═══════════════════════════════
# DATABASE
# ═══════════════════════════════
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(str(DB))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(str(DB))
    db.executescript("""
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
            image_url TEXT DEFAULT '',
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
            processed_by TEXT DEFAULT 'system',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        INSERT OR IGNORE INTO categories (name) VALUES ('未分類');
        INSERT OR IGNORE INTO categories (name) VALUES ('食品');
        INSERT OR IGNORE INTO categories (name) VALUES ('飲品');
        INSERT OR IGNORE INTO categories (name) VALUES ('日用品');
        INSERT OR IGNORE INTO categories (name) VALUES ('電子產品');
        INSERT OR IGNORE INTO categories (name) VALUES ('其他');
    """)
    db.close()

init_db()

# ═══════════════════════════════
# AUTH HELPER
# ═══════════════════════════════
def require_staff(f):
    @wraps(f)
    def wrapper(*args, **kw):
        pwd = request.headers.get("X-Staff-Password") or request.args.get("password") or ""
        if pwd != STAFF_PASSWORD:
            return jsonify({"error": "Unauthorized"}), 403
        return f(*args, **kw)
    return wrapper

# ═══════════════════════════════
# STATIC PAGES
# ═══════════════════════════════
@app.route("/")
def index():
    return send_file(str(STATIC / "index.html"))

@app.route("/catalog")
def catalog_page():
    return send_file(str(STATIC / "catalog_cart.html"))

@app.route("/admin")
def admin_page():
    return send_file(str(STATIC / "admin_login.html"))

# ═══════════════════════════════
# AUTH
# ═══════════════════════════════
@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(force=True)
    if data.get("password") == STAFF_PASSWORD:
        return jsonify({"status": "ok", "role": "staff"})
    return jsonify({"status": "error", "message": "密碼錯誤"}), 401

# ═══════════════════════════════
# CATEGORIES (public)
# ═══════════════════════════════
@app.route("/api/categories")
def list_categories():
    db = get_db()
    rows = db.execute("SELECT * FROM categories ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/categories", methods=["POST"])
@require_staff
def create_category():
    data = request.get_json(force=True)
    db = get_db()
    try:
        cur = db.execute("INSERT INTO categories (name) VALUES (?)", (data["name"],))
        db.commit()
        return jsonify({"id": cur.lastrowid, "name": data["name"]})
    except:
        return jsonify({"error": "分類已存在"}), 400

@app.route("/api/categories/<int:cat_id>", methods=["DELETE"])
@require_staff
def delete_category(cat_id):
    db = get_db()
    db.execute("UPDATE products SET category_id=1 WHERE category_id=?", (cat_id,))
    db.execute("DELETE FROM categories WHERE id=? AND id > 6", (cat_id,))
    db.commit()
    return jsonify({"ok": True})

# ═══════════════════════════════
# CATALOG (public - for applicants)
# ═══════════════════════════════
@app.route("/api/catalog")
def catalog_data():
    cat_id = request.args.get("category_id", type=int)
    db = get_db()
    sql = """SELECT p.*, c.name as category_name 
             FROM products p LEFT JOIN categories c ON p.category_id=c.id 
             WHERE p.quantity > 0"""
    params = []
    if cat_id:
        sql += " AND p.category_id = ?"
        params.append(cat_id)
    sql += " ORDER BY c.name, p.name"
    rows = db.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])

# ═══════════════════════════════
# PRODUCTS (staff only for write)
# ═══════════════════════════════
@app.route("/api/products")
def list_products():
    search = request.args.get("search", "")
    cat_id = request.args.get("category_id", type=int)
    low_stock = request.args.get("low_stock", "").lower() == "true"
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    db = get_db()
    sql = """SELECT p.*, c.name as category_name 
             FROM products p LEFT JOIN categories c ON p.category_id=c.id WHERE 1=1"""
    params = []
    if search:
        sql += " AND (p.name LIKE ? OR p.sku LIKE ? OR p.location LIKE ?)"
        q = f"%{search}%"
        params += [q, q, q]
    if cat_id:
        sql += " AND p.category_id = ?"
        params.append(cat_id)
    if low_stock:
        sql += " AND p.quantity <= p.min_stock"

    count = db.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
    sql += " ORDER BY p.updated_at DESC LIMIT ? OFFSET ?"
    params += [per_page, (page - 1) * per_page]
    rows = db.execute(sql, params).fetchall()
    return jsonify({"items": [dict(r) for r in rows], "total": count, "page": page, "per_page": per_page})

@app.route("/api/products/<int:pid>")
def get_product(pid):
    db = get_db()
    row = db.execute(
        "SELECT p.*, c.name as category_name FROM products p LEFT JOIN categories c ON p.category_id=c.id WHERE p.id=?",
        (pid,)
    ).fetchone()
    if not row:
        return jsonify({"error": "產品不存在"}), 404
    return jsonify(dict(row))

@app.route("/api/products", methods=["POST"])
@require_staff
def create_product():
    data = request.get_json(force=True)
    db = get_db()
    cur = db.execute("""
        INSERT INTO products (name,category_id,sku,quantity,unit,unit_price,min_stock,location,notes)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (data["name"], data.get("category_id", 1), data.get("sku", ""),
          data.get("quantity", 0), data.get("unit", "件"), data.get("unit_price", 0),
          data.get("min_stock", 5), data.get("location", ""), data.get("notes", "")))
    pid = cur.lastrowid
    if data.get("quantity", 0) != 0:
        db.execute("INSERT INTO transactions (product_id,type,quantity,note) VALUES (?,?,?,?)",
                   (pid, 'in', abs(data["quantity"]), '初始庫存'))
    db.commit()
    return jsonify({"id": pid, **data})

@app.route("/api/products/<int:pid>", methods=["PUT"])
@require_staff
def update_product(pid):
    data = request.get_json(force=True)
    db = get_db()
    fields = {k: v for k, v in data.items() if v is not None}
    if not fields:
        return jsonify({"error": "沒有要更新的欄位"}), 400
    sets = ", ".join(f"{k}=?" for k in fields)
    sql = f"UPDATE products SET {sets}, updated_at=datetime('now','localtime') WHERE id=?"
    db.execute(sql, list(fields.values()) + [pid])
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/products/<int:pid>", methods=["DELETE"])
@require_staff
def delete_product(pid):
    db = get_db()
    db.execute("DELETE FROM transactions WHERE product_id=?", (pid,))
    db.execute("DELETE FROM products WHERE id=?", (pid,))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/products/batch-update", methods=["POST"])
@require_staff
def batch_update():
    updates = request.get_json(force=True)
    db = get_db()
    count = 0
    for u in updates:
        pid = u.pop("id", None)
        if not pid or not u:
            continue
        sets = ", ".join(f"{k}=?" for k in u)
        sql = f"UPDATE products SET {sets}, updated_at=datetime('now','localtime') WHERE id=?"
        db.execute(sql, list(u.values()) + [pid])
        count += 1
    db.commit()
    return jsonify({"ok": True, "updated": count})

# ═══════════════════════════════
# STOCK MOVEMENTS
# ═══════════════════════════════
@app.route("/api/products/<int:pid>/stock-in", methods=["POST"])
@require_staff
def stock_in(pid):
    data = request.get_json(force=True)
    db = get_db()
    p = db.execute("SELECT quantity FROM products WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify({"error": "產品不存在"}), 404
    qty = data.get("quantity", 0)
    db.execute("UPDATE products SET quantity=quantity+?, updated_at=datetime('now','localtime') WHERE id=?",
               (qty, pid))
    db.execute("INSERT INTO transactions (product_id,type,quantity,note) VALUES (?,?,?,?)",
               (pid, 'in', qty, data.get("note", "")))
    db.commit()
    return jsonify({"ok": True, "new_qty": p["quantity"] + qty})

@app.route("/api/products/<int:pid>/stock-out", methods=["POST"])
@require_staff
def stock_out(pid):
    data = request.get_json(force=True)
    db = get_db()
    p = db.execute("SELECT quantity FROM products WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify({"error": "產品不存在"}), 404
    qty = data.get("quantity", 0)
    if p["quantity"] < qty:
        return jsonify({"error": "庫存不足"}), 400
    db.execute("UPDATE products SET quantity=quantity-?, updated_at=datetime('now','localtime') WHERE id=?",
               (qty, pid))
    db.execute("INSERT INTO transactions (product_id,type,quantity,note) VALUES (?,?,?,?)",
               (pid, 'out', qty, data.get("note", "")))
    db.commit()
    return jsonify({"ok": True, "new_qty": p["quantity"] - qty})

# ═══════════════════════════════
# APPLICATION SUBMIT (public)
# ═══════════════════════════════
@app.route("/api/applications/submit", methods=["POST"])
def submit_application():
    data = request.get_json(force=True)
    app_type = data.get("app_type", "withdraw")
    items = data.get("items", [])
    
    if app_type not in ('withdraw', 'deposit'):
        return jsonify({"error": "類型必須是 withdraw 或 deposit"}), 400
    if not items or all(it.get("quantity", 0) <= 0 for it in items):
        return jsonify({"error": "請至少填寫一項物品及數量"}), 400

    results = []
    db = get_db()
    txn_type = 'in' if app_type == 'deposit' else 'out'

    for item in items:
        name = item.get("name", "").strip()
        qty = item.get("quantity", 0)
        if not name or qty <= 0:
            continue

        # Try exact match (normalize)
        norm_name = re.sub(r'[\s\-_/\(\)（）]', '', name).lower()
        matched = None
        match_type = ""

        all_products = db.execute("SELECT * FROM products").fetchall()
        for row in all_products:
            r = dict(row)
            r_norm = re.sub(r'[\s\-_/\(\)（）]', '', r['name']).lower()
            if r_norm == norm_name:
                matched = r
                match_type = "完全匹配"
                break

        # Partial LIKE match
        if not matched:
            row = db.execute("SELECT * FROM products WHERE name LIKE ? LIMIT 1",
                           (f"%{name}%",)).fetchone()
            if row:
                matched = dict(row)
                match_type = "近似匹配"

        # Create new
        if not matched:
            cur = db.execute("INSERT INTO products (name, category_id, quantity, unit) VALUES (?, 1, 0, '件')",
                           (name,))
            matched = {"id": cur.lastrowid, "name": name, "quantity": 0}
            match_type = "新產品"

        pid = matched["id"]
        old_qty = matched["quantity"]

        if app_type == 'deposit':
            db.execute("UPDATE products SET quantity=quantity+?, updated_at=datetime('now','localtime') WHERE id=?",
                      (qty, pid))
            new_qty = old_qty + qty
        else:
            if old_qty < qty:
                return jsonify({"error": f"「{name}」庫存不足 (現有: {old_qty}, 需要: {qty})"}), 400
            db.execute("UPDATE products SET quantity=quantity-?, updated_at=datetime('now','localtime') WHERE id=?",
                      (qty, pid))
            new_qty = old_qty - qty

        results.append({
            "item": name, "qty": qty, "match": match_type,
            "product_id": pid, "old_qty": old_qty, "new_qty": new_qty,
            "action": "存入" if app_type == 'deposit' else "申領"
        })

    items_json = json.dumps(items, ensure_ascii=False)
    cur = db.execute(
        "INSERT INTO applications (app_type, department, applicant_name, reason, items_json, status) VALUES (?,?,?,?,?,'approved')",
        (app_type, data.get("department", ""), data.get("applicant_name", ""),
         data.get("reason", ""), items_json))
    app_id = cur.lastrowid

    for r in results:
        db.execute(
            "INSERT INTO transactions (product_id, type, quantity, note, application_id) VALUES (?,?,?,?,?)",
            (r["product_id"], txn_type, r["qty"],
             f"申請#{app_id}: {data.get('applicant_name', '')} - {data.get('reason', '')}", app_id))

    db.commit()
    return jsonify({
        "application_id": app_id,
        "status": "approved",
        "results": results,
        "summary": f"系統自動處理 {len(results)} 項物品 ({'存入' if app_type == 'deposit' else '申領'})"
    })

@app.route("/api/applications")
def list_applications():
    limit = request.args.get("limit", 20, type=int)
    db = get_db()
    rows = db.execute("SELECT * FROM applications ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    apps = []
    for r in rows:
        d = dict(r)
        d["items"] = json.loads(d["items_json"])
        del d["items_json"]
        apps.append(d)
    return jsonify(apps)

# ═══════════════════════════════
# STATS (public)
# ═══════════════════════════════
@app.route("/api/stats")
def get_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    low = db.execute("SELECT COUNT(*) FROM products WHERE quantity <= min_stock AND min_stock > 0").fetchone()[0]
    total_qty = db.execute("SELECT SUM(quantity) FROM products").fetchone()[0] or 0
    total_value = db.execute("SELECT SUM(quantity * unit_price) FROM products").fetchone()[0] or 0
    return jsonify({
        "total_products": total, "low_stock": low,
        "total_quantity": total_qty, "total_value": round(total_value, 2)
    })

# ═══════════════════════════════
# TRANSACTIONS
# ═══════════════════════════════
@app.route("/api/products/<int:pid>/transactions")
def product_transactions(pid):
    limit = request.args.get("limit", 50, type=int)
    db = get_db()
    rows = db.execute(
        "SELECT * FROM transactions WHERE product_id=? ORDER BY created_at DESC LIMIT ?",
        (pid, limit)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/transactions/recent")
def recent_transactions():
    limit = request.args.get("limit", 100, type=int)
    db = get_db()
    rows = db.execute("""
        SELECT t.*, p.name as product_name 
        FROM transactions t LEFT JOIN products p ON t.product_id=p.id
        ORDER BY t.created_at DESC LIMIT ?
    """, (limit,)).fetchall()
    return jsonify([dict(r) for r in rows])

# ═══════════════════════════════
# IMAGE UPLOAD
# ═══════════════════════════════
@app.route("/api/upload-image", methods=["POST"])
@require_staff
def upload_image():
    pid = request.form.get("product_id", type=int)
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file"}), 400
    
    # Validate file extension
    ext = Path(file.filename).suffix.lower()
    allowed = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'}
    if ext not in allowed:
        return jsonify({"error": f"不支援的檔案格式：{ext}。支援：JPG, PNG, GIF, WebP, BMP, TIFF"}), 400
    
    # Validate it's actually an image using Pillow
    try:
        from PIL import Image
        file_bytes = file.read()
        img = Image.open(io.BytesIO(file_bytes))
        img.verify()  # verify it's a valid image
        file.seek(0)  # reset for saving
    except Exception as e:
        return jsonify({"error": f"無法識別圖片：{str(e)}"}), 400
    
    fname = f"prod_{pid}_{int(__import__('time').time())}{ext}"
    save_path = IMAGES_DIR / fname
    file.save(str(save_path))
    
    # Also create thumbnail for catalog
    try:
        from PIL import Image
        thumb = Image.open(str(save_path))
        thumb.thumbnail((400, 400), Image.LANCZOS)
        thumb_path = IMAGES_DIR / f"thumb_{fname}"
        thumb.save(str(thumb_path), quality=85)
    except Exception:
        pass
    
    url = f"/static/images/{fname}"
    db = get_db()
    db.execute("UPDATE products SET image_url=?, updated_at=datetime('now','localtime') WHERE id=?",
              (url, pid))
    db.commit()
    return jsonify({"ok": True, "image_url": url, "filename": fname})

# ═══════════════════════════════
# OCR / PHOTO RECOGNITION
# ═══════════════════════════════
@app.route("/api/ocr/recognize", methods=["POST"])
def ocr_recognize():
    """Upload a photo (PNG/JPG) → recognize text/product info using AI vision"""
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "請上傳圖片檔案"}), 400
    
    ext = Path(file.filename).suffix.lower()
    allowed = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'}
    if ext not in allowed:
        return jsonify({"error": f"不支援的格式：{ext}。支援 PNG, JPG, WebP, BMP, TIFF"}), 400
    
    content = file.read()
    
    # Validate image with Pillow
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        img.verify()
        # Reopen for actual processing
        img = Image.open(io.BytesIO(content))
        w, h = img.size
        fmt = img.format
    except Exception as e:
        return jsonify({"error": f"無法讀取圖片：{str(e)}"}), 400
    
    # Save uploaded file
    ts = int(__import__('time').time())
    save_path = UPLOAD_DIR / f"ocr_{ts}{ext}"
    save_path.write_bytes(content)
    
    # Encode as base64 for AI vision API
    img_b64 = base64.b64encode(content).decode()
    
    # Try AI vision recognition via the app's AI API
    ocr_result = None
    try:
        ocr_result = _call_vision_ocr(img_b64)
    except Exception as e:
        ocr_result = {"error": str(e)}
    
    return jsonify({
        "ok": True,
        "image": {
            "width": w, "height": h,
            "format": fmt,
            "size_bytes": len(content),
            "saved_path": str(save_path)
        },
        "ocr": ocr_result
    })

def _call_vision_ocr(img_b64):
    """Call external AI vision API to recognize text in image"""
    prompt = """你是一個 OCR 辨識助手。請仔細觀察這張圖片，提取所有可見的中文和英文文字。
    
如果圖片中有：
- 物品/產品名稱 → 提取
- 數量/數字 → 提取
- 條碼/編號 → 提取
- 任何其他文字 → 提取

請以 JSON 格式回覆：
{
  "text": "圖片中的所有文字",
  "items": [{"name": "辨識到的物品名稱", "text": "相關文字"}],
  "summary": "簡短描述圖片內容"
}

只回覆 JSON，不要加任何解釋。"""
    
    # Try using the app's configured AI API
    api_url = os.environ.get("AI_API_URL", "")
    api_key = os.environ.get("AI_API_KEY", "")
    
    if not api_url or not api_key:
        # Fall back to basic Pillow analysis
        return {"text": "", "items": [], "summary": "AI API 未設定 (set AI_API_URL / AI_API_KEY env vars)", "mode": "fallback"}
    
    payload = {
        "model": os.environ.get("AI_MODEL", "gpt-4o"),
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]
        }],
        "temperature": 0.1,
        "max_tokens": 1000
    }
    
    req = urllib.request.Request(api_url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        })
    
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        raw = resp["choices"][0]["message"]["content"]
    except Exception as e:
        return {"text": "", "items": [], "summary": f"API 呼叫失敗：{str(e)}", "mode": "error"}
    
    # Try to parse JSON from response
    try:
        jm = re.search(r'\{[\s\S]*\}', raw)
        if jm:
            parsed = json.loads(jm.group())
            parsed["mode"] = "ai_vision"
            return parsed
    except Exception:
        pass
    
    return {"text": raw, "items": [], "summary": "", "mode": "ai_text"}

@app.route("/api/ocr/test", methods=["GET"])
def ocr_test():
    """Test endpoint — returns available image formats"""
    formats = []
    try:
        from PIL import Image
        formats = [
            {"ext": ".jpg", "mime": "image/jpeg", "supported": True},
            {"ext": ".png", "mime": "image/png", "supported": True},
            {"ext": ".gif", "mime": "image/gif", "supported": True},
            {"ext": ".webp", "mime": "image/webp", "supported": True},
            {"ext": ".bmp", "mime": "image/bmp", "supported": True},
            {"ext": ".tiff", "mime": "image/tiff", "supported": True},
        ]
    except ImportError:
        formats = [{"ext": "*", "supported": False, "error": "Pillow not installed"}]
    return jsonify({
        "service": "OCR 拍照識別",
        "formats": formats,
        "ai_enabled": bool(os.environ.get("AI_API_KEY")),
        "endpoints": {
            "recognize": "POST /api/ocr/recognize (multipart: file=@photo.jpg)",
            "upload_image": "POST /api/upload-image (multipart: file=@photo.jpg + product_id=N)"
        }
    })

# ═══════════════════════════════
# EXPORT CSV
# ═══════════════════════════════
@app.route("/api/export/csv")
def export_csv():
    db = get_db()
    rows = db.execute("""
        SELECT p.name, c.name as category, p.sku, p.quantity, p.unit, 
               p.unit_price, p.min_stock, p.location, p.notes
        FROM products p LEFT JOIN categories c ON p.category_id=c.id
        ORDER BY c.name, p.name
    """).fetchall()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["名稱", "分類", "SKU", "庫存", "單位", "單價", "安全存量", "位置", "備註"])
    for r in rows:
        cw.writerow([r[i] for i in range(len(r))])
    output = io.BytesIO(si.getvalue().encode('utf-8-sig'))
    output.seek(0)
    return send_file(output, mimetype="text/csv",
                     as_attachment=True, download_name="inventory_export.csv")

# ═══════════════════════════════
# PDF GENERATION
# ═══════════════════════════════
from fpdf import FPDF

FONT_PATH = BASE / "fonts" / "msjh.ttc"
FONT_BOLD_PATH = BASE / "fonts" / "msjhbd.ttc"
_NOTO_PATH = BASE / "fonts" / "NotoSansCJKtc-Regular.otf"
_NOTO_BOLD_PATH = BASE / "fonts" / "NotoSansCJKtc-Bold.otf"

# Windows fallback
_WIN_FONT = Path("C:/Windows/Fonts/msjh.ttc")
_WIN_FONT_BOLD = Path("C:/Windows/Fonts/msjhbd.ttc")
# Linux / PythonAnywhere fallback
_PA_FONT = Path("/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf")
_PA_FONT2 = Path("/usr/share/fonts/truetype/arphic/uming.ttc")

if not FONT_PATH.exists() and _WIN_FONT.exists():
    FONT_PATH = _WIN_FONT
if not FONT_BOLD_PATH.exists() and _WIN_FONT_BOLD.exists():
    FONT_BOLD_PATH = _WIN_FONT_BOLD
if not FONT_PATH.exists() and _NOTO_PATH.exists():
    FONT_PATH = _NOTO_PATH
if not FONT_BOLD_PATH.exists() and _NOTO_BOLD_PATH.exists():
    FONT_BOLD_PATH = _NOTO_BOLD_PATH
if not FONT_PATH.exists() and _PA_FONT.exists():
    FONT_PATH = _PA_FONT
if not FONT_BOLD_PATH.exists() and _PA_FONT2.exists():
    FONT_BOLD_PATH = _PA_FONT2

class AppPDF(FPDF):
    _cjk = False

    def __init__(self):
        super().__init__('P', 'mm', 'A4')
        font_loaded = False
        # Try fonts in priority order
        for fpath in [
            str(FONT_PATH),
            str(_PA_FONT),
            "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf",
            "/usr/share/fonts/truetype/arphic/uming.ttc",
        ]:
            try:
                if Path(fpath).exists():
                    self.add_font("cjk", "", fpath)
                    self._cjk = True
                    font_loaded = True
                    break
            except Exception:
                continue
        if not font_loaded and FONT_PATH.exists():
            try:
                self.add_font("cjk", "", str(FONT_PATH))
                self._cjk = True
            except Exception:
                pass
        if FONT_BOLD_PATH.exists():
            try:
                self.add_font("cjk", "B", str(FONT_BOLD_PATH))
            except Exception:
                pass
        self.set_auto_page_break(True, 15)

    def _font(self, style="", size=12):
        if self._cjk:
            self.set_font("cjk", style, size)
        else:
            self.set_font("Helvetica", style, size)

    def footer(self):
        # No auto footer — we draw version number manually in draw()
        pass

    def _hline(self, x1, y, x2):
        """Draw horizontal line"""
        self.line(x1, y, x2, y)

    def _vline(self, x, y1, y2):
        """Draw vertical line"""
        self.line(x, y1, x, y2)

    def draw(self, app_type, products, dept="", applicant="", reason=""):
        """Draw the standard application form — 100% match to reference with frame borders"""
        self.add_page()
        LM = 34  # left margin mm
        self.set_left_margin(LM)
        self.set_right_margin(25)
        w = 151  # usable width
        RM = LM + w  # right edge
        self.set_draw_color(0, 0, 0)
        LW = 0.35  # line width
        self.set_line_width(LW)
        
        # ═══ TOP-RIGHT: 申請編號 ═══
        self._font("", 9)
        self.set_text_color(0, 0, 0)
        self.cell(w, 5, "申請編號:__________", align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(8)
        
        # ═══ TITLE ═══
        self._font("B", 18)
        self.set_text_color(0, 0, 0)
        self.cell(w, 8, "紀念品申請表", align="C", new_x="LMARGIN", new_y="NEXT")
        self._font("", 10)
        self.cell(w, 5, "申領/存入", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(10)
        
        # Record Y positions for frame drawing
        content_top = self.get_y()
        
        # ═══ 基本資料 SECTION HEADER ═══
        sec1_y1 = self.get_y()
        self.set_fill_color(217, 217, 217)
        self._font("B", 11)
        self.cell(w, 8, "  基本資料", border=0, fill=True, new_x="LMARGIN", new_y="NEXT")
        sec1_y2 = self.get_y()
        self.ln(3)
        
        # ═══ FORM FIELDS ═══
        self._font("", 10)
        self.set_text_color(0, 0, 0)
        # Row 1: 申請部門 + 申請人姓名
        field1_y1 = self.get_y()
        self.cell(20, 8, "申請部門")
        self.cell(55, 8, dept if dept else "_____________________", align="L")
        self.cell(24, 8, "申請人姓名")
        self.cell(52, 8, applicant if applicant else "_____________________", align="L")
        field1_y2 = self.get_y() + 8
        self.ln(10)
        # Row 2: 申請事由
        field2_y1 = self.get_y()
        self.cell(20, 8, "申請事由")
        self.cell(131, 8, reason if reason else "__________________________________________________", align="L")
        field2_y2 = self.get_y() + 8
        self.ln(10)
        # Row 3: 分類選項
        field3_y1 = self.get_y()
        self.cell(20, 8, "分類選項")
        wc = "■" if app_type == "withdraw" else "□"
        dc = "■" if app_type == "deposit" else "□"
        self.cell(35, 8, f"{wc} 申領")
        self.cell(35, 8, f"{dc} 存入")
        field3_y2 = self.get_y() + 8
        self.ln(10)
        
        # ═══ TABLE ═══
        col_num = 12
        col_name = 105
        col_qty = 34
        rh = 8
        table_top = self.get_y()
        
        # Header
        self._font("B", 10)
        self.set_fill_color(230, 230, 230)
        self.cell(col_num, rh, "項目", border=0, fill=True, align="C")
        self.cell(col_name, rh, "  物品名稱", border=0, fill=True, align="L")
        self.cell(col_qty, rh, "數量", border=0, fill=True, align="C")
        self.ln()
        table_header_bottom = self.get_y()
        
        # Rows 1-13
        self._font("", 10)
        total_rows = 13
        for i in range(total_rows):
            num = str(i + 1)
            if i < len(products):
                p = products[i]
                name = p["name"][:30]
                self.cell(col_num, rh, num, border=0, align="C")
                self.cell(col_name, rh, f"  {name}", border=0, align="L")
                self.cell(col_qty, rh, "", border=0, align="C")
            else:
                self.cell(col_num, rh, num, border=0, align="C")
                self.cell(col_name, rh, "", border=0, align="L")
                self.cell(col_qty, rh, "", border=0, align="C")
            self.ln()
        table_bottom = self.get_y()
        
        self.ln(10)
        
        # ═══ SIGNATURES ═══
        sig_top = self.get_y()
        sig_w = 75
        sig_mid = LM + sig_w
        self._font("B", 10)
        self.cell(sig_w, 7, "申請人", align="C")
        self.cell(sig_w, 7, "部門主管", align="C")
        self.ln(10)
        
        self._font("", 10)
        self.cell(12, 7, "簽名")
        self.cell(sig_w - 12, 7, "___________________", align="L")
        self.cell(12, 7, "簽名")
        self.cell(sig_w - 12, 7, "___________________", align="L")
        self.ln(12)
        
        self.cell(12, 7, "日期")
        self.cell(sig_w - 12, 7, "___________________", align="L")
        self.cell(12, 7, "日期")
        self.cell(sig_w - 12, 7, "___________________", align="L")
        self.ln(14)
        
        # ═══ FOOTER ═══
        self._font("", 8)
        self.set_text_color(100, 100, 100)
        self.cell(w, 5, "版本2：2023/1/1", align="R", new_x="LMARGIN", new_y="NEXT")
        content_bottom = self.get_y()
        
        # ═══════════════════════════════════
        # DRAW EXPLICIT BORDER LINES (overlay)
        # ═══════════════════════════════════
        self.set_line_width(LW)
        self.set_draw_color(0, 0, 0)
        
        # ── Outer frame around entire content ──
        self.rect(LM, content_top, w, content_bottom - content_top)
        
        # ── 基本資料 section box ──
        self._hline(LM, sec1_y1, RM)
        self._hline(LM, sec1_y2, RM)
        
        # ── Field row dividers ──
        # 申請部門 | 申請人姓名 split
        col_split = LM + 20 + 55  # after 申請部門 field
        self._vline(col_split, sec1_y2, field3_y2)
        
        # ── 基本資料 -> Table separator ──
        self._hline(LM, field3_y2, RM)
        
        # ── TABLE GRID ──
        # Vertical lines for all 3 columns
        col1_right = LM + col_num
        col2_right = col1_right + col_name
        # Full vertical lines through entire table height
        self._vline(LM, table_top, table_bottom)           # left edge
        self._vline(col1_right, table_top, table_bottom)    # after 項目
        self._vline(col2_right, table_top, table_bottom)    # after 物品名稱
        self._vline(RM, table_top, table_bottom)            # right edge
        
        # Horizontal lines: header bottom + all 13 rows
        self._hline(LM, table_header_bottom, RM)
        row_y = table_header_bottom
        for _ in range(total_rows):
            row_y += rh
            self._hline(LM, row_y, RM)
        
        # ── Signature area borders ──
        sig_bottom = self.get_y() - 19  # approximate
        # Column split in signature area
        self._vline(sig_mid, sig_top, sig_bottom)
        
        return self

@app.route("/api/applications/generate-pdf")
def generate_pdf():
    product_ids = request.args.get("product_ids", "")
    app_type = request.args.get("app_type", "withdraw")
    dept = request.args.get("department", "")
    applicant = request.args.get("applicant", "")
    reason = request.args.get("reason", "")

    if not product_ids:
        return jsonify({"error": "請選擇至少一件物品"}), 400

    ids = [int(x.strip()) for x in product_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return jsonify({"error": "無效的物品 ID"}), 400

    db = get_db()
    ph = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT p.*, c.name as category_name FROM products p LEFT JOIN categories c ON p.category_id=c.id WHERE p.id IN ({ph}) ORDER BY c.name, p.name",
        ids).fetchall()
    products = [dict(r) for r in rows]

    if not products:
        return jsonify({"error": "找不到指定的物品"}), 404

    pdf = AppPDF()
    pdf.draw(app_type, products, dept, applicant, reason)
    out = io.BytesIO()
    pdf.output(out)
    out.seek(0)
    return send_file(out, mimetype="application/pdf",
                     as_attachment=True, download_name="DMA_紀念品申請表.pdf")

@app.route("/api/applications/generate-pdf-with-qty", methods=["POST"])
def generate_pdf_with_qty():
    """Generate PDF with specific quantities per item — with explicit frame borders"""
    data = request.get_json(force=True)
    app_type = data.get("app_type", "withdraw")
    dept = data.get("department", "")
    applicant = data.get("applicant_name", "")
    reason = data.get("reason", "")
    items = data.get("items", [])

    if not items:
        return jsonify({"error": "請至少選擇一件物品"}), 400

    # Load product info for each item
    db = get_db()
    products = []
    for it in items:
        row = db.execute("SELECT * FROM products WHERE id=?", (it["product_id"],)).fetchone()
        if row:
            p = dict(row)
            p["request_qty"] = it.get("quantity", 0)
            products.append(p)

    if not products:
        return jsonify({"error": "找不到指定的物品"}), 404

    pdf = AppPDF()
    pdf.add_page()
    LM = 34
    pdf.set_left_margin(LM)
    pdf.set_right_margin(25)
    w = 151
    RM = LM + w
    LW = 0.35
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(LW)
    
    # TOP-RIGHT: 申請編號
    pdf._font("", 9)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(w, 5, "申請編號:__________", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    
    # TITLE
    pdf._font("B", 18)
    pdf.cell(w, 8, "紀念品申請表", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf._font("", 10)
    pdf.cell(w, 5, "申領/存入", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    
    content_top = pdf.get_y()
    
    # 基本資料 HEADER
    sec1_y1 = pdf.get_y()
    pdf.set_fill_color(217, 217, 217)
    pdf._font("B", 11)
    pdf.cell(w, 8, "  基本資料", border=0, fill=True, new_x="LMARGIN", new_y="NEXT")
    sec1_y2 = pdf.get_y()
    pdf.ln(3)
    
    # FORM FIELDS
    pdf._font("", 10)
    pdf.set_text_color(0, 0, 0)
    field1_y1 = pdf.get_y()
    pdf.cell(20, 8, "申請部門")
    pdf.cell(55, 8, dept if dept else "_____________________", align="L")
    pdf.cell(24, 8, "申請人姓名")
    pdf.cell(52, 8, applicant if applicant else "_____________________", align="L")
    field1_y2 = pdf.get_y() + 8
    pdf.ln(10)
    field2_y1 = pdf.get_y()
    pdf.cell(20, 8, "申請事由")
    pdf.cell(131, 8, reason if reason else "__________________________________________________", align="L")
    field2_y2 = pdf.get_y() + 8
    pdf.ln(10)
    field3_y1 = pdf.get_y()
    pdf.cell(20, 8, "分類選項")
    wc = "■" if app_type == "withdraw" else "□"
    dc = "■" if app_type == "deposit" else "□"
    pdf.cell(35, 8, f"{wc} 申領")
    pdf.cell(35, 8, f"{dc} 存入")
    field3_y2 = pdf.get_y() + 8
    pdf.ln(10)
    
    # TABLE
    col_num = 12; col_name = 105; col_qty = 34; rh = 8
    table_top = pdf.get_y()
    
    pdf._font("B", 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(col_num, rh, "項目", border=0, fill=True, align="C")
    pdf.cell(col_name, rh, "  物品名稱", border=0, fill=True, align="L")
    pdf.cell(col_qty, rh, "數量", border=0, fill=True, align="C")
    pdf.ln()
    table_header_bottom = pdf.get_y()
    
    pdf._font("", 10)
    total_rows = 13
    for i in range(total_rows):
        num = str(i + 1)
        if i < len(products):
            p = products[i]
            name = p["name"][:30]
            qty = str(p.get("request_qty", ""))
            pdf.cell(col_num, rh, num, border=0, align="C")
            pdf.cell(col_name, rh, f"  {name}", border=0, align="L")
            pdf.cell(col_qty, rh, qty, border=0, align="C")
        else:
            pdf.cell(col_num, rh, num, border=0, align="C")
            pdf.cell(col_name, rh, "", border=0, align="L")
            pdf.cell(col_qty, rh, "", border=0, align="C")
        pdf.ln()
    table_bottom = pdf.get_y()
    
    pdf.ln(10)
    
    # SIGNATURES
    sig_top = pdf.get_y()
    sig_w = 75
    sig_mid = LM + sig_w
    pdf._font("B", 10)
    pdf.cell(sig_w, 7, "申請人", align="C")
    pdf.cell(sig_w, 7, "部門主管", align="C")
    pdf.ln(10)
    
    pdf._font("", 10)
    pdf.cell(12, 7, "簽名")
    pdf.cell(sig_w - 12, 7, "___________________", align="L")
    pdf.cell(12, 7, "簽名")
    pdf.cell(sig_w - 12, 7, "___________________", align="L")
    pdf.ln(12)
    
    pdf.cell(12, 7, "日期")
    pdf.cell(sig_w - 12, 7, "___________________", align="L")
    pdf.cell(12, 7, "日期")
    pdf.cell(sig_w - 12, 7, "___________________", align="L")
    pdf.ln(14)
    
    # FOOTER
    pdf._font("", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(w, 5, "版本2：2023/1/1", align="R", new_x="LMARGIN", new_y="NEXT")
    content_bottom = pdf.get_y()
    
    # ═══════════════════════════════════
    # DRAW EXPLICIT BORDER LINES (overlay)
    # ═══════════════════════════════════
    pdf.set_line_width(LW)
    pdf.set_draw_color(0, 0, 0)
    
    # Outer frame
    pdf.rect(LM, content_top, w, content_bottom - content_top)
    
    # 基本資料 section
    pdf._hline(LM, sec1_y1, RM)
    pdf._hline(LM, sec1_y2, RM)
    
    # Field column split
    col_split = LM + 20 + 55
    pdf._vline(col_split, sec1_y2, field3_y2)
    
    # Table top border
    pdf._hline(LM, field3_y2, RM)
    
    # Table grid
    col1_right = LM + col_num
    col2_right = col1_right + col_name
    pdf._vline(LM, table_top, table_bottom)
    pdf._vline(col1_right, table_top, table_bottom)
    pdf._vline(col2_right, table_top, table_bottom)
    pdf._vline(RM, table_top, table_bottom)
    
    pdf._hline(LM, table_header_bottom, RM)
    row_y = table_header_bottom
    for _ in range(total_rows):
        row_y += rh
        pdf._hline(LM, row_y, RM)
    
    # Signature split
    sig_bottom = pdf.get_y() - 19
    pdf._vline(sig_mid, sig_top, sig_bottom)

    out = io.BytesIO()
    pdf.output(out)
    out.seek(0)
    return send_file(out, mimetype="application/pdf",
                     as_attachment=True, download_name="DMA_紀念品申請表.pdf")

# ═══════════════════════════════
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8709, debug=True)
