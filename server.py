#!/usr/bin/env python3
import argparse
import email
import email.policy
import hashlib
import hmac
import html
import http.server
import json
import logging
import logging.handlers
import os
import re
import shutil
import sys
import time
import urllib.parse
import zipfile
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_ADMIN_PASSWORD_HASH = "4813494d137e1631bba301d5acab6e7bb7aa74ce1185d456565ef51d737677b2"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not cfg.get("admin_password_hash"):
            raise ValueError("missing hash")
        return cfg
    except (OSError, ValueError):
        cfg = {"admin_password_hash": DEFAULT_ADMIN_PASSWORD_HASH}
        save_config(cfg)
        return cfg


_CFG = load_config()
ADMIN_PASSWORD_HASH = _CFG["admin_password_hash"]
SESSION_SECRET = hashlib.sha256((ADMIN_PASSWORD_HASH + "share-session").encode()).hexdigest().encode()
SESSION_DAYS = 7
SESSION_RENEW = 24 * 3600
CHUNK = 5 * 1024 * 1024
UPLOAD_TTL = 10 * 60
RESERVE_TTL = 2 * 60
_LAST_CLEANUP = 0

FILES_DIR = os.path.join(BASE_DIR, "files")
UPLOADS_DIR = os.path.join(FILES_DIR, ".uploads")
QUOTA = int(_CFG.get("quota") or (10 * 1024 * 1024 * 1024))
PREFIX = "/share"


def set_quota(bytes_val):
    global QUOTA
    QUOTA = bytes_val
    cfg = load_config()
    cfg["quota"] = bytes_val
    save_config(cfg)

LOG = logging.getLogger("share")
if not LOG.handlers:
    LOG.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        _logdir = os.path.join(BASE_DIR, "logs")
        os.makedirs(_logdir, exist_ok=True)
        _fh = logging.handlers.TimedRotatingFileHandler(
            os.path.join(_logdir, "share.log"), when="midnight", interval=1, backupCount=7, encoding="utf-8")
        _fh.setFormatter(_fmt)
        LOG.addHandler(_fh)
    except OSError:
        pass
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    LOG.addHandler(_sh)

ICONS = {
    ".pdf": "📕", ".doc": "📘", ".docx": "📘", ".ppt": "📙", ".pptx": "📙",
    ".xls": "📗", ".xlsx": "📗", ".csv": "📗", ".txt": "📄", ".md": "📝",
    ".zip": "📦", ".rar": "📦", ".7z": "📦", ".gz": "📦", ".tar": "📦",
    ".mp3": "🎵", ".wav": "🎵", ".flac": "🎵", ".mp4": "🎬", ".mkv": "🎬",
    ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️", ".gif": "🖼️", ".webp": "🖼️",
    ".svg": "🖼️", ".exe": "⚙️", ".apk": "📱", ".iso": "💿",
}
DEFAULT_ICON = "📎"

TILE_BG = {
    ".pdf": "#fde2e2", ".doc": "#dbeafe", ".docx": "#dbeafe", ".ppt": "#fef3c7", ".pptx": "#fef3c7",
    ".xls": "#dcfce7", ".xlsx": "#dcfce7", ".csv": "#dcfce7", ".txt": "#eef2f7", ".md": "#eef2f7",
    ".zip": "#fef9c3", ".rar": "#fef9c3", ".7z": "#fef9c3", ".gz": "#fef9c3", ".tar": "#fef9c3",
    ".mp3": "#fce7f3", ".wav": "#fce7f3", ".flac": "#fce7f3", ".mp4": "#ede9fe", ".mkv": "#ede9fe",
    ".jpg": "#cffafe", ".jpeg": "#cffafe", ".png": "#cffafe", ".gif": "#cffafe", ".webp": "#cffafe",
    ".svg": "#cffafe", ".exe": "#e0e7ff", ".apk": "#e0e7ff", ".iso": "#f3e8ff",
}
DEFAULT_TILE = "#f1f5f9"
FOLDER_TILE = "#e6ddc6"


def U(path):
    return PREFIX + path


def admin_uri(msg=None):
    u = U("/admin")
    if msg:
        u += "?msg=" + urllib.parse.quote(msg)
    return u


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}"
        n /= 1024


def fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "-"


def file_icon(name):
    return ICONS.get(os.path.splitext(name)[1].lower(), DEFAULT_ICON)


def file_tile(name):
    return TILE_BG.get(os.path.splitext(name)[1].lower(), DEFAULT_TILE)


def sanitize_rel(p):
    p = (p or "").replace("\\", "/").strip()
    p = re.sub(r"/+", "/", p).strip("/")
    parts = [re.sub(r'[<>:"|?*\x00-\x1f]', "_", seg) for seg in p.split("/")]
    parts = [s for s in parts if s not in ("", ".", "..")]
    if not parts:
        return ""
    return "/".join(parts)


def safe_path(rel):
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or rel.startswith(".uploads"):
        return None
    real = os.path.realpath(os.path.join(FILES_DIR, rel))
    base = os.path.realpath(FILES_DIR) + os.sep
    if not real.startswith(base) or real == os.path.realpath(FILES_DIR):
        return None
    return real


