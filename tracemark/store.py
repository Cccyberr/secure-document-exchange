"""SQLite storage: platform accounts, provenance registry, social feed, police cases, warrants."""
import json, os, sqlite3, threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, username TEXT, full_name TEXT, phone TEXT,
  email TEXT, city TEXT, ip TEXT, device TEXT, signup TEXT);
CREATE TABLE IF NOT EXISTS registry (record_id TEXT PRIMARY KEY, envelope TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS generations (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, record_id TEXT,
  prompt TEXT, style TEXT, file TEXT, created_at TEXT, psnr REAL);
CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT, handle TEXT, caption TEXT, file TEXT,
  via TEXT, parent INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS cases (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, file TEXT,
  complainant TEXT, complaint TEXT, status TEXT, analysis TEXT, record_id TEXT, identity TEXT,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS warrants (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER, record_id TEXT,
  reason TEXT, officer TEXT, status TEXT, warrant TEXT, judge TEXT, created_at TEXT, decided_at TEXT);
"""

DEMO_ACCOUNTS = [
    # Entirely fictional people for the demo.
    ("PF-10231", "dark_lens_77", "Vivek Raghav ", "+91 90000 11231", "dark.lens77@example.com",
     "Kollam, Kerala", "117.211.84.19", "Android 14 · Redmi Note 12", "2026-03-14"),
    ("PF-20488", "art_by_meera", "Meera Nair", "+91 90000 22488", "meera.art@example.com",
     "Thiruvananthapuram, Kerala", "59.92.140.7", "Windows 11 · Chrome 141", "2025-11-02"),
    ("PF-30915", "x_anon_creator", "Rohit Das", "+91 90000 33915", "anon.creator@example.com",
     "Kochi, Kerala", "106.203.57.66", "iPhone 15 · Safari", "2026-08-21"),
]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.img_dir = os.path.join(data_dir, "images")
        os.makedirs(self.img_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "tracemark.db")
        self.lock = threading.Lock()
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self._conn() as c:
            c.executescript(SCHEMA)
            if not c.execute("SELECT 1 FROM accounts").fetchone():
                c.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?)", DEMO_ACCOUNTS)

    def reset(self):
        with self.lock, self._conn() as c:
            for t in ("registry", "generations", "posts", "cases", "warrants"):
                c.execute(f"DELETE FROM {t}")
            c.execute("DELETE FROM sqlite_sequence")
        for f in os.listdir(self.img_dir):
            os.remove(os.path.join(self.img_dir, f))

    def q(self, sql, args=(), one=False):
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        rows = [dict(r) for r in rows]
        return (rows[0] if rows else None) if one else rows

    def x(self, sql, args=()):
        with self.lock, self._conn() as c:
            cur = c.execute(sql, args)
            return cur.lastrowid

    # images
    def save_image(self, name, data: bytes):
        with open(os.path.join(self.img_dir, name), "wb") as f:
            f.write(data)
        return name

    def image_path(self, name):
        return os.path.join(self.img_dir, name)

    def read_image(self, name) -> bytes:
        with open(self.image_path(name), "rb") as f:
            return f.read()

    # registry
    def register(self, record_id_hex, env):
        self.x("INSERT INTO registry VALUES (?,?,?)", (record_id_hex, json.dumps(env), now()))

    def lookup(self, record_id_hex):
        r = self.q("SELECT envelope FROM registry WHERE record_id=?", (record_id_hex,), one=True)
        return json.loads(r["envelope"]) if r else None
