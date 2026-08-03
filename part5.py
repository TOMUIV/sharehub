
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

        if path == "/admin/rename":
            old = sanitize_rel(fields.get("old", ""))
            new = sanitize_rel(fields.get("new", ""))
            t_old = safe_path(old) if old else None
            t_new = safe_path(new) if new else None
            if not t_old or not t_new:
                self._json({"error": "非法路径"})
                return
            if not os.path.exists(t_old):
                self._json({"error": "目标不存在"})
                return
            if os.path.exists(t_new):
                self._json({"error": "同名目标已存在"})
                return
            try:
                os.rename(t_old, t_new)
                self._json({"ok": True, "path": new})
            except OSError:
                self._json({"error": "重命名失败"})
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