def make_token():
    exp = int(time.time()) + SESSION_DAYS * 86400
    sig = hmac.new(SESSION_SECRET, str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def check_token(tok):
    try:
        exp, sig = tok.split(".")
        expect = hmac.new(SESSION_SECRET, exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expect) and int(exp) > time.time()
    except Exception:
        return False


def renew_token(tok):
    try:
        exp = int(tok.split(".")[0])
        if exp - time.time() < SESSION_RENEW:
            return make_token()
    except Exception:
        pass
    return None


def login_ok(handler):
    cookie = handler.headers.get("Cookie", "")
    for c in cookie.split(";"):
        c = c.strip()
        if c.startswith("share_auth="):
            tok = c[len("share_auth="):]
            if check_token(tok):
                nt = renew_token(tok)
                if nt:
                    handler._renew_cookie = ("share_auth=%s; Max-Age=%d; Path=/; HttpOnly; SameSite=Lax"
                                             % (nt, SESSION_DAYS * 86400))
                return True
    return False


def pool_used():
    total = 0
    for root, dirs, files in os.walk(FILES_DIR):
        dirs[:] = [d for d in dirs if d != ".uploads"]
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def pending_used():
    if not os.path.isdir(UPLOADS_DIR):
        return 0
    total = 0
    for root, _dirs, files in os.walk(UPLOADS_DIR):
        for f in files:
            if not f.isdigit():
                continue
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def reserved_used():
    total = 0
    if not os.path.isdir(UPLOADS_DIR):
        return 0
    for d in os.listdir(UPLOADS_DIR):
        dp = os.path.join(UPLOADS_DIR, d)
        if not os.path.isdir(dp):
            continue
        meta = upload_meta(d)
        if meta:
            need = meta.get("need")
            total += int(need) if need is not None else int(meta.get("size") or 0)
    return total


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def scan_pool():
    items = []

    def walk(dpath, prefix):
        subtree = {"count": 0, "size": 0, "mtime": 0}
        try:
            entries = os.listdir(dpath)
        except OSError:
            return subtree
        files = sorted(f for f in entries if os.path.isfile(os.path.join(dpath, f)))
        dirs = sorted(d for d in entries
                      if os.path.isdir(os.path.join(dpath, d)) and d != ".uploads")
        for f in files:
            fp = os.path.join(dpath, f)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            path = prefix + f
            items.append({"path": path, "name": f, "is_dir": False,
                          "size": st.st_size, "size_h": human_size(st.st_size),
                          "mtime": fmt_time(st.st_mtime),
                          "icon": file_icon(f), "tile": file_tile(f), "file_count": 0})
            subtree["count"] += 1
            subtree["size"] += st.st_size
            subtree["mtime"] = max(subtree["mtime"], st.st_mtime)
        for d in dirs:
            child = walk(os.path.join(dpath, d), prefix + d + "/")
            items.append({"path": prefix + d, "name": d, "is_dir": True,
                          "size": child["size"], "size_h": human_size(child["size"]),
                          "mtime": fmt_time(child["mtime"]),
                          "icon": "📁", "tile": FOLDER_TILE, "file_count": child["count"]})
            subtree["count"] += child["count"]
            subtree["size"] += child["size"]
            subtree["mtime"] = max(subtree["mtime"], child["mtime"])
        return subtree

    if os.path.isdir(FILES_DIR):
        walk(FILES_DIR, "")
    return items


def upload_meta(uid):
    path = os.path.join(UPLOADS_DIR, uid, "meta.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


def write_meta(uid, meta):
    udir = os.path.join(UPLOADS_DIR, uid)
    os.makedirs(udir, exist_ok=True)
    with open(os.path.join(udir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)


def registry_path():
    return os.path.join(UPLOADS_DIR, "_registry.json")


def load_registry():
    try:
        with open(registry_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def save_registry(reg):
    try:
        with open(registry_path(), "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False)
    except OSError:
        pass


def register_hash(file_hash, uid):
    if not file_hash:
        return
    reg = load_registry()
    reg[file_hash] = uid
    save_registry(reg)


def unregister_hash(file_hash):
    if not file_hash:
        return
    reg = load_registry()
    if file_hash in reg:
        del reg[file_hash]
        save_registry(reg)


def unregister_uid(uid):
    reg = load_registry()
    changed = False
    for h, u in list(reg.items()):
        if u == uid:
            del reg[h]
            changed = True
    if changed:
        save_registry(reg)


def total_chunks_for(size):
    if size <= 0:
        return 1
    return (size + CHUNK - 1) // CHUNK


def chunk_expected_len(size, total, i):
    if size <= 0:
        return 0
    if i < total - 1:
        return CHUNK
    return size - CHUNK * (total - 1)


def cleanup_uploads():
    if not os.path.isdir(UPLOADS_DIR):
        return
    now = time.time()
    for d in os.listdir(UPLOADS_DIR):
        dp = os.path.join(UPLOADS_DIR, d)
        mp = os.path.join(dp, "meta.json")
        try:
            if os.path.isdir(dp):
                last = os.path.getmtime(mp) if os.path.exists(mp) else os.path.getmtime(dp)
                if now - last > UPLOAD_TTL:
                    shutil.rmtree(dp, ignore_errors=True)
                    unregister_uid(d)
                    LOG.warning("cleanup: upload %s idle >%ds, removed", d, UPLOAD_TTL)
                elif os.path.exists(mp):
                    meta = upload_meta(d)
                    if meta and meta.get("need") and now - last > RESERVE_TTL:
                        meta["need"] = 0
                        write_meta(d, meta)
                        LOG.info("reserve released: upload %s idle >%ds", d, RESERVE_TTL)
        except OSError:
            pass


def clear_uploads():
    freed = 0
    if os.path.isdir(UPLOADS_DIR):
        for d in os.listdir(UPLOADS_DIR):
            dp = os.path.join(UPLOADS_DIR, d)
            if os.path.isdir(dp):
                freed += dir_size(dp)
                shutil.rmtree(dp, ignore_errors=True)
    try:
        os.remove(registry_path())
    except OSError:
        pass
    return freed


def maybe_cleanup():
    global _LAST_CLEANUP
    now = time.time()
    if now - _LAST_CLEANUP < 30:
        return
    _LAST_CLEANUP = now
    cleanup_uploads()


def touch_upload(uid):
    mp = os.path.join(UPLOADS_DIR, uid, "meta.json")
    try:
        if os.path.exists(mp):
            os.utime(mp, None)
    except OSError:
        pass


def parse_multipart(content_type, body):
    raw = (
        "Content-Type: " + content_type + "\r\n"
        "MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8") + body
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    fields = {}
    for part in msg.iter_parts():
        if part.get_content_maintype() == "multipart":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        if filename is not None:
            fields[name] = {"filename": filename, "content": part.get_payload(decode=True) or b""}
        else:
            payload = part.get_payload(decode=True)
            fields[name] = payload.decode("utf-8", "replace") if payload else ""
    return fields


def parse_multipart_list(content_type, body):
    raw = (
        "Content-Type: " + content_type + "\r\n"
        "MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8") + body
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    out = {}
    for part in msg.iter_parts():
        if part.get_content_maintype() == "multipart":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        if part.get_filename() is not None:
            out.setdefault(name, []).append(part.get_payload(decode=True) or b"")
        else:
            payload = part.get_payload(decode=True)
            out.setdefault(name, []).append(payload.decode("utf-8", "replace") if payload else "")
    return out

PAGE_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📁</text></svg>">
<style>
:root{--paper:#f5efe1;--card:#fdf9ef;--ink:#2a2418;--muted:#8b7f64;--rule:#d9cfb6;--rule2:#b3a486;--accent:#b23a2b;--accent-deep:#8f2d21;--ring:rgba(178,58,43,.25);--shadow:3px 3px 0 rgba(42,36,24,.55)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:radial-gradient(1000px 500px at 88% -8%,rgba(178,58,43,.07),transparent 62%),radial-gradient(900px 480px at -8% 8%,rgba(42,36,24,.05),transparent 60%),var(--paper);color:var(--ink);min-height:100vh;-webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.06;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
.wrap{max-width:1020px;margin:0 auto;padding:30px 20px 92px}
.hero{position:relative;border:2px solid var(--ink);background:var(--card);box-shadow:6px 6px 0 var(--ink);padding:20px 26px 20px;background-image:linear-gradient(rgba(42,36,24,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(42,36,24,.035) 1px,transparent 1px);background-size:22px 22px}
.hero::before{content:"";position:absolute;left:-2px;top:-2px;width:18px;height:18px;background:var(--accent)}
.hrow{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:14px}
.brand{display:flex;align-items:center;gap:14px}
.logo{width:50px;height:50px;background:var(--ink);color:var(--card);display:grid;place-items:center;font-size:25px;box-shadow:3px 3px 0 var(--accent);flex-shrink:0}
.brand h1{font-family:Georgia,"Times New Roman","Songti SC","STSong",serif;font-size:26px;font-weight:700;letter-spacing:.5px}
.brand .sub{font-size:11px;color:var(--muted);margin-top:4px;letter-spacing:1.5px;text-transform:uppercase;font-family:"Courier New",monospace}
.acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.act-sep{width:1px;height:20px;background:rgba(42,36,24,.28);margin:0 2px;align-self:center;flex-shrink:0}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}
.stat{border:1.5px solid var(--ink);background:var(--card);padding:8px 16px;min-width:118px;box-shadow:2px 2px 0 rgba(42,36,24,.35)}
.stat b{display:block;font-family:Georgia,serif;font-size:20px;font-weight:700}
.stat span{font-family:"Courier New",monospace;font-size:10px;letter-spacing:1px;color:var(--muted);text-transform:uppercase}
.quota{margin-top:14px;max-width:520px}
.quota .bar{height:12px;border:1.5px solid var(--ink);background:repeating-linear-gradient(45deg,rgba(42,36,24,.14) 0 4px,transparent 4px 8px);display:flex;overflow:hidden}
.quota .bar i{display:block;height:100%;width:0;transition:width .3s}
#qbar{background:var(--accent)}
#qbar2{background:repeating-linear-gradient(45deg,#caa53d 0 6px,#e2c05c 6px 12px)}
#qbar3{background:repeating-linear-gradient(135deg,#5b8dd6 0 6px,#8fb0e8 6px 12px)}
.quota .lbl{font-family:"Courier New",monospace;font-size:11px;margin-top:7px;color:var(--muted);letter-spacing:.3px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:8px 16px;border-radius:0;font-size:12px;font-weight:700;text-decoration:none;cursor:pointer;transition:transform .1s,box-shadow .1s,background .12s;white-space:nowrap;font-family:inherit;letter-spacing:.4px;text-transform:uppercase;border:1.5px solid var(--ink);background:var(--card);color:var(--ink)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none}
.btn:hover{transform:translate(-1px,-1px);box-shadow:2px 2px 0 var(--ink)}
.btn:active{transform:none;box-shadow:none}
.btn-white{background:var(--ink);color:var(--card)}
.btn-white:hover{background:var(--accent-deep)}
.btn-primary{background:var(--ink);color:var(--card)}
.btn-primary:hover{background:var(--accent-deep)}
.btn-ghost{background:transparent}
.btn-danger{background:var(--accent);color:#fff7ea;border-color:var(--accent-deep)}
.btn-add{background:transparent;border-style:dashed}
.btn-multi{background:var(--card)}
.btn-multi.on{background:var(--ink);color:var(--card)}
.btn-sm{padding:6px 12px;font-size:11px}
.btn-xs{padding:4px 9px;font-size:10.5px}
.selbar{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);display:flex;align-items:center;gap:10px;padding:10px 16px;border:2px solid var(--ink);background:var(--card);box-shadow:5px 5px 0 var(--ink);z-index:50;flex-wrap:wrap;justify-content:center;max-width:96vw}
.selbar .cnt{font-size:13px;font-weight:700;color:var(--accent-deep);margin-right:2px;font-family:Georgia,serif}
.file-card{position:relative}
.chk{position:absolute;top:9px;right:9px;width:22px;height:22px;border:2px solid var(--ink);background:var(--card);display:none;place-items:center;font-size:13px;color:#fff;font-weight:800;line-height:1}
.chk.on{background:var(--accent);border-color:var(--accent)}
.selmode .chk{display:grid}
.file-card.sel{border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
.file-card.selmode-card{cursor:pointer}
.crumbs{display:flex;flex-wrap:wrap;align-items:center;gap:2px;font-size:12.5px;margin:18px 0 4px;font-family:"Courier New",monospace}
.crumbs a{color:var(--accent-deep);text-decoration:none;cursor:pointer;padding:3px 6px;border-bottom:1px solid transparent;font-weight:700}
.crumbs a:hover{border-bottom-color:var(--accent)}
.crumbs .sep{color:var(--rule2);padding:0 2px}
.search{position:relative;margin:12px 0 14px}
.search input{width:100%;padding:11px 16px 11px 40px;border:1.5px solid var(--ink);font-size:14px;background:var(--card);outline:none;font-family:inherit;box-shadow:2px 2px 0 rgba(42,36,24,.35);transition:box-shadow .12s}
.search input:focus{box-shadow:3px 3px 0 var(--ink)}
.search .m{position:absolute;left:13px;top:50%;transform:translateY(-50%);font-size:15px;opacity:.5;pointer-events:none}
.gtool{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
.pager{display:flex;align-items:center;justify-content:center;gap:12px;margin-top:18px;font-family:"Courier New",monospace;font-size:12px;color:var(--muted);flex-wrap:wrap}
.pg-jump{display:flex;align-items:center;gap:4px}
.pg-jump input{width:52px;padding:4px 6px;border:1.5px solid var(--ink);background:var(--card);font-family:"Courier New",monospace;font-size:12px;text-align:center;outline:none;color:var(--ink)}
.pg-jump input:focus{box-shadow:2px 2px 0 var(--ink)}
.card{background:var(--card);border:1.5px solid var(--ink);box-shadow:3px 3px 0 rgba(42,36,24,.5)}
.file-card{display:flex;flex-direction:column;padding:15px;transition:transform .12s,box-shadow .12s;position:relative}
.file-card::before{content:"";position:absolute;top:-1.5px;right:16px;width:30px;height:9px;background:var(--ink)}
.file-card:hover{transform:translate(-2px,-2px);box-shadow:6px 6px 0 var(--ink)}
.back-card{border-style:dashed;cursor:pointer}
.back-card .tile{border-style:dashed}
.back-card:hover{transform:translate(-2px,-2px);box-shadow:6px 6px 0 var(--ink)}
.f-top{display:flex;align-items:center;gap:13px}
.f-top .meta{flex:1;min-width:0;overflow:hidden}
.tile{width:50px;height:50px;border:1.5px solid var(--ink);display:grid;place-items:center;font-size:24px;flex-shrink:0}
.name{font-weight:700;font-size:14.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.f-ext{font-size:12px;color:var(--muted);max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:bottom}
.sub{font-size:11px;color:var(--muted);margin-top:3px;font-family:"Courier New",monospace}
.f-bot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:14px;padding-top:12px;border-top:1.5px dashed var(--rule2)}
.f-bot form{display:inline-flex}
.empty{grid-column:1/-1;padding:58px 20px;text-align:center;color:var(--muted);border:2px dashed var(--rule2);background:var(--card)}
.empty .big{font-size:42px;margin-bottom:12px}
.zone{position:relative;border:2px dashed var(--ink);padding:24px 20px;text-align:center;color:var(--muted);cursor:pointer;transition:background .15s;background:rgba(253,249,239,.5)}
.zone::before,.zone::after{content:"";position:absolute;width:14px;height:14px;border:2px solid var(--ink)}
.zone::before{top:-2px;left:-2px;border-right:0;border-bottom:0}
.zone::after{bottom:-2px;right:-2px;border-left:0;border-top:0}
.zone:hover,.zone.drag{background:rgba(178,58,43,.07);color:var(--ink)}
.zone.drag{outline:2px solid var(--accent)}
.zone .big{font-size:34px;margin-bottom:6px}
.zone .tip{font-size:11px;margin-top:7px;opacity:.72;font-family:"Courier New",monospace;letter-spacing:.3px}
.panel{background:var(--card);border:2px solid var(--ink);box-shadow:5px 5px 0 var(--ink);padding:20px;margin-top:30px;margin-bottom:18px}
.panel h3{font-size:14px;font-weight:800;margin-bottom:14px;display:flex;align-items:center;gap:8px;border-bottom:1.5px solid var(--ink);padding-bottom:10px;font-family:Georgia,serif;letter-spacing:.4px}
.task{display:flex;align-items:center;gap:12px;padding:9px 13px;border:1.5px solid var(--rule2);margin-bottom:8px;background:var(--card);box-shadow:2px 2px 0 rgba(42,36,24,.2)}
.task .tic{font-size:20px;flex-shrink:0}
.task .nm{flex:1;min-width:0}
.task .nm .pn{font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.task .nm .ps{font-size:11px;color:var(--muted);font-family:"Courier New",monospace}
.task .tbar{width:88px;height:8px;border:1px solid var(--ink);background:rgba(42,36,24,.08);overflow:hidden;flex-shrink:0}
.task .tbar i{display:block;height:100%;width:0;background:var(--accent);transition:width .15s}
.task .tbar.err{border-color:var(--accent-deep);background:rgba(178,58,43,.1)}
.task .tbar.err i{background:var(--accent-deep)}
.task .tbar.ok{border-color:#1f7a4d;background:rgba(31,122,77,.08)}
.task .tbar.ok i{background:#1f7a4d}
.task .st{font-size:10.5px;color:var(--muted);width:auto;min-width:74px;white-space:nowrap;text-align:right;flex-shrink:0;font-family:"Courier New",monospace}
.task .st.err{color:var(--accent-deep);font-weight:700}
.task .st.done{color:#1f7a4d;font-weight:700}
.tdone{display:flex;align-items:center;gap:10px;padding:14px 16px;border:2px solid #1f7a4d;background:#eef7f0;color:#1f7a4d;font-size:14px;font-weight:700;box-shadow:2px 2px 0 rgba(42,36,24,.2)}
.task-status{display:none;flex-wrap:wrap;gap:8px;margin:12px 0 16px}
.task-status .stat{border:1.5px solid var(--rule);background:var(--paper);min-width:0;padding:6px 14px;box-shadow:1.5px 1.5px 0 rgba(42,36,24,.35)}
.task-status .stat b{font-size:16px}
.task-status .stat span{font-size:9px}
.task-status .stat.total{border-color:var(--ink)}
.task-status .stat.total b{color:var(--ink)}
.task-status .stat.done b{color:#1f7a4d}
.task-status .stat.up b{color:#3b6db5}
.task-status .stat.wait b{color:#a07c15}
.task-status .stat.pause b{color:#777}
.task-status .stat.fail b{color:var(--accent-deep)}
.modal{position:fixed;inset:0;background:rgba(42,36,24,.55);z-index:100;display:flex;align-items:center;justify-content:center;padding:20px}
.modal-card{background:var(--card);border:2px solid var(--ink);box-shadow:8px 8px 0 var(--ink);max-width:860px;width:100%;max-height:82vh;display:flex;flex-direction:column;overflow:hidden}
.modal-head{display:flex;align-items:center;justify-content:space-between;padding:13px 18px;border-bottom:1.5px solid var(--ink);gap:10px}
.modal-head b{font-family:Georgia,serif;font-size:14px}
.cache-body{flex:1;overflow:auto;padding:6px 18px 14px}
.cache-table{width:100%;border-collapse:collapse;font-size:12.5px}
.cache-table th{text-align:left;font-family:"Courier New",monospace;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);border-bottom:1.5px solid var(--ink);padding:9px 10px;position:sticky;top:0;background:var(--card)}
.cache-table td{padding:8px 10px;border-bottom:1px dashed var(--rule2);vertical-align:top}
.cache-table tr:last-child td{border-bottom:none}
.cache-table .h{font-family:"Courier New",monospace;color:var(--accent-deep);font-size:11.5px;word-break:break-all}
.cache-table .fn{font-weight:700}
.cache-table .num{font-family:"Courier New",monospace;white-space:nowrap}
.modal-card pre{flex:1;overflow:auto;margin:0;padding:14px 18px;font-size:12px;line-height:1.55;background:#211d14;color:#d8cdb6;font-family:Consolas,Menlo,monospace;white-space:pre-wrap;word-break:break-all}
footer{text-align:center;margin-top:34px;font-size:11px;color:var(--muted);font-family:"Courier New",monospace;letter-spacing:.5px}
footer a{color:var(--accent-deep);text-decoration:none}
.auth{max-width:400px;margin:9vh auto 0}
.auth-card{padding:34px 30px;background:var(--card);border:2px solid var(--ink);box-shadow:8px 8px 0 var(--ink)}
.auth .logo{width:58px;height:58px;font-size:28px;background:var(--ink);color:var(--card);display:grid;place-items:center;margin:0 auto 16px;box-shadow:3px 3px 0 var(--accent)}
.auth h2{text-align:center;font-family:Georgia,serif;font-size:20px;font-weight:700;margin-bottom:22px;letter-spacing:.5px}
.auth input{width:100%;padding:11px 13px;border:1.5px solid var(--ink);font-size:14px;outline:none;background:var(--paper);box-shadow:2px 2px 0 rgba(42,36,24,.3);transition:box-shadow .12s}
.auth input:focus{box-shadow:3px 3px 0 var(--ink)}
.auth .btn{width:100%;padding:12px;margin-top:14px;font-size:13.5px}
#toasts{position:fixed;top:16px;left:0;right:0;z-index:999;pointer-events:none}
.titem-wrap{position:absolute;left:50%;transform:translateX(-50%);top:0}
.titem{color:#fff;padding:12px 24px;border-radius:0;font-size:13px;font-weight:700;min-width:260px;max-width:82vw;text-align:center;box-shadow:4px 4px 0 rgba(42,36,24,.55);opacity:0;transform:translateY(-18px);transition:opacity .22s ease,transform .22s ease;pointer-events:auto}
.titem.show{opacity:1;transform:translateY(0)}
.titem.ok{background:var(--ink)}
.titem.err{background:var(--accent-deep)}
</style>
<script>
window.fmt=function(b){if(b>=1073741824)return (b/1073741824).toFixed(1)+' GB';if(b>=1048576)return (b/1048576).toFixed(1)+' MB';if(b>=1024)return (b/1024).toFixed(1)+' KB';return b+' B';};
window._toastSeq=0;
window.toast=function(ok,text){
  var box=document.getElementById('toasts');
  if(!box)return;
  var w=document.createElement('div');w.className='titem-wrap';
  var t=document.createElement('div');t.className='titem'+(ok?' ok':' err');
  t.textContent=text;
  w.appendChild(t);
  box.appendChild(w);
  var wraps=box.querySelectorAll('.titem-wrap');
  while(wraps.length>4){wraps[0].remove();wraps=box.querySelectorAll('.titem-wrap');}
  for(var i=0;i<wraps.length;i++){
    if(wraps[i]!==w){
      var cur=parseFloat(wraps[i].style.top)||0;
      wraps[i].style.top=(cur+14)+'px';
    }
  }
  w.style.top='0px';
  w.style.zIndex=String(++window._toastSeq);
  requestAnimationFrame(function(){t.classList.add('show');});
  setTimeout(function(){t.classList.remove('show');setTimeout(function(){w.remove();},240);},3200);
};
window.esc=function(s){return String(s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});};
window.inDir=function(dir,path){var i=dir?path.indexOf(dir+'/'):0;if(dir&&i!==0)return false;var rest=dir?path.slice(dir.length+1):path;return rest.indexOf('/')<0;};
</script>
</head>
<body>
<div id="toasts"></div>
<div class="wrap">
"""

PAGE_FOOT = """
</div>
<script>
if(window.__msg&&window.__msg[1])window.toast(window.__msg[0]==='ok',window.__msg[1]);
</script>
</body>
</html>
"""


def page(title, body):
    return PAGE_HEAD.replace("{title}", title) + body + PAGE_FOOT

PUBLIC_SCRIPT = """<script>
var P="__PREFIX__";
var INIT=__INIT__;
var MSG=__MSG__;
var DATA=INIT.data,USED=INIT.used,QUOTA=INIT.quota,PENDING=INIT.pending||0,RESERVED=INIT.reserved||0;
var dir='',q='';
var PAGE_SIZE=12,page=1,pageCount=1;
var selMode=false,selected=[];
function inSel(p){return selected.indexOf(p)>=0;}
function toggleSel(p){var i=selected.indexOf(p);if(i>=0)selected.splice(i,1);else selected.push(p);render();renderSel();}
function selAll(){var items=DATA.filter(function(it){return inDir(dir,it.path);});
  var all=items.length>0&&items.every(function(it){return inSel(it.path);});
  if(all){var ps={};items.forEach(function(it){ps[it.path]=1;});selected=selected.filter(function(p){return !ps[p];});}
  else{items.forEach(function(it){if(selected.indexOf(it.path)<0)selected.push(it.path);});}
  render();renderSel();}
function renderSel(){
  var act=document.getElementById('btnSel');
  if(act)act.classList.toggle('on',selMode);
  var bar=document.getElementById('selbar');
  if(!bar)return;
  if(!selMode){bar.style.display='none';return;}
  bar.style.display='flex';
  document.getElementById('selcount').textContent='已选 '+selected.length+' 项';
  var z=document.getElementById('selZipBtn');if(z)z.disabled=selected.length===0;
}
function zipDown(){
  if(!selected.length){toast(false,'请先选择文件');return;}
  var f=document.createElement('form');f.method='POST';f.action=P+'/zip';f.style.display='none';
  selected.forEach(function(p){var i=document.createElement('input');i.type='hidden';i.name='path';i.value=p;f.appendChild(i);});
  document.body.appendChild(f);f.submit();
}
function zipOne(path){
  var f=document.createElement('form');f.method='POST';f.action=P+'/zip';f.style.display='none';
  var i=document.createElement('input');i.type='hidden';i.name='path';i.value=path;
  f.appendChild(i);document.body.appendChild(f);f.submit();
}
function nav(p){dir=p;page=1;try{history.pushState(null,'','#/'+p);}catch(e){}render();}
function render(){
  var items=DATA.filter(function(it){return inDir(dir,it.path);});
  if(q){var v=q.toLowerCase();items=items.filter(function(it){return it.name.toLowerCase().indexOf(v)>=0;});}
  items.sort(function(a,b){return (a.is_dir===b.is_dir)?a.name.localeCompare(b.name):(a.is_dir?-1:1);});
  var per=dir?(PAGE_SIZE-1):PAGE_SIZE;
  pageCount=Math.max(1,Math.ceil(items.length/per));
  if(page>pageCount)page=pageCount;
  var pj0=document.getElementById('pgJump');if(pj0)pj0.value=page;
  var g=document.getElementById('grid');
  g.innerHTML='';
  g.className='grid'+(selMode?' selmode':'');
  if(dir){
    var parent=dir.split('/').filter(Boolean).slice(0,-1).join('/');
    var bk=document.createElement('div');bk.className='card file-card back-card';
    var bt=document.createElement('div');bt.className='tile';bt.textContent='↰';
    var bm=document.createElement('div');bm.className='meta';
    var bn=document.createElement('div');bn.className='name';bn.textContent='返回上一级';
    var bs=document.createElement('div');bs.className='sub';bs.textContent=parent?('📁 '+parent):'📁 根目录';
    bm.appendChild(bn);bm.appendChild(bs);
    bk.appendChild(bt);bk.appendChild(bm);
    bk.onclick=function(){nav(parent);};
    g.appendChild(bk);
  }
  if(!items.length){
    var empty=document.createElement('div');empty.className='empty';
    empty.innerHTML='<div class="big">🗂️</div><div style="font-weight:700;color:var(--ink)">'+(dir?'该文件夹为空':'这里空空如也')+'</div><div style="margin-top:6px">'+(dir?'':'管理员上传文件后，就会展示在这里')+'</div>';
    g.appendChild(empty);
  }
  items.slice((page-1)*per,page*per).forEach(function(it){
    var c=document.createElement('div');c.className='card file-card';
    if(selMode)c.classList.add('selmode-card');
    c.classList.toggle('sel',inSel(it.path));
    var chk=document.createElement('div');chk.className='chk'+(inSel(it.path)?' on':'');chk.textContent=inSel(it.path)?'✓':'';
    c.appendChild(chk);
    var top=document.createElement('div');top.className='f-top';
    var t=document.createElement('div');t.className='tile';t.style.background=it.tile;t.textContent=it.icon;
    var m=document.createElement('div');m.className='meta';
    var n=document.createElement('div');n.className='name';n.title=it.name;n.textContent=it.name;
    var s=document.createElement('div');s.className='sub';
    s.textContent=it.is_dir?(it.file_count+' 个文件 · '+fmt(it.size)):(fmt(it.size)+' · '+it.mtime);
    m.appendChild(n);m.appendChild(s);top.appendChild(t);top.appendChild(m);
    var bot=document.createElement('div');bot.className='f-bot';
    var lb=document.createElement('span');lb.className='f-ext';
    var extRaw=it.name.indexOf('.')>=0?it.name.split('.').pop():'';
    var ext=extRaw.toUpperCase();
    lb.textContent=it.is_dir?'文件夹':(ext||'文件');
    lb.title=it.is_dir?'文件夹':(extRaw||'文件');
    bot.appendChild(lb);
    if(it.is_dir){
      var grp=document.createElement('div');grp.style.cssText='display:flex;gap:8px;align-items:center';
      var b=document.createElement('button');b.className='btn btn-ghost btn-sm';b.textContent='打开';
      b.onclick=function(e){e.stopPropagation();nav(it.path);};
      var z=document.createElement('button');z.className='btn btn-primary btn-sm';z.textContent='⬇ ZIP';
      z.onclick=function(e){e.stopPropagation();zipOne(it.path);};
      grp.appendChild(b);grp.appendChild(z);
      bot.appendChild(grp);
    }else{
      var a=document.createElement('a');a.className='btn btn-primary btn-sm';a.href=P+'/d?p='+encodeURIComponent(it.path);a.textContent='↓ 下载';
      a.addEventListener('click',function(e){e.stopPropagation();});
      bot.appendChild(a);
    }
    c.appendChild(top);c.appendChild(bot);
    if(selMode)c.onclick=function(){toggleSel(it.path);};
    g.appendChild(c);
  });
  var fc=0;DATA.forEach(function(x){if(!x.is_dir)fc++;});
  var free=Math.max(0,QUOTA-USED-RESERVED-PENDING);
  document.getElementById('st-count').innerHTML='<b>'+fc+'</b><span>文件</span>';
  document.getElementById('st-size').innerHTML='<b>'+fmt(USED)+'</b><span>已用空间</span>';
  document.getElementById('st-quota').innerHTML='<b>'+fmt(free)+'</b><span>可用空间</span>';
  var pUsed=QUOTA?Math.min(100,USED/QUOTA*100):0;
  var pPending=QUOTA?Math.min(Math.max(0,100-pUsed),PENDING/QUOTA*100):0;
  var pReserved=QUOTA?Math.min(Math.max(0,100-pUsed-pPending),RESERVED/QUOTA*100):0;
  var qb=document.getElementById('qbar');if(qb)qb.style.width=pUsed+'%';
  var q2=document.getElementById('qbar2');if(q2)q2.style.width=pPending+'%';
  var q3=document.getElementById('qbar3');if(q3)q3.style.width=pReserved+'%';
  var ql=document.getElementById('qlbl');
  if(ql)ql.textContent='已用 '+fmt(USED)+' · 预留 '+fmt(RESERVED)+' · 缓存 '+fmt(PENDING)+' · 可用 '+fmt(free)+' · 总量 '+fmt(QUOTA);
  var pg=document.getElementById('pager');
  if(pg){
    if(items.length<=PAGE_SIZE){pg.style.display='none';}
    else{
      pg.style.display='flex';
      document.getElementById('pgInfo').textContent='第 '+page+' / '+pageCount+' 页 · 共 '+items.length+' 项';
      var pv=document.getElementById('pgPrev'),nx=document.getElementById('pgNext');
      if(pv)pv.disabled=page<=1;
      if(nx)nx.disabled=page>=pageCount;
      var j=document.getElementById('pgJump');if(j)j.max=pageCount;
    }
  }
  var cr=document.getElementById('crumbs');cr.innerHTML='';
  var root=document.createElement('a');root.textContent='🏠 根目录';root.href='javascript:void 0';root.onclick=function(){nav('');};cr.appendChild(root);
  if(dir){
    var acc='';
    dir.split('/').forEach(function(s){
      acc=acc?acc+'/'+s:s;
      var sp=document.createElement('span');sp.className='sep';sp.textContent='/';cr.appendChild(sp);
      var a=document.createElement('a');a.textContent=s;a.href='javascript:void 0';
      a.onclick=function(){nav(acc);};cr.appendChild(a);
    });
  }
}
window.addEventListener('popstate',function(){dir=(location.hash||'#/').slice(2).split('/').filter(Boolean).join('/');page=1;render();});
document.getElementById('q').addEventListener('input',function(){q=this.value;page=1;render();});
var pgPrev=document.getElementById('pgPrev');
if(pgPrev){pgPrev.onclick=function(){if(page>1){page--;render();}};}
var pgNext=document.getElementById('pgNext');
if(pgNext){pgNext.onclick=function(){if(page<pageCount){page++;render();}};}
var pgJump=document.getElementById('pgJump');
if(pgJump){pgJump.onclick=function(){this.select();};
  var jumpG=function(){var v=parseInt(pgJump.value);if(isNaN(v)){pgJump.value=page;return;}page=Math.max(1,Math.min(pageCount,v));pgJump.value=page;render();};
  pgJump.addEventListener('keydown',function(e){if(e.key==='Enter'){jumpG();}});
  pgJump.addEventListener('blur',jumpG);
  var pgGo=document.getElementById('pgGo');
  if(pgGo){pgGo.onclick=jumpG;}}
if(MSG)toast(MSG[0]==='ok',MSG[1]);
var bsel=document.getElementById('btnSel');
if(bsel){bsel.onclick=function(){selMode=!selMode;render();renderSel();};}
var bzip=document.getElementById('selZipBtn');
if(bzip){bzip.onclick=zipDown;}
var bclear=document.getElementById('selClearBtn');
if(bclear){bclear.onclick=function(){selected=[];selMode=false;render();renderSel();};}
var ball=document.getElementById('selAllBtn');
if(ball){ball.onclick=selAll;}
renderSel();
render();
</script>"""

PUBLIC_HTML = """<section class="hero">
  <div class="hrow">
    <div class="brand">
      <div class="logo">📁</div>
      <div><h1>共享资源库</h1></div>
    </div>
  </div>
  <div class="acts">
    <a class="btn btn-white btn-sm" href="__PREFIX__/admin">🔐 管理入口</a>
  </div>
  <div class="stats">
    <div class="stat" id="st-count"><b>-</b><span>文件</span></div>
    <div class="stat" id="st-size"><b>-</b><span>资源总量</span></div>
    <div class="stat" id="st-quota"><b>-</b><span>池容量</span></div>
  </div>
  <div class="quota"><div class="bar"><i id="qbar"></i><i id="qbar2"></i><i id="qbar3"></i></div><div class="lbl" id="qlbl"></div></div>
</section>
<nav class="crumbs" id="crumbs"></nav>
<div class="search"><span class="m">🔍</span><input id="q" type="text" placeholder="搜索当前目录…" autocomplete="off"></div>
<div class="gtool">
  <button class="btn btn-multi btn-sm" id="btnSel">☑ 多选</button>
</div>
<div class="grid" id="grid"></div>
<div class="pager" id="pager" style="display:none">
  <button class="btn btn-ghost btn-xs" id="pgPrev">← 上一页</button>
  <span id="pgInfo"></span>
  <button class="btn btn-ghost btn-xs" id="pgNext">下一页 →</button>
  <span class="pg-jump">跳至<input id="pgJump" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="4">页</span><button class="btn btn-ghost btn-xs" id="pgGo">跳转</button>
</div>
<div class="selbar" id="selbar" style="display:none">
  <span class="cnt" id="selcount">已选 0 项</span>
  <button class="btn btn-ghost btn-xs" id="selAllBtn">全选当前目录</button>
  <button class="btn btn-primary btn-sm" id="selZipBtn">↓ 打包下载 ZIP</button>
  <button class="btn btn-ghost btn-sm" id="selClearBtn">取消</button>
</div>
"""

ADMIN_SCRIPT = """<script>
var P="__PREFIX__";
var INIT=__INIT__;
var MSG=__MSG__;
var DATA=INIT.data,USED=INIT.used,QUOTA=INIT.quota,PENDING=INIT.pending||0,RESERVED=INIT.reserved||0;
var dir='',q='';
var selMode=false,selected=[];
function inSel(p){return selected.indexOf(p)>=0;}
function toggleSel(p){var i=selected.indexOf(p);if(i>=0)selected.splice(i,1);else selected.push(p);render();renderSel();}
function selAll(){var items=DATA.filter(function(it){return inDir(dir,it.path);});
  var all=items.length>0&&items.every(function(it){return inSel(it.path);});
  if(all){var ps={};items.forEach(function(it){ps[it.path]=1;});selected=selected.filter(function(p){return !ps[p];});}
  else{items.forEach(function(it){if(selected.indexOf(it.path)<0)selected.push(it.path);});}
  render();renderSel();}
function renderSel(){
  var act=document.getElementById('btnSel');
  if(act)act.classList.toggle('on',selMode);
  var bar=document.getElementById('selbar');
  if(!bar)return;
  if(!selMode){bar.style.display='none';return;}
  bar.style.display='flex';
  document.getElementById('selcount').textContent='已选 '+selected.length+' 项';
  var z=document.getElementById('selZipBtn');if(z)z.disabled=selected.length===0;
  var d=document.getElementById('selDelBtn');if(d)d.disabled=selected.length===0;
}
function zipDown(){
  if(!selected.length){toast(false,'请先选择文件');return;}
  var f=document.createElement('form');f.method='POST';f.action=P+'/zip';f.style.display='none';
  selected.forEach(function(p){var i=document.createElement('input');i.type='hidden';i.name='path';i.value=p;f.appendChild(i);});
  document.body.appendChild(f);f.submit();
}
function zipOne(path){
  var f=document.createElement('form');f.method='POST';f.action=P+'/zip';f.style.display='none';
  var i=document.createElement('input');i.type='hidden';i.name='path';i.value=path;
  f.appendChild(i);document.body.appendChild(f);f.submit();
}
function batchDel(){
  if(!selected.length)return;
  if(!confirm('确认删除已选 '+selected.length+' 项？此操作不可恢复。'))return;
  var fd=new FormData();fd.append('op','delete');
  selected.forEach(function(p){fd.append('path',p);});
  fetch(P+'/admin/batch',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'已删除 '+j.done+' 项'+(j.failed&&j.failed.length?('，失败 '+j.failed.length+' 项'):''));
      if(j.failed&&j.failed.length)toast(false,j.failed.map(function(x){return x.path+':'+x.error;}).join('；'));
    }else{toast(false,j.error||'删除失败');}
    selected=[];selMode=false;refresh();renderSel();
  }).catch(function(){toast(false,'删除失败');});
}
var CHUNK=5*1024*1024,WORKERS=3;
var queue=[];var active=0;
var PAGE_SIZE=12,page=1,pageCount=1;
var TPAGE_SIZE=10,tPage=1,tPageCount=1;
function jpost(url,obj){var fd=new FormData();Object.keys(obj).forEach(function(k){fd.append(k,obj[k]);});return fetch(url,{method:'POST',body:fd}).then(function(r){return r.json();});}
function addFile(f,rel,targetDir){
  var path=rel||f.name;
  if(!path)return;
  var base=(typeof targetDir==='string')?targetDir:dir;
  if(base)path=base+'/'+path;
  var t={id:Math.random().toString(36).slice(2),file:f,path:path,name:path.split('/').pop(),
    size:f.size,lastModified:f.lastModified,upload_id:null,done:{},total:0,uploaded:0,status:'waiting',err:null};
  queue.push(t);tPage=1;pump();
}
function pump(){
  while(active<WORKERS){
    var t=null;
    for(var i=0;i<queue.length;i++){if(queue[i].status==='waiting'){t=queue[i];break;}}
    if(!t)return;
    active++;t.status='uploading';updateTaskRow(t);
    runTask(t).then(function(){active--;pump();});
  }
}
async function runTask(t){
  try{
    var fh='';
    if(t.size>0&&t.size<=64*1024*1024&&window.crypto&&crypto.subtle){
      try{fh=await fileHash(t.file);}catch(e){fh='';}
    }
    var init=await new Promise(function(res,rej){
      _initChain=_initChain.then(function(){
        jpost(P+'/admin/upload/init',{path:t.path,size:t.size,lastModified:t.lastModified,file_hash:fh}).then(res,rej);
      });
    });
    if(t.status==='cancelled'){
      if(init.upload_id){
        var rfd2=new FormData();rfd2.append('upload_id',init.upload_id);rfd2.append('release','1');
        fetch(P+'/admin/upload/cancel',{method:'POST',body:rfd2}).catch(function(){});
      }
      return;
    }
    if(init.error){fail(t,init.error);return;}
    t.upload_id=init.upload_id;t.total=init.total_chunks||1;
    _myUids[t.upload_id]=1;
    t.done={};t.uploaded=0;
    for(var k=0;k<(init.done||[]).length;k++){var di=init.done[k];t.done[di]=1;t.uploaded+=chunkLen(t,di);}
    updateTaskRow(t);
    for(var i=0;i<t.total;i++){
      if(t.status==='cancelled'||t.status==='paused')return;
      if(t.done[i])continue;
      var ok=await upChunk(t,i);
      if(t.status==='cancelled'||t.status==='paused')return;
      if(ok){t.done[i]=1;t.uploaded=Math.min(t.size,t.uploaded+chunkLen(t,i));updateTaskProgress(t);}
      else{fail(t,'分片 '+i+' 上传失败');return;}
    }
    if(t.status==='cancelled'||t.status==='paused')return;
    var comp=await jpost(P+'/admin/upload/complete',{upload_id:t.upload_id});
    if(t.status==='cancelled'||t.status==='paused')return;
    if(comp.error){fail(t,comp.error);return;}
    finish(t);
  }catch(e){fail(t,'网络错误，可重试');}
}
function chunkLen(t,i){if(t.size<=0)return 0;return i<t.total-1?CHUNK:(t.size-CHUNK*(t.total-1));}
function fileHash(blob){
  return blob.arrayBuffer().then(function(b){return crypto.subtle.digest('SHA-256',b);}).then(function(b){
    var a=new Uint8Array(b),h='';
    for(var i=0;i<a.length;i++)h+=('0'+a[i].toString(16)).slice(-2);
    return h;
  });
}
function upChunk(t,i){
  return new Promise(function(res){
    var blob=t.file.slice(i*CHUNK,Math.min(t.size,(i+1)*CHUNK));
    function sendChunk(hex){
      var x=new XMLHttpRequest();
      t._xhr=x;
      x.open('POST',P+'/admin/upload/chunk?upload_id='+encodeURIComponent(t.upload_id)+'&index='+i+(hex?'&sha256='+hex:''));
      x.onload=function(){t._xhr=null;res(x.status>=200&&x.status<300);};
      x.onerror=function(){t._xhr=null;res(false);};
      x.onabort=function(){t._xhr=null;res(false);};
      x.send(blob);
    }
    if(window.crypto&&crypto.subtle){
      blob.arrayBuffer().then(function(buf){return crypto.subtle.digest('SHA-256',buf);}).then(function(buf){
        if(t.status==='cancelled'||t.status==='paused'){res(false);return;}
        var arr=new Uint8Array(buf),hex='';
        for(var k=0;k<arr.length;k++)hex+=('0'+arr[k].toString(16)).slice(-2);
        sendChunk(hex);
      }).catch(function(){if(t.status==='cancelled'||t.status==='paused'){res(false);return;}sendChunk('');});
    }else{sendChunk('');}
  });
}
function fail(t,msg){t.status='failed';t.err=msg;updateTaskRow(t);renderBulk();toast(false,msg+'：'+t.name);refreshStats();if(!queue.some(function(x){return x.status==='uploading'||x.status==='waiting';}))finalizePool();}
var _doneTimer=null,_batchSize=0,_initChain=Promise.resolve(),_upSnap=null,_myUids={};
function snapUp(){_upSnap={};queue.forEach(function(t){_upSnap[t.id]=t.uploaded;});}
window.addEventListener('pagehide',function(){
  Object.keys(_myUids).forEach(function(u){
    var fd=new FormData();fd.append('upload_id',u);fd.append('release','1');
    try{navigator.sendBeacon(P+'/admin/upload/cancel',fd);}catch(e){}
  });
});
function showDone(n){
  var box=document.getElementById('tasks');
  if(!box)return;
  box.style.display='block';
  box.innerHTML='<div class="tdone">✓ 全部上传完成 · '+n+' 个文件</div>';
  clearTimeout(_doneTimer);
  _doneTimer=setTimeout(function(){box.style.display='none';},5000);
}
function finalizePool(){
  var n=0,f=0,p=0;
  queue.forEach(function(t){
    if(t.status==='done')n++;
    else if(t.status==='failed')f++;
    else if(t.status==='paused')p++;
  });
  var tp=document.getElementById('taskPager');
  if(!f&&!p){
    queue=[];
    renderBulk();
    updateTasksum();
    if(tp)tp.style.display='none';
    showDone(n);
  }else{
    renderBulk();
    updateTasksum();
    renderTasks();
    toast(f?false:true,(n+' 个完成'+(f?('，'+f+' 个失败'):'')+(p?('，'+p+' 个暂停'):'')));
  }
  refresh();
}
function finish(t){
  if(_batchSize<=1)toast(true,'上传完成：'+t.name);
  if(t.upload_id)delete _myUids[t.upload_id];
  t.status='done';t.uploaded=t.size;
  updateTaskRow(t);
  renderBulk();
  if(!queue.some(function(x){return x.status==='uploading'||x.status==='waiting';}))finalizePool();
}
function cancelTask(t){
  if(t._xhr){try{t._xhr.abort();}catch(e){}t._xhr=null;}
  t.status='cancelled';
  if(t.upload_id){
    delete _myUids[t.upload_id];
    var rfd=new FormData();rfd.append('upload_id',t.upload_id);rfd.append('release','1');
    fetch(P+'/admin/upload/cancel',{method:'POST',body:rfd}).catch(function(){});
  }
  queue=queue.filter(function(x){return x.id!==t.id;});
  removeTaskRow(t);refreshStats();
}
function pauseTask(t){
  if(t.status==='uploading'||t.status==='waiting'){
    if(t._xhr){try{t._xhr.abort();}catch(e){}t._xhr=null;}
    t.status='paused';updateTaskRow(t);renderBulk();refreshStats();
  }
}
function resumeTask(t){
  if(t.status==='paused'){t.status='waiting';updateTaskRow(t);renderBulk();pump();}
}
function retryTask(t){
  t.status='waiting';t.err=null;
  updateTaskRow(t);renderBulk();pump();
}
function buildTaskRow(t){
  var r=document.createElement('div');r.className='task';r.setAttribute('data-id',t.id);
  var ic=document.createElement('div');ic.className='tic';ic.textContent='📄';
  var nm=document.createElement('div');nm.className='nm';
  var pn=document.createElement('div');pn.className='pn';pn.textContent=t.name;pn.title=t.path;
  var ps=document.createElement('div');ps.className='ps';
  var extra='';
  if(t.status==='uploading'||t.status==='waiting'||t.status==='paused'){
    var dc=0;for(var kk in t.done)dc++;
    extra=' · 分片 '+dc+'/'+t.total;
  }
  ps.textContent=(t.path!==t.name?t.path+' · ':'')+fmt(t.size)+extra+(t.err?(' · '+t.err):'');
  nm.appendChild(pn);nm.appendChild(ps);
  r.appendChild(ic);r.appendChild(nm);
  var tb=document.createElement('div');tb.className='tbar';
  var ti=document.createElement('i');
  var pct=t.size?Math.round(t.uploaded/t.size*100):0;
  ti.style.width=pct+'%';tb.appendChild(ti);
  var st=document.createElement('div');st.className='st';
  r.appendChild(tb);r.appendChild(st);
  if(t.status==='failed'){
    tb.classList.add('err');
    st.className='st err';st.textContent='失败';
    var rb=document.createElement('button');rb.className='btn btn-ghost btn-xs';rb.textContent='重试';
    rb.onclick=function(){retryTask(t);};r.appendChild(rb);
  }else if(t.status==='waiting'){
    st.textContent='等待中';
  }else if(t.status==='paused'){
    st.textContent='已暂停 '+pct+'%';
    var rs=document.createElement('button');rs.className='btn btn-add btn-xs';rs.textContent='继续';
    rs.onclick=function(){resumeTask(t);};r.appendChild(rs);
  }else if(t.status==='done'){
    tb.classList.add('ok');
    st.className='st done';st.textContent='✓ 已完成';
  }else{
    st.textContent=pct+'% · '+fmt(t.uploaded);
    var pz=document.createElement('button');pz.className='btn btn-ghost btn-xs';pz.textContent='暂停';
    pz.onclick=function(){pauseTask(t);};r.appendChild(pz);
  }
  var cx=document.createElement('button');cx.className='btn btn-danger btn-xs';cx.textContent='取消';
  cx.onclick=function(){cancelTask(t);};
  r.appendChild(cx);
  return r;
}
function updateTasksum(){
  var s=document.getElementById('tasksum');
  if(!s)return;
  if(!queue.length){s.textContent='';}
  else{var up=queue.filter(function(x){return x.status==='uploading'||x.status==='waiting';}).length;
    s.textContent=up?(' · 上传中 '+up+' 个'):(' · 队列 '+queue.length+' 个');}
}
function renderTaskPager(){
  var tp=document.getElementById('taskPager');
  if(!tp)return;
  tPageCount=Math.max(1,Math.ceil(queue.length/TPAGE_SIZE));
  if(tPage>tPageCount)tPage=tPageCount;
  var tj0=document.getElementById('tpJump');if(tj0)tj0.value=tPage;
  if(queue.length<=TPAGE_SIZE){tp.style.display='none';return;}
  tp.style.display='flex';
  document.getElementById('tpInfo').textContent='任务 '+tPage+' / '+tPageCount+' 页 · 共 '+queue.length+' 个';
  var pv=document.getElementById('tpPrev'),nx=document.getElementById('tpNext');
  if(pv)pv.disabled=tPage<=1;
  if(nx)nx.disabled=tPage>=tPageCount;
  var j=document.getElementById('tpJump');if(j)j.max=tPageCount;
}
function renderTasks(){
  var box=document.getElementById('tasks');
  box.innerHTML='';
  renderBulk();
  updateTasksum();
  renderTaskPager();
  if(!queue.length){box.style.display='none';return;}
  box.style.display='block';
  queue.slice((tPage-1)*TPAGE_SIZE,tPage*TPAGE_SIZE).forEach(function(t){
    box.appendChild(buildTaskRow(t));
  });
}
function updateTaskProgress(t){
  var r=document.querySelector('#tasks .task[data-id="'+t.id+'"]');
  if(!r)return;
  var pct=t.size?Math.round(t.uploaded/t.size*100):0;
  var ti=r.querySelector('.tbar i');if(ti)ti.style.width=pct+'%';
  var st=r.querySelector('.st');if(st)st.textContent=pct+'% · '+fmt(t.uploaded);
  var ps=r.querySelector('.ps');if(ps){
    var dc=0;for(var kk in t.done)dc++;
    ps.textContent=(t.path!==t.name?t.path+' · ':'')+fmt(t.size)+' · 分片 '+dc+'/'+t.total+(t.err?(' · '+t.err):'');
  }
}
function updateTaskRow(t){
  var r=document.querySelector('#tasks .task[data-id="'+t.id+'"]');
  if(!r)return;
  r.replaceWith(buildTaskRow(t));
}
function removeTaskRow(t){
  var r=document.querySelector('#tasks .task[data-id="'+t.id+'"]');
  if(r)r.remove();
  renderBulk();
  updateTasksum();
  if(!queue.length){renderTasks();return;}
  renderTaskPager();
}
function renderBulk(){
  var canPause=queue.some(function(t){return t.status==='uploading'||t.status==='waiting';});
  var canResume=queue.some(function(t){return t.status==='paused';});
  var canRetry=queue.some(function(t){return t.status==='failed';});
  var canCancel=queue.length>0;
  var bar=document.getElementById('bulkBar');if(bar)bar.style.display=queue.length?'flex':'none';
  var b1=document.getElementById('btnPauseAll');if(b1)b1.disabled=!canPause;
  var b2=document.getElementById('btnResumeAll');if(b2)b2.disabled=!canResume;
  var b3=document.getElementById('btnRetryAll');if(b3)b3.disabled=!canRetry;
  var b5=document.getElementById('btnCancelFailed');if(b5)b5.disabled=!canRetry;
  var b4=document.getElementById('btnCancelAll');if(b4)b4.disabled=!canCancel;
  var st=document.getElementById('taskStatus');
  if(st){
    if(!queue.length){st.style.display='none';st.innerHTML='';}
    else{
      st.style.display='flex';st.innerHTML='';
      var done=0,up=0,wait=0,pause=0,fail=0;
      queue.forEach(function(t){
        if(t.status==='done')done++;
        else if(t.status==='uploading')up++;
        else if(t.status==='waiting')wait++;
        else if(t.status==='paused')pause++;
        else if(t.status==='failed')fail++;
      });
      var item=function(cls,label,n){
        if(n<=0)return;
        var s=document.createElement('div');s.className='stat '+cls;
        s.innerHTML='<b>'+n+'</b><span>'+label+'</span>';
        st.appendChild(s);
      };
      item('total','文件总数',queue.length);
      item('done','已完成',done);
      item('up','上传中',up);
      item('wait','等待',wait);
      item('pause','暂停',pause);
      item('fail','失败',fail);
    }
  }
}
function retryAll(){
  var any=false;
  queue.forEach(function(t){if(t.status==='failed'){t.status='waiting';t.err=null;any=true;}});
  if(any){renderTasks();pump();}
}
function addBatch(batch,targetDir){
  if(!batch.length)return;
  clearTimeout(_doneTimer);
  _batchSize=batch.length;
  if(typeof targetDir!=='string')targetDir=dir;
  batch.sort(function(a,b){return a.f.size-b.f.size;});
  var total=0;
  for(var i=0;i<batch.length;i++)total+=batch[i].f.size;
  fetch(P+'/api/files').then(function(r){return r.json();}).then(function(j){
    var used=j.used,quota=j.quota,rsrv=j.reserved||0;
    var inflight=0;
    queue.forEach(function(t){if(t.status==='waiting')inflight+=t.size;});
    var avail=quota-used-rsrv-(j.pending||0)-inflight;
    if(total>avail){
      toast(false,'所选内容共 '+fmt(total)+'，可用空间 '+fmt(Math.max(0,avail))+'，超出容量，未添加');
      return;
    }
    batch.forEach(function(x){addFile(x.f,x.rel,targetDir);});
    tPageCount=Math.max(1,Math.ceil(queue.length/TPAGE_SIZE));
    if(tPage>tPageCount)tPage=tPageCount;
    renderTasks();
  }).catch(function(){
    batch.forEach(function(x){addFile(x.f,x.rel,targetDir);});
    tPageCount=Math.max(1,Math.ceil(queue.length/TPAGE_SIZE));
    if(tPage>tPageCount)tPage=tPageCount;
    renderTasks();
  });
}
function onPicked(files){
  var batch=[];
  Array.prototype.forEach.call(files,function(f){
    var rel=f.webkitRelativePath||f.name;
    batch.push({f:f,rel:rel});
  });
  addBatch(batch,dir);
}
function gatherDropped(entries, cb){
  var batch=[];
  var pending=0;
  function done(){if(pending===0)cb(batch);}
  function walk(entry){
    if(!entry)return;
    pending++;
    if(entry.isFile){
      entry.file(function(f){
        batch.push({f:f,rel:entry.fullPath.split('/').filter(Boolean).join('/')});
        pending--;done();
      });
    }else if(entry.isDirectory){
      var rd=entry.createReader();var acc=[];
      (function next(){
        rd.readEntries(function(es){
          if(!es.length){
            acc.forEach(function(x){walk(x);});
            pending--;done();
            return;
          }
          acc=acc.concat(es);next();
        });
      })();
    }else{pending--;done();}
  }
  entries.forEach(function(e){walk(e);});
  if(!entries.length)done();
}
function render(){
  var items=DATA.filter(function(it){return inDir(dir,it.path);});
  if(q){var v=q.toLowerCase();items=items.filter(function(it){return it.name.toLowerCase().indexOf(v)>=0;});}
  items.sort(function(a,b){return (a.is_dir===b.is_dir)?a.name.localeCompare(b.name):(a.is_dir?-1:1);});
  var per=dir?(PAGE_SIZE-1):PAGE_SIZE;
  pageCount=Math.max(1,Math.ceil(items.length/per));
  if(page>pageCount)page=pageCount;
  var pj0=document.getElementById('pgJump');if(pj0)pj0.value=page;
  var g=document.getElementById('grid');
  g.innerHTML='';
  g.className='grid'+(selMode?' selmode':'');
  if(dir){
    var parent=dir.split('/').filter(Boolean).slice(0,-1).join('/');
    var bk=document.createElement('div');bk.className='card file-card back-card';
    var bt=document.createElement('div');bt.className='tile';bt.textContent='↰';
    var bm=document.createElement('div');bm.className='meta';
    var bn=document.createElement('div');bn.className='name';bn.textContent='返回上一级';
    var bs=document.createElement('div');bs.className='sub';bs.textContent=parent?('📁 '+parent):'📁 根目录';
    bm.appendChild(bn);bm.appendChild(bs);
    bk.appendChild(bt);bk.appendChild(bm);
    bk.onclick=function(){nav(parent);};
    g.appendChild(bk);
  }
  if(!items.length){
    var empty=document.createElement('div');empty.className='empty';
    empty.innerHTML='<div class="big">📤</div><div style="font-weight:700;color:var(--ink)">'+(dir?'该文件夹为空':'这里还没有内容')+'</div><div style="margin-top:6px">'+(dir?'':'拖拽文件/文件夹到上方，或点击按钮上传')+'</div>';
    g.appendChild(empty);
  }
  items.slice((page-1)*per,page*per).forEach(function(it){
    var c=document.createElement('div');c.className='card file-card';
    if(selMode)c.classList.add('selmode-card');
    c.classList.toggle('sel',inSel(it.path));
    var chk=document.createElement('div');chk.className='chk'+(inSel(it.path)?' on':'');chk.textContent=inSel(it.path)?'✓':'';
    c.appendChild(chk);
    var top=document.createElement('div');top.className='f-top';
    var t=document.createElement('div');t.className='tile';t.style.background=it.tile;t.textContent=it.icon;
    var m=document.createElement('div');m.className='meta';
    var n=document.createElement('div');n.className='name';n.title=it.name;n.textContent=it.name;
    var s=document.createElement('div');s.className='sub';
    s.textContent=it.is_dir?(it.file_count+' 个文件 · '+fmt(it.size)):(fmt(it.size)+' · '+it.mtime);
    m.appendChild(n);m.appendChild(s);top.appendChild(t);top.appendChild(m);
    var bot=document.createElement('div');bot.className='f-bot';
    var lb=document.createElement('span');lb.className='f-ext';
    var extRaw=it.name.indexOf('.')>=0?it.name.split('.').pop():'';
    var ext=extRaw.toUpperCase();
    lb.textContent=it.is_dir?'文件夹':(ext||'文件');
    lb.title=it.is_dir?'文件夹':(extRaw||'文件');
    bot.appendChild(lb);
    var grp=document.createElement('div');grp.style.cssText='display:flex;gap:8px;align-items:center';
    var db=document.createElement('button');db.className='btn btn-danger btn-xs';db.textContent='🗑';
    db.onclick=function(e){e.stopPropagation();del(it.path,it.is_dir);};
    grp.appendChild(db);
    if(it.is_dir){
      var ob=document.createElement('button');ob.className='btn btn-ghost btn-xs';ob.textContent='打开';
      ob.onclick=function(e){e.stopPropagation();nav(it.path);};grp.appendChild(ob);
      var z=document.createElement('button');z.className='btn btn-primary btn-xs';z.textContent='⬇ ZIP';
      z.onclick=function(e){e.stopPropagation();zipOne(it.path);};grp.appendChild(z);
    }else{
      var a=document.createElement('a');a.className='btn btn-ghost btn-xs';a.href=P+'/d?p='+encodeURIComponent(it.path);a.textContent='下载';
      a.addEventListener('click',function(e){e.stopPropagation();});
      grp.appendChild(a);
    }
    bot.appendChild(grp);c.appendChild(top);c.appendChild(bot);
    if(selMode)c.onclick=function(){toggleSel(it.path);};
    g.appendChild(c);
  });
  var fc=0;DATA.forEach(function(x){if(!x.is_dir)fc++;});
  renderStats(fc);
  var qb=document.getElementById('qbar');if(qb)qb.style.width=(QUOTA?Math.min(100,USED/QUOTA*100):0)+'%';
  var pg=document.getElementById('pager');
  if(pg){
    if(items.length<=PAGE_SIZE){pg.style.display='none';}
    else{
      pg.style.display='flex';
      document.getElementById('pgInfo').textContent='第 '+page+' / '+pageCount+' 页 · 共 '+items.length+' 项';
      var pv=document.getElementById('pgPrev'),nx=document.getElementById('pgNext');
      if(pv)pv.disabled=page<=1;
      if(nx)nx.disabled=page>=pageCount;
      var j=document.getElementById('pgJump');if(j)j.max=pageCount;
    }
  }
  var cr=document.getElementById('crumbs');cr.innerHTML='';
  var root=document.createElement('a');root.textContent='🏠 根目录';root.href='javascript:void 0';root.onclick=function(){nav('');};cr.appendChild(root);
  if(dir){
    var acc='';
    dir.split('/').forEach(function(s){
      acc=acc?acc+'/'+s:s;
      var sp=document.createElement('span');sp.className='sep';sp.textContent='/';cr.appendChild(sp);
      var a=document.createElement('a');a.textContent=s;a.href='javascript:void 0';
      a.onclick=function(){nav(acc);};cr.appendChild(a);
    });
  }
}
function renderStats(fc){
  var rsvDisp=0;
  queue.forEach(function(t){rsvDisp+=Math.max(0,t.size-((_upSnap&&_upSnap[t.id])?(_upSnap[t.id]):t.uploaded));});
  var free=Math.max(0,QUOTA-USED-rsvDisp-PENDING);
  var over=(USED+rsvDisp+PENDING)>QUOTA;
  document.getElementById('st-count').innerHTML='<b>'+fc+'</b><span>文件</span>';
  document.getElementById('st-size').innerHTML='<b>'+fmt(USED)+'</b><span>已用空间</span>';
  document.getElementById('st-quota').innerHTML='<b>'+fmt(free)+'</b><span>可用空间</span>';
  var pUsed=QUOTA?Math.min(100,USED/QUOTA*100):0;
  var pPending=QUOTA?Math.min(Math.max(0,100-pUsed),PENDING/QUOTA*100):0;
  var pReserved=QUOTA?Math.min(Math.max(0,100-pUsed-pPending),rsvDisp/QUOTA*100):0;
  var qb=document.getElementById('qbar');if(qb)qb.style.width=pUsed+'%';
  var q2=document.getElementById('qbar2');if(q2)q2.style.width=pPending+'%';
  var q3=document.getElementById('qbar3');if(q3)q3.style.width=pReserved+'%';
  var ql=document.getElementById('qlbl');
  if(ql)ql.textContent=over?('⚠ 已用 '+fmt(USED)+' + 预留/缓存 '+fmt(RESERVED+PENDING)+' 超出容量 '+fmt(QUOTA)+'，请删除文件'):('已用 '+fmt(USED)+' · 预留 '+fmt(rsvDisp)+' · 缓存 '+fmt(PENDING)+' · 可用 '+fmt(free)+' · 总量 '+fmt(QUOTA));
}
function refreshStats(){
  snapUp();
  fetch(P+'/api/stats').then(function(r){return r.json();}).then(function(j){
    USED=j.used;QUOTA=j.quota;PENDING=j.pending||0;RESERVED=j.reserved||0;
    var fc=0;if(DATA)DATA.forEach(function(x){if(!x.is_dir)fc++;});
    renderStats(fc);
  }).catch(function(){});
}
setInterval(function(){
  if(queue.some(function(t){return t.status==='uploading'||t.status==='waiting';}))refreshStats();
},2500);
function del(path,isDir){
  var name=isDir?('文件夹「'+path+'」（含全部内容）'):('「'+path+'」');
  if(!confirm('确认删除 '+name+'？此操作不可恢复。'))return;
  var fd=new FormData();fd.append('path',path);fd.append('is_dir',isDir?1:0);
  fetch(P+'/admin/delete',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'已删除 '+path);refresh();}else{toast(false,j.error||'删除失败');}
  }).catch(function(){toast(false,'删除失败');});
}
function refresh(){
  snapUp();
  fetch(P+'/api/files').then(function(r){return r.json();}).then(function(j){
    DATA=j.data;USED=j.used;QUOTA=j.quota;PENDING=j.pending||0;render();
  }).catch(function(){});
}
function nav(p){dir=p;page=1;try{history.pushState(null,'','#/'+p);}catch(e){}render();}
window.addEventListener('popstate',function(){dir=(location.hash||'#/').slice(2).split('/').filter(Boolean).join('/');page=1;render();});
document.getElementById('q').addEventListener('input',function(){q=this.value;page=1;render();});
var pgPrev=document.getElementById('pgPrev');
if(pgPrev){pgPrev.onclick=function(){if(page>1){page--;render();}};}
var pgNext=document.getElementById('pgNext');
if(pgNext){pgNext.onclick=function(){if(page<pageCount){page++;render();}};}
var pgJump=document.getElementById('pgJump');
if(pgJump){pgJump.onclick=function(){this.select();};
  var jumpG=function(){var v=parseInt(pgJump.value);if(isNaN(v)){pgJump.value=page;return;}page=Math.max(1,Math.min(pageCount,v));pgJump.value=page;render();};
  pgJump.addEventListener('keydown',function(e){if(e.key==='Enter'){jumpG();}});
  pgJump.addEventListener('blur',jumpG);
  var pgGo=document.getElementById('pgGo');
  if(pgGo){pgGo.onclick=jumpG;}}
var tpPrev=document.getElementById('tpPrev');
if(tpPrev){tpPrev.onclick=function(){if(tPage>1){tPage--;renderTasks();}};}
var tpNext=document.getElementById('tpNext');
if(tpNext){tpNext.onclick=function(){if(tPage<tPageCount){tPage++;renderTasks();}};}
var tpJump=document.getElementById('tpJump');
if(tpJump){tpJump.onclick=function(){this.select();};
  var jumpT=function(){var v=parseInt(tpJump.value);if(isNaN(v)){tpJump.value=tPage;return;}tPage=Math.max(1,Math.min(tPageCount,v));tpJump.value=tPage;renderTasks();};
  tpJump.addEventListener('keydown',function(e){if(e.key==='Enter'){jumpT();}});
  tpJump.addEventListener('blur',jumpT);
  var tpGo=document.getElementById('tpGo');
  if(tpGo){tpGo.onclick=jumpT;}}
(function(){
  var zone=document.getElementById('zone'),fi=document.getElementById('fileInput'),di=document.getElementById('dirInput');
  if(di){di.setAttribute('webkitdirectory','');di.setAttribute('directory','');}
  zone.addEventListener('click',function(e){if(e.target.tagName!=='BUTTON'&&e.target.tagName!=='INPUT'&&e.target.closest('.acts')===null)fi.click();});
  zone.addEventListener('dragover',function(e){e.preventDefault();zone.classList.add('drag');});
  zone.addEventListener('dragleave',function(){zone.classList.remove('drag');});
  zone.addEventListener('drop',function(e){
    e.preventDefault();zone.classList.remove('drag');
    var items=e.dataTransfer.items||[];
    var entries=[];var plain=[];
    var startDir=dir;
    for(var i=0;i<items.length;i++){
      var ent=items[i].webkitGetAsEntry?items[i].webkitGetAsEntry():null;
      if(ent){entries.push(ent);}
      else if(items[i].getAsFile){plain.push(items[i].getAsFile());}
    }
    if(!entries.length){for(var j=0;j<e.dataTransfer.files.length;j++)plain.push(e.dataTransfer.files[j]);}
    var batch=[];plain.forEach(function(f){batch.push({f:f,rel:f.name});});
    if(entries.length){
      gatherDropped(entries,function(gb){addBatch(batch.concat(gb),startDir);});
    }else{
      addBatch(batch,startDir);
    }
  });
  document.getElementById('btnFiles').onclick=function(e){e.stopPropagation();fi.click();};
  document.getElementById('btnFolder').onclick=function(e){e.stopPropagation();di.click();};
  fi.addEventListener('change',function(){if(fi.files.length)onPicked(fi.files);fi.value='';});
  di.addEventListener('change',function(){if(di.files.length)onPicked(di.files);di.value='';});
})();
if(MSG)toast(MSG[0]==='ok',MSG[1]);
var bsel=document.getElementById('btnSel');
if(bsel){bsel.onclick=function(){selMode=!selMode;render();renderSel();};}
var bnf=document.getElementById('btnNewFolder');
if(bnf){bnf.onclick=function(){
  var name=prompt('新建文件夹名称','新建文件夹');
  if(name===null||!name.trim())return;
  var nm=name.trim();
  if(nm.indexOf('/')>=0||nm.indexOf('\\\\')>=0){toast(false,'文件夹名称不能包含斜杠');return;}
  var p=dir?(dir+'/'+nm):nm;
  var fd=new FormData();fd.append('path',p);
  fetch(P+'/admin/mkdir',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'已创建文件夹 '+p);refresh();}
    else{toast(false,j.error||'创建失败');}
  }).catch(function(){toast(false,'创建失败');});
};}
var bzip=document.getElementById('selZipBtn');
if(bzip){bzip.onclick=zipDown;}
var bclear=document.getElementById('selClearBtn');
if(bclear){bclear.onclick=function(){selected=[];selMode=false;render();renderSel();};}
var ball=document.getElementById('selAllBtn');
if(ball){ball.onclick=selAll;}
var bdel=document.getElementById('selDelBtn');
if(bdel){bdel.onclick=batchDel;}
var bpa=document.getElementById('btnPauseAll');
if(bpa){bpa.onclick=function(){queue.forEach(function(t){if(t.status==='uploading'||t.status==='waiting')pauseTask(t);});};}
var bra=document.getElementById('btnResumeAll');
if(bra){bra.onclick=function(){queue.forEach(function(t){if(t.status==='paused')resumeTask(t);});};}
var brt=document.getElementById('btnRetryAll');
if(brt){brt.onclick=retryAll;}
function cancelFailed(){
  var failed=[];
  queue.forEach(function(t){if(t.status==='failed')failed.push(t);});
  if(!failed.length){toast(false,'没有失败的上传任务');return;}
  if(!confirm('取消 '+failed.length+' 个失败的上传任务？其分片将保留为缓存。'))return;
  failed.forEach(function(t){cancelTask(t);});
  if(!queue.some(function(x){return x.status==='uploading'||x.status==='waiting'||x.status==='paused';})){
    var n=0;queue.forEach(function(t){if(t.status==='done')n++;});
    queue=[];
    renderBulk();
    updateTasksum();
    showDone(n);
  }
}
var bcf=document.getElementById('btnCancelFailed');
if(bcf){bcf.onclick=cancelFailed;}
var bca=document.getElementById('btnCancelAll');
if(bca){bca.onclick=function(){
  if(!queue.length){toast(false,'没有进行中的上传');return;}
  if(!confirm('取消全部 '+queue.length+' 个上传任务？分片将保留，可稍后继续。'))return;
  queue.slice().forEach(function(t){cancelTask(t);});
};}
var blog=document.getElementById('btnLog');
if(blog){blog.onclick=function(){
  var m=document.getElementById('logModal');m.style.display='flex';
  document.getElementById('logBody').textContent='加载中…';
  fetch(P+'/admin/log').then(function(r){return r.json();}).then(function(j){
    document.getElementById('logBody').textContent=j.log||j.error||'';
  }).catch(function(){document.getElementById('logBody').textContent='加载失败';});
};}
var lc=document.getElementById('logClose');
if(lc){lc.onclick=function(){document.getElementById('logModal').style.display='none';};}
var lm=document.getElementById('logModal');
if(lm){lm.addEventListener('click',function(e){if(e.target===lm)lm.style.display='none';});}
var bvc=document.getElementById('btnViewCache');
if(bvc){bvc.onclick=function(){
  var m=document.getElementById('cacheModal');m.style.display='flex';
  document.getElementById('cacheBody').textContent='加载中…';
  document.getElementById('cacheSum').textContent='';
  fetch(P+'/admin/cache').then(function(r){return r.json();}).then(function(j){
    document.getElementById('cacheSum').textContent='共 '+j.count+' 个会话';
    var body=document.getElementById('cacheBody');
    if(!j.items.length){body.innerHTML='<div style="padding:30px;text-align:center;color:var(--muted)">暂无缓存</div>';return;}
    var h='<table class="cache-table"><thead><tr><th>HASH</th><th>文件名</th><th>分片</th><th>大小</th><th>最后活动</th></tr></thead><tbody>';
    j.items.forEach(function(it){
      h+='<tr><td class="h">'+esc(it.hash)+'</td><td class="fn">'+esc(it.path)+'</td><td class="num">'+it.chunks_done+'/'+it.chunks_total+'</td><td class="num">'+esc(it.bytes_h)+'</td><td class="num">'+esc(it.last_activity)+'</td></tr>';
    });
    h+='</tbody></table>';
    body.innerHTML=h;
  }).catch(function(){document.getElementById('cacheBody').textContent='加载失败';});
};}
var ccl=document.getElementById('cacheClose');
if(ccl){ccl.onclick=function(){document.getElementById('cacheModal').style.display='none';};}
var cm2=document.getElementById('cacheModal');
if(cm2){cm2.addEventListener('click',function(e){if(e.target===cm2)cm2.style.display='none';});}
var bpurge=document.getElementById('btnPurge');
if(bpurge){bpurge.onclick=function(){
  if(!confirm('清除所有未完成上传的临时分片？（已完成上传的文件不受影响）'))return;
  fetch(P+'/admin/upload/clear',{method:'POST'}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'已清理 '+j.freed_h+' 临时分片');refresh();}
    else{toast(false,j.error||'清理失败');}
  }).catch(function(){toast(false,'清理失败');});
};}
var bpwd=document.getElementById('btnPwd');
if(bpwd){bpwd.onclick=function(){
  var oldp=prompt('请输入当前管理员密码：');
  if(oldp===null)return;
  var newp=prompt('请输入新密码（至少 5 位）：');
  if(newp===null||newp.length<5){toast(false,'新密码至少 5 位');return;}
  var fd=new FormData();fd.append('old_password',oldp);fd.append('new_password',newp);
  fetch(P+'/admin/password',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'密码已修改');}else{toast(false,j.error||'修改失败');}
  }).catch(function(){toast(false,'修改失败');});
};}
var bquota=document.getElementById('btnQuota');
if(bquota){bquota.onclick=function(){
  var cur=(QUOTA/1073741824).toFixed(1);
  var gb=prompt('设置池最大容量（GB，范围 0.5 ~ 200）：', cur);
  if(gb===null)return;
  var v=parseFloat(gb);
  if(isNaN(v)||v<0.5||v>200){toast(false,'容量需在 0.5 ~ 200 GB 之间');return;}
  if(v*1073741824 < USED){toast(false,'目标容量小于当前已用 '+fmt(USED)+'，请先删除部分文件');return;}
  var fd=new FormData();fd.append('gb',v);
  fetch(P+'/admin/quota',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'池容量已设为 '+j.quota_h);refreshStats();}
    else{toast(false,j.error||'设置失败');}
  }).catch(function(){toast(false,'设置失败');});
};}
renderSel();
render();renderTasks();
</script>"""

ADMIN_HTML = """<section class="hero">
  <div class="hrow">
    <div class="brand">
      <div class="logo">🔐</div>
      <div><h1>管理后台</h1></div>
    </div>
  </div>
  <div class="acts">
    <a class="btn btn-white btn-sm" href="__PREFIX__/">🏠 回到前台</a>
    <a class="btn btn-ghost btn-sm" href="__PREFIX__/admin/logout">🚪 退出</a>
    <span class="act-sep"></span>
    <button class="btn btn-multi btn-sm" id="btnViewCache">📋 查看缓存</button>
    <button class="btn btn-multi btn-sm" id="btnPurge">🧹 清理缓存</button>
    <span class="act-sep"></span>
    <button class="btn btn-multi btn-sm" id="btnQuota">⚖️ 修改容量</button>
    <button class="btn btn-multi btn-sm" id="btnPwd">🔑 修改密码</button>
    <span class="act-sep"></span>
    <button class="btn btn-multi btn-sm" id="btnLog">📄 日志</button>
  </div>
  <div class="stats">
    <div class="stat" id="st-count"><b>-</b><span>文件</span></div>
    <div class="stat" id="st-size"><b>-</b><span>资源总量</span></div>
    <div class="stat" id="st-quota"><b>-</b><span>池容量</span></div>
  </div>
  <div class="quota"><div class="bar"><i id="qbar"></i><i id="qbar2"></i><i id="qbar3"></i></div><div class="lbl" id="qlbl"></div></div>
