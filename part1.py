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