</section>
<div class="panel">
  <h3>☁️ 上传资源 <span id="tasksum" style="font-size:12px;color:var(--muted);font-weight:600"></span></h3>
  <div id="taskStatus" class="task-status"></div>
  <div class="zone" id="zone">
    <div class="big">☁️</div>
    <div style="font-weight:700;color:var(--ink);font-size:15px">拖拽文件或文件夹到此处，或点击选择文件</div>
    <div class="tip">3 并发分片 · 断点可续传</div>
    <div class="acts" style="justify-content:center;margin-top:14px">
      <button class="btn btn-add" id="btnFiles">📄 选择文件</button>
      <button class="btn btn-primary" id="btnFolder" style="padding:9px 22px">📁 选择文件夹</button>
    </div>
  </div>
  <input type="file" id="fileInput" multiple style="display:none">
  <input type="file" id="dirInput" webkitdirectory multiple style="display:none">
  <div class="acts" id="bulkBar" style="justify-content:center;margin-top:14px">
    <button class="btn btn-ghost btn-sm" id="btnPauseAll">⏸ 全部暂停</button>
    <button class="btn btn-add btn-sm" id="btnResumeAll">▶ 全部继续</button>
    <button class="btn btn-add btn-sm" id="btnRetryAll">↻ 全部重试</button>
    <button class="btn btn-ghost btn-sm" id="btnCancelFailed">✖ 取消失败</button>
    <button class="btn btn-danger btn-sm" id="btnCancelAll">✕ 全部取消</button>
  </div>
  <div id="tasks" style="margin-top:16px"></div>
  <div class="pager" id="taskPager" style="display:none">
    <button class="btn btn-ghost btn-xs" id="tpPrev">← 上一页</button>
    <span id="tpInfo"></span>
    <button class="btn btn-ghost btn-xs" id="tpNext">下一页 →</button>
    <span class="pg-jump">跳至<input id="tpJump" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="4">页</span><button class="btn btn-ghost btn-xs" id="tpGo">跳转</button>
  </div>
</div>
<div class="modal" id="logModal" style="display:none">
  <div class="modal-card">
    <div class="modal-head"><b>📄 服务器日志（最近 300 行）</b><button class="btn btn-ghost btn-xs" id="logClose">✕ 关闭</button></div>
    <pre id="logBody">加载中…</pre>
  </div>
</div>
<div class="modal" id="cacheModal" style="display:none">
  <div class="modal-card">
    <div class="modal-head"><b>📋 上传缓存（临时分片）</b><span id="cacheSum" style="font-size:12px;color:var(--muted);font-family:'Courier New',monospace"></span><button class="btn btn-ghost btn-xs" id="cacheClose">✕ 关闭</button></div>
    <div class="cache-body" id="cacheBody">加载中…</div>
  </div>
</div>
<nav class="crumbs" id="crumbs"></nav>
<div class="search"><span class="m">🔍</span><input id="q" type="text" placeholder="搜索当前目录…" autocomplete="off"></div>
<div class="gtool" style="justify-content:flex-end">
  <button class="btn btn-multi btn-sm" id="btnSel">☑ 多选</button>
  <button class="btn btn-add btn-sm" id="btnNewFolder">📁 新建文件夹</button>
</div>
<div class="grid" id="grid"></div>
<div class="pager" id="pager" style="display:none">
  <button class="btn btn-ghost btn-xs" id="pgPrev">← 上一页</button>
  <span id="pgInfo"></span>
  <button class="btn btn-ghost btn-xs" id="pgNext">下一页 →</button>
  <span class="pg-jump">跳至<input id="pgJump" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="4">页</span><button class="btn btn-ghost btn-xs" id="pgGo">跳转</button>
</div>
<div class="selbar" id="selbar" style="display:none">
  <span class="cnt" id="selcount">已选 0 项</span>
  <button class="btn btn-ghost btn-xs" id="selAllBtn">全选当前目录</button>
  <button class="btn btn-primary btn-sm" id="selZipBtn">↓ 打包下载 ZIP</button>
  <button class="btn btn-danger btn-sm" id="selDelBtn">🗑 删除</button>
  <button class="btn btn-ghost btn-sm" id="selClearBtn">取消</button>
</div>
"""

def public_page(items, used, quota, msg=None, pending=0, reserved=0):
    script = PUBLIC_SCRIPT.replace("__PREFIX__", PREFIX).replace(
        "__INIT__", json.dumps({"data": items, "used": used, "quota": quota, "pending": pending, "reserved": reserved}, ensure_ascii=False))
    if msg:
        script = script.replace("__MSG__", json.dumps(["ok" if msg[0] == "ok" else "err", msg[1]], ensure_ascii=False))
    else:
        script = script.replace("__MSG__", "null")
    body = PUBLIC_HTML.replace("__PREFIX__", PREFIX) + script
    return page("共享资源库", body)


def admin_page(items, used, quota, msg=None, pending=0, reserved=0):
    script = ADMIN_SCRIPT.replace("__PREFIX__", PREFIX).replace(
        "__INIT__", json.dumps({"data": items, "used": used, "quota": quota, "pending": pending, "reserved": reserved}, ensure_ascii=False))
    if msg:
        script = script.replace("__MSG__", json.dumps(["ok" if msg[0] == "ok" else "err", msg[1]], ensure_ascii=False))
    else:
        script = script.replace("__MSG__", "null")
    body = ADMIN_HTML.replace("__PREFIX__", PREFIX).replace("{quota_h}", human_size(quota)) + script
    return page("管理后台", body)


def login_page(msg=None):
    msgscript = "window.__msg=null;"
    if msg:
        msgscript = f'window.__msg=["{msg[0]}","{html.escape(msg[1])}"];'
    return page("管理员登录", f"""
<script>{msgscript}</script>
<div class="auth">
  <div class="auth-card">
    <div class="logo">🔐</div>
    <h2>管理员登录</h2>
    <form method="post" action="{U("/admin/login")}">
      <input type="password" name="password" placeholder="请输入管理员密码" autofocus autocomplete="current-password">
      <button class="btn btn-primary">登 录</button>
    </form>
    <a class="btn btn-ghost" href="{U("/")}" style="margin-top:10px">返回资源库</a>
  </div>
</div>
""")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ShareSrv/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def end_headers(self):
        rc = getattr(self, "_renew_cookie", None)
        if rc:
            self.send_header("Set-Cookie", rc)
        super().end_headers()

    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if not getattr(self, "head_only", False):
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _redirect(self, loc):
        self._send(302, "text/plain", b"", {"Location": loc})

    def _read_body(self):
        clen = int(self.headers.get("Content-Length") or 0)
        if clen > 16 * 1024 * 1024:
            return None
        return self.rfile.read(clen)

    def _fields(self, body):
        ctype = self.headers.get("Content-Type", "")
        if "multipart" in ctype:
            fields = parse_multipart(ctype, body)
            out = {}
            for k, v in fields.items():
                if isinstance(v, dict):
                    out[k] = v["filename"]
                else:
                    out[k] = v
            return out
        return dict((k, v) for k, v in urllib.parse.parse_qsl(body.decode("utf-8", "replace")))

    def _fields_list(self, body):
        ctype = self.headers.get("Content-Type", "")
        if "multipart" in ctype:
            return parse_multipart_list(ctype, body)
        out = {}
        for k, v in urllib.parse.parse_qsl(body.decode("utf-8", "replace")):
            out.setdefault(k, []).append(v)
        return out

    def _send_zip(self, items):
        members = []
        for rel in items:
            p = safe_path(rel)
            if p and os.path.exists(p):
                members.append(p)
        if not members:
            self._json({"error": "没有可打包的项目"})
            return
        fname = "batch-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % fname)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()

        class _W(object):
            def __init__(self, f):
                self.f = f

            def write(self, b):
                return self.f.write(b)

            def seekable(self):
                return False

            def flush(self):
                try:
                    self.f.flush()
                except AttributeError:
                    pass

        try:
            with zipfile.ZipFile(_W(self.wfile), "w", zipfile.ZIP_DEFLATED) as zf:
                for p in members:
                    if os.path.isfile(p):
                        zf.write(p, arcname=os.path.relpath(p, FILES_DIR).replace("\\", "/"))
                    elif os.path.isdir(p):
                        for root, _dirs, files in os.walk(p):
                            for fn in files:
                                fp = os.path.join(root, fn)
                                zf.write(fp, arcname=os.path.relpath(fp, FILES_DIR).replace("\\", "/"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _send_file(self, target, range_hdr=None):
        size = os.path.getsize(target)
        fname = os.path.basename(target)
        ascii_name = re.sub(r"[^\x20-\x7e]", "_", fname)
        disp = 'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (ascii_name, urllib.parse.quote(fname))
        start, end, status = 0, size - 1, 200
        if range_hdr:
            m = re.match(r"bytes=(\d*)-(\d*)", range_hdr.strip())
            if not m or (m.group(1) == "" and m.group(2) == ""):
                return self._send(416, "text/plain", b"", {"Content-Range": "bytes */%d" % size, "Accept-Ranges": "bytes"})
            s, e = m.group(1), m.group(2)
            if s == "":
                start = max(0, size - int(e))
            else:
                start = int(s)
                end = int(e) if e else size - 1
            if start >= size or start < 0:
                return self._send(416, "text/plain", b"", {"Content-Range": "bytes */%d" % size, "Accept-Ranges": "bytes"})
            end = min(end, size - 1)
            status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", disp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        if getattr(self, "head_only", False):
            return
        try:
            with open(target, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_HEAD(self):
        self.head_only = True
        try:
            self.do_GET()
        finally:
            del self.head_only

    def do_GET(self):
        maybe_cleanup()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            msg = None
            if "msg" in query:
                v = query["msg"][0]
                msg = ("ok", "操作成功") if v == "ok" else ("err", v)
            self._send(200, "text/html; charset=utf-8",
                       public_page(scan_pool(), pool_used(), QUOTA, msg, pending_used(), reserved_used()).encode("utf-8"))
            return

        if path == "/api/files":
            self._json({"data": scan_pool(), "used": pool_used(), "quota": QUOTA, "pending": pending_used(), "reserved": reserved_used()})
            return

        if path == "/api/stats":
            self._json({"used": pool_used(), "quota": QUOTA, "pending": pending_used(), "reserved": reserved_used()})
            return

        if path == "/d":
            name = sanitize_rel(query.get("p", [""])[0]) if "p" in query else ""
            target = safe_path(name) if name else None
            if not target or not os.path.isfile(target):
                self._send(404, "text/html; charset=utf-8", page("未找到", '<div class="card" style="padding:40px;text-align:center"><div class="big" style="font-size:40px">🤷</div><p>文件不存在</p><p style="margin-top:12px"><a class="btn btn-ghost" href="' + U("/") + '">返回资源库</a></p></div>').encode("utf-8"))
                return
            self._send_file(target, self.headers.get("Range"))
            return

        if path.startswith("/d/"):
            name = sanitize_rel(urllib.parse.unquote(path[3:]))
            target = safe_path(name) if name else None
            if not target or not os.path.isfile(target):
                self._send(404, "text/plain", b"not found")
                return
            self._send_file(target, self.headers.get("Range"))
            return

        if path == "/admin":
            if login_ok(self):
                msg = None
                if "msg" in query:
                    v = query["msg"][0]
                    msg = ("ok", "操作成功") if v == "ok" else ("err", v)
                self._send(200, "text/html; charset=utf-8",
                           admin_page(scan_pool(), pool_used(), QUOTA, msg, pending_used(), reserved_used()).encode("utf-8"))
            else:
                msg = None
                if "msg" in query:
                    v = query["msg"][0]
                    msg = ("ok", "操作成功") if v == "ok" else ("err", v)
                self._send(200, "text/html; charset=utf-8", login_page(msg).encode("utf-8"))
            return

        if path == "/admin/logout":
            self._send(302, "text/plain", b"", {"Location": U("/admin"),
                       "Set-Cookie": "share_auth=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"})
            return

        if path == "/admin/upload/status":
            if not login_ok(self):
                self._json({"error": "请先登录"}, 401)
                return
            uid = sanitize_rel(query.get("upload_id", [""])[0])
            meta = upload_meta(uid) if uid else None
            if not meta:
                self._json({"error": "会话不存在"})
                return
            done = []
            udir = os.path.join(UPLOADS_DIR, uid)
            for i in range(meta["total_chunks"]):
                if os.path.isfile(os.path.join(udir, str(i))):
                    done.append(i)
            self._json({"upload_id": uid, "done": done,
                        "total_chunks": meta["total_chunks"],
                        "path": meta["path"], "size": meta["size"]})
            return

        if path == "/admin/log":
            if not login_ok(self):
                self._json({"error": "请先登录"}, 401)
                return
            try:
                logfile = os.path.join(BASE_DIR, "logs", "share.log")
                with open(logfile, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                self._json({"ok": True, "log": "".join(lines[-300:])})
            except OSError:
                self._json({"ok": True, "log": "（暂无日志文件）"})
            return

        if path == "/admin/cache":
            if not login_ok(self):
                self._json({"error": "请先登录"}, 401)
                return
            items = []
            if os.path.isdir(UPLOADS_DIR):
                for d in sorted(os.listdir(UPLOADS_DIR)):
                    dp = os.path.join(UPLOADS_DIR, d)
                    if not os.path.isdir(dp):
                        continue
                    meta = upload_meta(d)
                    chunks = []
                    total = 0
                    for f in os.listdir(dp):
                        fp = os.path.join(dp, f)
                        if f.isdigit() and os.path.isfile(fp):
                            chunks.append(f)
                            try:
                                total += os.path.getsize(fp)
                            except OSError:
                                pass
                    items.append({
                        "hash": d,
                        "path": meta["path"] if meta else "?",
                        "size": meta["size"] if meta else 0,
                        "chunks_done": len(chunks),
                        "chunks_total": meta["total_chunks"] if meta else 0,
                        "bytes": total,
                        "bytes_h": human_size(total),
                        "last_activity": fmt_time(os.path.getmtime(dp)),
                    })
            self._json({"ok": True, "items": items, "count": len(items)})
            return

        self._send(404, "text/html; charset=utf-8", page("404", '<div class="card" style="padding:40px;text-align:center"><p>页面不存在</p></div>').encode("utf-8"))

    def do_POST(self):
        global ADMIN_PASSWORD_HASH
        maybe_cleanup()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/admin/login":
            body = self._read_body()
            fields = self._fields(body) if body is not None else {}
            pw = str(fields.get("password", ""))
            if hashlib.sha256(pw.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
                self._send(302, "text/plain", b"", {
                    "Location": U("/admin"),
                    "Set-Cookie": f"share_auth={make_token()}; Max-Age={SESSION_DAYS * 86400}; Path=/; HttpOnly; SameSite=Lax",
                })
            else:
                self._redirect(admin_uri("密码错误"))
            return

        if path == "/zip":
            body = self._read_body()
            fields = self._fields_list(body) if body is not None else {}
            items = []
            for p in fields.get("path", []):
                rel = sanitize_rel(p)
                if rel and safe_path(rel):
                    items.append(rel)
            items = items[:500]
            if not items:
                self._json({"error": "没有可打包的项目"})
                return
            self._send_zip(items)
            return

        if not login_ok(self):
            self._json({"error": "请先登录"}, 401)
            return

        if path == "/admin/upload/chunk":
            uid = sanitize_rel(query.get("upload_id", [""])[0])
            try:
                index = int(query.get("index", ["-1"])[0])
            except ValueError:
                index = -1
            meta = upload_meta(uid) if uid else None
            if not meta:
                self._json({"error": "上传会话不存在，请重新选择文件"}, 400)
                return
            if index < 0 or index >= meta["total_chunks"]:
                self._json({"error": "分片越界"}, 400)
                return
            clen = int(self.headers.get("Content-Length") or 0)
            if clen > CHUNK:
                self._json({"error": "分片超过 5MB 限制"}, 400)
                return
            data = self.rfile.read(clen)
            expect = chunk_expected_len(meta["size"], meta["total_chunks"], index)
            if len(data) != expect:
                self._json({"error": "分片长度不匹配，请重传此片"}, 400)
                return
            sha = query.get("sha256", [""])[0]
            if sha and not re.fullmatch(r"[0-9a-f]{64}", sha):
                self._json({"error": "校验参数不合法"}, 400)
                return
            if sha and hashlib.sha256(data).hexdigest() != sha:
                self._json({"error": "分片校验失败（内容不符），请重传此片"}, 400)
                return
            with open(os.path.join(UPLOADS_DIR, uid, str(index)), "wb") as f:
                f.write(data)
            touch_upload(uid)
            self._json({"ok": True, "index": index})
            return

        body = self._read_body()
        fields = self._fields(body) if body is not None else {}

        if path == "/admin/upload/init":
            rel = sanitize_rel(fields.get("path", ""))
            try:
                size = int(fields.get("size", 0))
                lastModified = int(fields.get("lastModified", 0))
            except ValueError:
                size = lastModified = 0
            fhash = str(fields.get("file_hash", "") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", fhash):
                fhash = ""
            if not rel or size < 0:
                self._json({"error": "参数不合法"})
                return
            target = safe_path(rel)
            if not target:
                self._json({"error": "非法路径"})
                return
            if os.path.isdir(target):
                self._json({"error": "已存在同名文件夹"})
                return
            uid = hashlib.sha256(f"{rel}:{size}:{lastModified}".encode()).hexdigest()[:24]
            meta = upload_meta(uid)
            if meta and (meta["path"] != rel or meta["size"] != size or meta["lastModified"] != lastModified):
                shutil.rmtree(os.path.join(UPLOADS_DIR, uid), ignore_errors=True)
                unregister_uid(uid)
                meta = None
            if not meta and fhash:
                uid2 = load_registry().get(fhash)
                m2 = upload_meta(uid2) if uid2 else None
                if m2 and m2.get("size") == size:
                    uid = uid2
                    meta = m2
            total = total_chunks_for(size)
            udir = os.path.join(UPLOADS_DIR, uid)
            cur = rel
            while "/" in cur:
                cur = cur.rsplit("/", 1)[0]
                if os.path.isfile(safe_path(cur)):
                    self._json({"error": "无法写入：路径中存在同名文件 " + cur})
                    return
            used = pool_used()
            this_need = size
            if os.path.isfile(target):
                this_need = max(0, size - os.path.getsize(target))
            committed = reserved_used()
            if meta:
                needv = meta.get("need")
                committed -= int(needv) if needv is not None else int(meta.get("size") or 0)
            if used + committed + this_need > QUOTA:
                self._json({"error": "池容量不足，剩余 %s，需要 %s" % (human_size(max(0, QUOTA - used - committed)), human_size(size))})
                return
            if meta and meta.get("need") != this_need:
                meta["need"] = this_need
                write_meta(uid, meta)
            if not meta:
                write_meta(uid, {"path": rel, "size": size, "lastModified": lastModified,
                                 "total_chunks": total, "created": int(time.time()),
                                 "file_hash": fhash, "need": this_need})
                if fhash:
                    register_hash(fhash, uid)
            touch_upload(uid)
            done = []
            for i in range(total):
                if os.path.isfile(os.path.join(udir, str(i))):
                    done.append(i)
            self._json({"upload_id": uid, "done": done, "total_chunks": total})
            return

        if path == "/admin/upload/complete":
            uid = sanitize_rel(fields.get("upload_id", ""))
            meta = upload_meta(uid) if uid else None
            if not meta:
                self._json({"error": "上传会话不存在"})
                return
            rel = meta["path"]
            size = meta["size"]
            target = safe_path(rel)
            if not target:
                self._json({"error": "非法路径"})
                return
            udir = os.path.join(UPLOADS_DIR, uid)
            if (os.path.isfile(target) and os.path.getsize(target) == size
                    and not os.path.isfile(os.path.join(udir, "0"))):
                if meta.get("file_hash"):
                    unregister_hash(meta["file_hash"])
                shutil.rmtree(udir, ignore_errors=True)
                self._json({"ok": True, "path": rel})
                return
            total = meta["total_chunks"]
            missing = [i for i in range(total) if not os.path.isfile(os.path.join(udir, str(i)))]
            if missing:
                self._json({"error": "还有 %d 个分片未上传" % len(missing), "missing": missing})
                return
            for i in range(total):
                expect = chunk_expected_len(size, total, i)
                if os.path.getsize(os.path.join(udir, str(i))) != expect:
                    self._json({"error": "分片数据异常，请重新上传"})
                    return
            os.makedirs(os.path.dirname(target), exist_ok=True)
            final = target
            tmp = final + ".part"
            ok = False
            try:
                with open(tmp, "wb") as out:
                    for i in range(total):
                        with open(os.path.join(udir, str(i)), "rb") as ch:
                            shutil.copyfileobj(ch, out)
                if os.path.getsize(tmp) != size:
                    self._json({"error": "合并后大小校验失败"})
                else:
                    os.replace(tmp, final)
                    ok = True
            except OSError:
                self._json({"error": "写入失败，磁盘可能已满"})
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                shutil.rmtree(udir, ignore_errors=True)
            if ok:
                if meta.get("file_hash"):
                    unregister_hash(meta["file_hash"])
                self._json({"ok": True, "path": os.path.relpath(final, FILES_DIR).replace("\\", "/")})
            return

        if path == "/admin/upload/cancel":
            purge = fields.get("purge", "0") == "1"
            release = fields.get("release", "0") == "1"
            uid = sanitize_rel(fields.get("upload_id", ""))
            if not uid:
                rel = sanitize_rel(fields.get("path", ""))
                try:
                    size = int(fields.get("size", 0))
                    lastModified = int(fields.get("lastModified", 0))
                except ValueError:
                    size = lastModified = 0
                if rel:
                    uid = hashlib.sha256(f"{rel}:{size}:{lastModified}".encode()).hexdigest()[:24]
            if release and uid and upload_meta(uid):
                meta = upload_meta(uid)
                if meta and meta.get("need"):
                    meta["need"] = 0
                    write_meta(uid, meta)
            if purge and uid and upload_meta(uid):
                meta = upload_meta(uid)
                if meta and meta.get("file_hash"):
                    unregister_hash(meta["file_hash"])
                shutil.rmtree(os.path.join(UPLOADS_DIR, uid), ignore_errors=True)
            self._json({"ok": True, "kept": not purge})
            return

        if path == "/admin/upload/clear":
            freed = clear_uploads()
            LOG.info("cleared all pending chunks, freed %s", human_size(freed))
            self._json({"ok": True, "freed": freed, "freed_h": human_size(freed)})
            return

        if path == "/admin/password":
            old = str(fields.get("old_password", ""))
            new = str(fields.get("new_password", ""))
            if hashlib.sha256(old.encode()).hexdigest() != ADMIN_PASSWORD_HASH:
                self._json({"error": "旧密码错误"})
                return
            if not new:
                self._json({"error": "新密码不能为空"})
                return
            ADMIN_PASSWORD_HASH = hashlib.sha256(new.encode()).hexdigest()
            cfg = load_config()
            cfg["admin_password_hash"] = ADMIN_PASSWORD_HASH
            save_config(cfg)
            LOG.info("admin password changed")
            self._json({"ok": True})
            return

        if path == "/admin/quota":
            try:
                gb = float(fields.get("gb", ""))
            except (ValueError, TypeError):
                self._json({"error": "参数不合法"})
                return
            if not (0.5 <= gb <= 200):
                self._json({"error": "容量需在 0.5 ~ 200 GB 之间"})
                return
            new_q = int(gb * 1024 * 1024 * 1024)
            used = pool_used()
            if used > new_q:
                self._json({"error": "当前已用 %s，超过目标容量 %s，请先删除部分文件或设置更大容量" % (human_size(used), human_size(new_q))})
                return
            set_quota(new_q)
            LOG.info("quota changed to %s", human_size(QUOTA))
            self._json({"ok": True, "quota": QUOTA, "quota_h": human_size(QUOTA)})
            return

        if path == "/admin/mkdir":
            rel = sanitize_rel(fields.get("path", ""))
            target = safe_path(rel)
            if not target:
                self._json({"error": "非法路径"})
                return
            if os.path.exists(target):
                self._json({"error": "同名文件夹已存在"})
                return
            try:
                os.makedirs(target, exist_ok=True)
                self._json({"ok": True, "path": rel})
            except OSError:
                self._json({"error": "创建失败"})
            return

        if path == "/admin/delete":
            rel = sanitize_rel(fields.get("path", ""))
            is_dir = fields.get("is_dir", "0") == "1"
            target = safe_path(rel)
            if not target:
                self._json({"error": "非法路径"})
                return
            if is_dir and os.path.isdir(target):
                try:
                    shutil.rmtree(target)
                    self._json({"ok": True})
                except OSError:
                    self._json({"error": "删除失败"})
            elif os.path.isfile(target):
                try:
                    os.remove(target)
                    self._json({"ok": True})
                except OSError:
                    self._json({"error": "删除失败"})
            else:
                self._json({"error": "目标不存在"})
            return

        if path == "/admin/batch":
            fl = self._fields_list(body) if body is not None else {}
            op = fl.get("op", [""])[0]
            if op != "delete":
                self._json({"error": "未知操作"})
                return
            paths = [sanitize_rel(p) for p in fl.get("path", [])]
            paths = [p for p in paths if p]
            if not paths:
                self._json({"error": "没有选择项目"})
                return
            done, failed = 0, []
            for rel in paths:
                target = safe_path(rel)
                if not target:
                    failed.append({"path": rel, "error": "非法路径"})
                    continue
                try:
                    if os.path.isdir(target):
                        shutil.rmtree(target)
                    elif os.path.isfile(target):
                        os.remove(target)
                    else:
                        failed.append({"path": rel, "error": "目标不存在"})
                        continue
                    done += 1
                except OSError:
                    failed.append({"path": rel, "error": "删除失败"})
            self._json({"ok": True, "done": done, "failed": failed})
            return

        self._json({"error": "not found"}, 404)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18888)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--prefix", default="/share")
    ap.add_argument("--quota-gb", type=float, default=10.0)
    args = ap.parse_args()
    global PREFIX, QUOTA
    PREFIX = args.prefix.rstrip("/") or ""
    cfg = load_config()
    if not cfg.get("quota"):
        QUOTA = int(args.quota_gb * 1024 * 1024 * 1024)
        cfg["quota"] = QUOTA
        save_config(cfg)
    else:
        QUOTA = int(cfg["quota"])
    os.makedirs(FILES_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    cleanup_uploads()
    import threading

    def _sweep():
        while True:
            time.sleep(60)
            try:
                cleanup_uploads()
            except Exception:
                pass

    threading.Thread(target=_sweep, daemon=True, name="upload-sweeper").start()
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    LOG.info("ShareSrv listening on %s:%d prefix=%s quota=%s files=%s",
             args.host, args.port, PREFIX, human_size(QUOTA), FILES_DIR)
    server.serve_forever()


if __name__ == "__main__":
    main()
