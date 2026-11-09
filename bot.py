#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RexStüdyo TikTok LIVE event server (best-effort support for TikTokLive versions)."""
import asyncio, hmac, html, json, re, os, queue, random, secrets, sys, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    from TikTokLive import TikTokLiveClient
    import TikTokLive.events as tiktok_events
except Exception as exc:
    TikTokLiveClient = None
    tiktok_events = None
    TIKTOK_IMPORT_ERROR = str(exc)
else:
    TIKTOK_IMPORT_ERROR = ""

PORT = int(os.environ.get("REXSTUDIO_PORT", "8080"))
SITE_URL = "https://rexstudyo.site"
HERE = os.path.dirname(os.path.abspath(__file__))
THREE_FILE = next((os.path.join(HERE, n) for n in ("three_r128_min.js", "three.r128.min.js") if os.path.exists(os.path.join(HERE, n))), os.path.join(HERE, "three.r128.min.js"))
THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"

# ============================================================
# LİSANS / OTURUM SİSTEMİ
# ============================================================
KEYS_FILE = os.path.join(HERE, "keys.json")
TG_FILE = os.path.join(HERE, "tg_config.json")
ORDERS_FILE = os.path.join(HERE, "orders.json")

def _file_cfg():
    try:
        with open(TG_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

_FC = _file_cfg()
# Gizli bilgiler: önce ortam değişkeni, sonra tg_config.json. İkisi de yoksa rastgele geçici şifre.
ADMIN_SECRET = os.environ.get("REX_ADMIN_SECRET") or str(_FC.get("admin_secret", "")).strip()
ADMIN_PASS = os.environ.get("REX_ADMIN_PASS") or str(_FC.get("admin_pass", "")).strip()
ADMIN_PASS_GENERATED = False
if not ADMIN_PASS:
    ADMIN_PASS = "******"
    ADMIN_PASS_GENERATED = True
AUTH_DISABLED = os.environ.get("REX_AUTH_DISABLED", "0") == "1"

SESSIONS = {}
SESSIONS_LOCK = threading.RLock()
ADMIN_SESSIONS = {}
ADMIN_LOCK = threading.RLock()

PRODUCTS = {
    "trial":   {"name": "Deneme Sürümü",     "days": 7,   "plan": "trial"},
    "weekly":  {"name": "1 Haftalık Üyelik", "days": 7,   "plan": "weekly"},
    "monthly": {"name": "1 Aylık Üyelik",    "days": 30,  "plan": "monthly"},
    "yearly":  {"name": "Yıllık Paket",      "days": 365, "plan": "yearly"},
}


# ============================================================
# TELEGRAM BİLDİRİM + SİPARİŞ SİSTEMİ
# ============================================================
# Ayar: ortam değişkeni (TG_BOT_TOKEN, TG_CHAT_ID) veya bot.py yanındaki tg_config.json:
#   {"token": "123456:ABC...", "chat_id": "123456789"}
TG_FILE = os.path.join(HERE, "tg_config.json")
ORDERS_FILE = os.path.join(HERE, "orders.json")
ORDERS_LOCK = threading.RLock()
ORDER_HITS = {}

def _tg_cfg():
    c = {"token": os.environ.get("TG_BOT_TOKEN", "").strip(), "chat_id": os.environ.get("TG_CHAT_ID", "").strip()}
    try:
        with open(TG_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("token") and not c["token"]: c["token"] = str(d["token"]).strip()
        if d.get("chat_id") and not c["chat_id"]: c["chat_id"] = str(d["chat_id"]).strip()
    except Exception:
        pass
    return c

def tg_api(method, payload, timeout=35):
    c = _tg_cfg()
    if not c["token"]:
        raise RuntimeError("TG_BOT_TOKEN ayarlı değil")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{c['token']}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", "ignore")[:300]
        except Exception: pass
        raise RuntimeError(f"Telegram HTTP {e.code}: {body}")

def tg_send(text, buttons=None, chat_id=None):
    c = _tg_cfg()
    chat_id = chat_id or c["chat_id"]
    if not c["token"] or not chat_id:
        print("[TELEGRAM] ⚠️ token / chat_id ayarlı değil, bildirim gönderilemedi")
        return False
    body = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": buttons}
    try:
        j = tg_api("sendMessage", body, 15)
        if not j.get("ok"):
            print("[TELEGRAM] gönderilemedi:", j)
        return bool(j.get("ok"))
    except Exception as e:
        print("[TELEGRAM] gönderilemedi:", repr(e))
        return False

def _atomic_write(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[UYARI] Dosya değiştirilemedi (kilitli olabilir), doğrudan yazılıyor: {e}")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            print(f"[HATA] Dosya yazılamadı: {ex}")
            raise ex
    finally:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except Exception: pass

def _same(a, b):
    return hmac.compare_digest(str(a or "").encode("utf-8"), str(b or "").encode("utf-8"))

def _read_json(handler, limit=20000):
    try:
        n = min(int(handler.headers.get("Content-Length", 0) or 0), limit)
        raw = handler.rfile.read(n).decode("utf-8", "ignore") if n > 0 else ""
        d = json.loads(raw or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

ADMIN_FAILS = {}
ADMIN_FAIL_LOCK = threading.Lock()

def _admin_locked(ip):
    now = time.time()
    with ADMIN_FAIL_LOCK:
        hits = [t for t in ADMIN_FAILS.get(ip, []) if now - t < 600]
        ADMIN_FAILS[ip] = hits
        return len(hits) >= 10

def _admin_fail(ip):
    with ADMIN_FAIL_LOCK:
        ADMIN_FAILS.setdefault(ip, []).append(time.time())

def _admin_ok(ip):
    with ADMIN_FAIL_LOCK:
        ADMIN_FAILS.pop(ip, None)

def _load_orders():
    try:
        with open(ORDERS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _save_orders(o):
    _atomic_write(ORDERS_FILE, o)

def _order_text(o):
    return (f"🛒 <b>YENİ SİPARİŞ</b>  #{o['id']}\n\n"
            f"📦 Paket: <b>{html.escape(o['plan_name'])}</b>\n"
            f"📱 İletişim: <code>{html.escape(o['contact'])}</code>\n"
            f"🕒 Zaman: {o['created'][:19].replace('T', ' ')}\n"
            f"🌐 IP: {html.escape(o.get('ip') or '-')}\n\n"
            f"Ödemeyi kontrol et, sonra butona bas.")

def _order_done_text(o):
    plan = html.escape(o.get("plan_name", ""))
    contact = html.escape(o.get("contact") or "-")
    if o.get("status") == "approved":
        exp = (o.get("expires") or "Süresiz")[:10]
        return (f"✅ <b>ONAYLANDI</b>  #{o['id']}\n\n"
                f"📦 {plan}\n📱 Müşteri: {contact}\n\n"
                f"🔑 Lisans anahtarı:\n<code>{o['key']}</code>\n\n"
                f"Bu anahtarı müşteriye ilet.\nBitiş: {exp}")
    return f"❌ <b>REDDEDİLDİ</b>  #{o['id']}\n\n📦 {plan}\n📱 Müşteri: {contact}"

def create_order(product, contact, ip, ua):
    p = PRODUCTS[product]
    with ORDERS_LOCK:
        orders = _load_orders()
        oid = secrets.token_hex(3).upper()
        while oid in orders:
            oid = secrets.token_hex(3).upper()
        o = {"id": oid, "product": product, "plan_name": p["name"], "contact": contact,
             "ip": ip, "ua": (ua or "")[:200], "created": datetime.now().isoformat(),
             "status": "pending", "key": None}
        orders[oid] = o
        _save_orders(orders)
    ok = tg_send(_order_text(o), [[
        {"text": "✅ Onayla (Key üret)", "callback_data": f"ok:{product}:{oid}"},
        {"text": "❌ Reddet", "callback_data": f"no:{product}:{oid}"}]])
    print(f"[SİPARİŞ] #{oid} · {p['name']} · {contact} · telegram={'OK' if ok else 'HATA'}")
    return o, ok

def _tg_safe(method, payload, timeout=15):
    try:
        return tg_api(method, payload, timeout)
    except Exception as e:
        print(f"[TELEGRAM] {method} hatası:", repr(e)[:160])
        return None

def _tg_answer(cb_id, text, alert=False):
    _tg_safe("answerCallbackQuery", {"callback_query_id": cb_id, "text": str(text)[:200], "show_alert": bool(alert)}, 10)

def _decide_order(oid, action, product=None, contact=None):
    """Onay/red tek noktadan. Dönüş: (sipariş, hata_metni_veya_None, anahtar_veya_None)."""
    with ORDERS_LOCK:
        orders = _load_orders()
        o = orders.get(oid)
        if o is None:
            if product not in PRODUCTS:
                return None, "Sipariş bulunamadı", None
            o = {"id": oid, "product": product, "plan_name": PRODUCTS[product]["name"],
                 "contact": contact or "", "created": datetime.now().isoformat(),
                 "status": "pending", "key": None}
        if o.get("status") != "pending":
            return o, "Bu sipariş zaten işlendi", o.get("key")
        p = PRODUCTS.get(o.get("product"))
        if not p:
            return o, "Geçersiz paket", None
        if action == "ok":
            key, info = create_key(p["days"], p["plan"], o.get("contact", ""), order_id=oid)
            o.update(status="approved", key=key, expires=info.get("expires"),
                     approved_at=datetime.now().isoformat())
        elif action == "no":
            o.update(status="rejected", rejected_at=datetime.now().isoformat())
        else:
            return o, "Geçersiz işlem", None
        orders[oid] = o
        _save_orders(orders)
    print(f"[SİPARİŞ] #{oid} → {o['status']}" + (f" · {o['key']}" if o.get("key") else ""))
    return o, None, o.get("key")

def _tg_handle_update(u):
    cfg = _tg_cfg()
    admin_chat = str(cfg["chat_id"])
    msg = u.get("message")
    if msg:
        txt = str(msg.get("text") or "")
        cid = msg.get("chat", {}).get("id")
        if txt.startswith(("/start", "/id")):
            tg_send(f"Chat ID'n: <code>{cid}</code>", chat_id=cid)
        return
    cb = u.get("callback_query")
    if not cb:
        return
    cb_id = cb.get("id")
    m = cb.get("message") or {}
    cid = str(m.get("chat", {}).get("id", ""))
    if not admin_chat or cid != admin_chat:
        _tg_answer(cb_id, "Yetkisiz", True)
        return
    parts = str(cb.get("data", "")).split(":")
    if len(parts) != 3 or parts[0] not in ("ok", "no"):
        _tg_answer(cb_id, "Geçersiz işlem", True)
        return
        
    # BUTONA BASILDIĞI AN CEVAP VER (Sonsuz yüklenmeyi engeller)
    _tg_answer(cb_id, "İşleniyor...")

    action, product, oid = parts
    print(f"[TELEGRAM] buton: {'onay' if action == 'ok' else 'red'} #{oid}")
    mt = re.search(r"İletişim:\s*(.+)", str(m.get("text") or ""))
    contact = mt.group(1).strip() if mt else ""
    
    try:
        o, err, _ = _decide_order(oid, action, product, contact)
        
        if o is None or err:
            _tg_answer(cb_id, err or "Sipariş bulunamadı", True)
            return
            
        text = _order_done_text(o)
        if m.get("message_id"):
            res = _tg_safe("editMessageText", {"chat_id": m["chat"]["id"], "message_id": m["message_id"],
                                               "text": text, "parse_mode": "HTML"})
            if not (res and res.get("ok")):
                tg_send(text, chat_id=admin_chat)
        else:
            tg_send(text, chat_id=admin_chat)
    except Exception as e:
        print(f"[TELEGRAM] Sipariş işlenirken hata: {repr(e)}")
        tg_send(f"⚠️ <b>Sipariş işlenirken hata oluştu!</b>\n\n<code>{html.escape(str(e))}</code>", chat_id=admin_chat)

def tg_poll_loop():
    if not _tg_cfg()["token"]:
        return
    try:
        tg_api("deleteWebhook", {}, 10)
    except Exception as e:
        print("[TELEGRAM] deleteWebhook:", repr(e)[:120])
    offset = 0
    while True:
        try:
            j = tg_api("getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]}, 40)
            for u in j.get("result", []):
                offset = u["update_id"] + 1
                try:
                    _tg_handle_update(u)
                except Exception as e:
                    print("[TELEGRAM] update hatası:", repr(e)[:200])
        except Exception as e:
            print("[TELEGRAM] polling hatası:", repr(e)[:200])
            time.sleep(5)

def normalize_contact(raw):
    """Sadece Türkiye cep telefonu (+905xxxxxxxxx) veya e-posta kabul eder. Geçersizse None."""
    c = " ".join(str(raw or "").split())
    if not c or len(c) > 120:
        return None
    if "@" in c:
        e = c.lower()
        return e if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", e) else None
    d = re.sub(r"[\s()\-]", "", c)
    if d.startswith("+"):
        d = d[1:]
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("90") and len(d) == 12:
        d = d[2:]
    if d.startswith("0") and len(d) == 11:
        d = d[1:]
    return "+90" + d if re.fullmatch(r"5\d{9}", d) else None

_PAGE_CSS = ("body{margin:0;background:#07080c;color:#f4f5f8;font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
             "min-height:100vh;display:grid;place-items:center;padding:20px}"
             ".box{width:min(540px,100%);background:#11151d;border:1px solid #232b3d;border-radius:20px;padding:26px}"
             "h1{font-size:22px;margin-bottom:8px}.muted{color:#9aa3b5;font-size:14px}"
             ".code{font:800 18px ui-monospace,Menlo,Consolas,monospace;background:#0b0d13;border:1px dashed #2a3144;padding:12px 14px;border-radius:12px;word-break:break-all;margin:10px 0}"
             ".bank{background:#0b0d13;border:1px solid #232b3d;border-radius:14px;padding:6px 14px;margin:14px 0}"
             ".bank div{padding:10px 0;border-bottom:1px dashed #2a3144;font-size:15px}.bank div:last-child{border:0}"
             ".bank small{display:block;color:#9aa3b5;font-size:12px;font-weight:700}"
             ".warn{background:rgba(239,68,68,.1);border-left:3px solid #ef4444;padding:11px 13px;border-radius:0 10px 10px 0;color:#fca5a5;font-size:14px;margin:12px 0}"
             ".ok{color:#4ade80}.bad{color:#f87171}.pen{color:#fbbf24}"
             "label{display:block;font-size:14px;font-weight:700;margin:12px 0 6px}"
             "input{width:100%;padding:14px;border-radius:12px;border:1px solid #2a3144;background:#0b0d13;color:#fff;font-size:16px}"
             ".btn{display:block;text-align:center;background:linear-gradient(135deg,#ff6b2c,#ff3d6e);color:#fff;padding:14px 18px;border-radius:12px;font-weight:800;text-decoration:none;margin-top:16px;border:0;width:100%;font-size:16px;cursor:pointer}"
             ".link{display:block;text-align:center;color:#9aa3b5;margin-top:14px;font-size:14px}")

def _page(title, body):
    return ('<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex">'
            '<title>' + html.escape(title) + ' · RexStüdyo</title>'
            '<style>' + _PAGE_CSS + '</style></head><body><div class="box">' + body + '</div></body></html>')

def _page_msg(title, text, back=None):
    back = back or SITE_URL
    return _page(title, '<h1>' + html.escape(title) + '</h1><p class="muted">' + html.escape(text) + '</p>'
                 '<a class="btn" href="' + html.escape(back) + '">Siteye dön</a>')

def _bank_html():
    return ('<div class="bank">'
            '<div><small>Hesap sahibi</small>Moka United Ödeme ve Elektronik Para Kuruluşu A.Ş.</div>'
            '<div><small>IBAN</small>TR23 0010 3000 0000 0001 4365 322</div>'
            '<div><small>Açıklama (zorunlu)</small><b>16582930611</b></div></div>')

def _page_order(o):
    oid = html.escape(o["id"])
    return _page("Siparişiniz alındı",
        '<h1 class="ok">Siparişiniz alındı</h1>'
        '<p class="muted">' + html.escape(o.get("plan_name", "")) + ' · Sipariş numaranız:</p>'
        '<div class="code">#' + oid + '</div>'
        + _bank_html() +
        '<div class="warn">Transfer açıklamasına <b>mutlaka 16582930611</b> yazın. Dekontu '
        '<b>parakazanrex@gmail.com</b> adresine sipariş numaranızla birlikte gönderin.</div>'
        '<p class="muted">Ödemeniz onaylanınca lisans anahtarınız iletişim bilginize gönderilir. '
        'Sipariş durumunu aşağıdaki bağlantıdan da görebilirsiniz.</p>'
        '<a class="btn" href="/takip?id=' + oid + '">Siparişimi takip et</a>'
        '<a class="link" href="' + html.escape(SITE_URL) + '">Siteye dön</a>')

def _page_track_form(oid="", err=""):
    body = '<h1>Siparişimi takip et</h1><p class="muted">Sipariş numaranızı ve sipariş sırasında girdiğiniz telefon veya e-postayı yazın.</p>'
    if err:
        body += '<div class="warn">' + html.escape(err) + '</div>'
    body += ('<form method="GET" action="/takip">'
             '<label for="id">Sipariş numarası</label><input id="id" name="id" value="' + html.escape(oid) + '" maxlength="12" autocomplete="off" style="text-transform:uppercase">'
             '<label for="contact">Telefon veya e-posta</label><input id="contact" name="contact" maxlength="120" autocomplete="off">'
             '<button class="btn" type="submit">Sorgula</button></form>'
             '<a class="link" href="' + html.escape(SITE_URL) + '">Siteye dön</a>')
    return _page("Siparişimi takip et", body)

def _page_track_result(o):
    st = {"pending": ("pen", "Ödeme onayı bekleniyor"), "approved": ("ok", "Onaylandı"), "rejected": ("bad", "Reddedildi")}
    cls, label = st.get(o.get("status"), ("pen", html.escape(str(o.get("status")))))
    body = ('<h1>Sipariş durumu</h1><p class="muted">' + html.escape(o.get("plan_name", "")) + '</p>'
            '<div class="code">#' + html.escape(o["id"]) + '</div>'
            '<p>Durum: <b class="' + cls + '">' + label + '</b></p>')
    if o.get("status") == "approved" and o.get("key"):
        body += ('<div class="bank"><div><small>Lisans anahtarınız</small><b class="ok" style="word-break:break-all">'
                 + html.escape(o["key"]) + '</b></div></div>'
                 '<p class="muted">Bu anahtarı yalnızca siz kullanın. Giriş için panele giriş yapın.</p>'
                 '<a class="btn" href="http://rexstudyo.cc.cd:3137/giris">Panele Giriş Yap</a>')
    elif o.get("status") == "pending":
        body += '<p class="muted">Dekontunuz kontrol edildikten sonra bu sayfada anahtarınızı göreceksiniz.</p>'
    elif o.get("status") == "rejected":
        body += '<div class="warn">Bu sipariş reddedildi. Yardım için parakazanrex@gmail.com adresine yazın.</div>'
    body += '<a class="link" href="' + html.escape(SITE_URL) + '">Siteye dön</a>'
    return _page("Sipariş durumu", body)

def _order_rate_ok(ip, limit=5):
    now = time.time()
    hits = [t for t in ORDER_HITS.get(ip, []) if now - t < 600]
    if len(hits) >= limit:
        ORDER_HITS[ip] = hits
        return False
    hits.append(now)
    ORDER_HITS[ip] = hits
    if len(ORDER_HITS) > 2000:
        ORDER_HITS.pop(next(iter(ORDER_HITS)))
    return True

KEYS_LOCK = threading.RLock()

def _load_keys():
    try:
        with open(KEYS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _save_keys(k):
    _atomic_write(KEYS_FILE, k)

def create_key(days, plan, owner="", order_id=""):
    with KEYS_LOCK:
        keys = _load_keys()
        while True:
            key = f"REX-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
            if key not in keys:
                break
        now = datetime.now()
        keys[key] = {
            "plan": plan, "owner": owner, "order_id": order_id,
            "expires": (now + timedelta(days=days)).isoformat() if days > 0 else None,
            "created": now.isoformat(), "active": True,
            "device": "", "device_locked_at": None,
            "last_login": None, "last_ip": None, "last_ua": None,
            "login_count": 0, "history": [],
        }
        _save_keys(keys)
        return key, keys[key]

def admin_key_action(key, action, days=0):
    with KEYS_LOCK:
        keys = _load_keys()
        if key not in keys:
            return False, "Anahtar bulunamadı"
        k = keys[key]
        if action == "reset":
            k["device"] = ""
            k["device_locked_at"] = None
            msg = "Cihaz kilidi sıfırlandı"
        elif action == "cancel":
            k["active"] = False
            msg = "Anahtar iptal edildi"
        elif action == "activate":
            k["active"] = True
            msg = "Anahtar tekrar aktif"
        elif action == "delete":
            del keys[key]
            msg = "Anahtar silindi"
        elif action == "extend" and days > 0:
            base = datetime.now()
            if k.get("expires"):
                try:
                    base = max(base, datetime.fromisoformat(k["expires"]))
                except Exception:
                    pass
            k["expires"] = (base + timedelta(days=days)).isoformat()
            msg = f"{days} gün eklendi. Yeni bitiş: {k['expires'][:10]}"
        else:
            return False, "Geçersiz aksiyon"
        _save_keys(keys)
    if action in ("reset", "cancel", "delete"):
        with SESSIONS_LOCK:
            for tok, s in list(SESSIONS.items()):
                if s.get("key") == key:
                    SESSIONS.pop(tok, None)
    print(f"[ADMIN] {action} · {key[:12]}…")
    return True, msg

def validate_key(key):
    key = str(key or "").strip().upper()
    if not key:
        return False, "Anahtar gerekli"
    keys = _load_keys()
    if key not in keys:
        return False, "Geçersiz anahtar"
    d = keys[key]
    if d.get("active") is False:
        return False, "Anahtar iptal edilmiş"
    exp = d.get("expires")
    if exp:
        try:
            if datetime.fromisoformat(exp) < datetime.now():
                return False, f"Lisans süresi doldu ({exp[:10]})"
        except Exception:
            pass
    return True, d

def check_device(key, device):
    keys = _load_keys()
    k = keys.get(key)
    if not k:
        return False, "Geçersiz anahtar"
    locked = k.get("device") or ""
    if not locked or locked == device:
        return True, None
    return False, "Bu anahtar başka bir cihaza kilitlenmiş. Yönetici ile iletişime geçin."

def lock_device(key, device, ip, ua):
    with KEYS_LOCK:
        keys = _load_keys()
        if key not in keys:
            return
        k = keys[key]
        now = datetime.now().isoformat()
        if not k.get("device"):
            k["device"] = device
            k["device_locked_at"] = now
        k["last_login"] = now
        k["last_ip"] = ip
        k["last_ua"] = (ua or "")[:200]
        k["login_count"] = int(k.get("login_count", 0)) + 1
        h = k.get("history") or []
        h.append({"at": now, "ip": ip})
        k["history"] = h[-20:]
        _save_keys(keys)

def new_session(key, info, device):
    token = secrets.token_urlsafe(32)
    with SESSIONS_LOCK:
        SESSIONS[token] = {
            "key": key, "device": device,
            "plan": info.get("plan", "?"),
            "expires": info.get("expires"),
            "owner": info.get("owner", ""),
            "created": datetime.now().isoformat(),
        }
    return token

def get_session(token):
    if not token:
        return None
    with SESSIONS_LOCK:
        s = SESSIONS.get(token)
        if not s:
            return None
        exp = s.get("expires")
        if exp:
            try:
                if datetime.fromisoformat(exp) < datetime.now():
                    del SESSIONS[token]
                    return None
            except Exception:
                pass
        return s

def parse_cookie(header):
    out = {}
    if not header:
        return out
    for part in header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k.strip()] = v.strip()
    return out

def new_admin_session():
    t = secrets.token_urlsafe(24)
    with ADMIN_LOCK:
        ADMIN_SESSIONS[t] = {"at": datetime.now().isoformat()}
    return t

def is_admin_token(t):
    with ADMIN_LOCK:
        return bool(t) and t in ADMIN_SESSIONS

def drop_admin(t):
    with ADMIN_LOCK:
        ADMIN_SESSIONS.pop(t, None)

# ---------- HTML ŞABLONLARI ----------
LOGIN_HTML = '''<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>REX Stüdyo · Giriş</title>
<style>
*{box-sizing:border-box;margin:0}
body{min-height:100vh;display:grid;place-items:center;background:radial-gradient(700px 400px at 50% 0,rgba(255,106,43,.18),transparent 60%),#07080b;color:#f2f4f8;font-family:system-ui;padding:20px}
.box{width:min(440px,100%);background:linear-gradient(180deg,#131720,#0e1117);border:1px solid #232836;border-radius:18px;padding:34px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
h1{font-size:22px;font-weight:800;margin-bottom:6px}h1 span{color:#ff6a2b}
.sub{color:#8d95a6;font-size:13px;margin-bottom:20px}
label{display:block;font-size:12px;color:#8d95a6;margin-bottom:6px;font-weight:600}
input{width:100%;padding:14px;border-radius:10px;border:1px solid #232836;background:#0b0d12;color:#f2f4f8;font:600 15px "Courier New",monospace;letter-spacing:1.5px;text-align:center;outline:none}
input:focus{border-color:#ff6a2b;box-shadow:0 0 0 3px rgba(255,106,43,.18)}
button{width:100%;margin-top:16px;padding:14px;border:0;border-radius:10px;background:#ff6a2b;color:#1a0d04;font-size:15px;font-weight:800;cursor:pointer}
button:hover{background:#ff8a4f}button:disabled{opacity:.5;cursor:wait}
.err{margin-top:14px;padding:10px 12px;border-radius:8px;background:rgba(255,60,80,.12);border:1px solid rgba(255,60,80,.3);color:#ff7580;font-size:13px;display:none}
.ok{margin-top:14px;padding:10px 12px;border-radius:8px;background:rgba(88,247,168,.12);border:1px solid rgba(88,247,168,.3);color:#58f7a8;font-size:13px;display:none}
</style></head><body>
<div class="box">
  <h1>REX<span>Stüdyo</span> · Giriş</h1>
  <p class="sub">Satın alma sonrası size verilen anahtarı girin.<br><b style="color:#ffb07a">Not:</b> Anahtar sadece bu cihazda çalışır.</p>
  <label>Lisans Anahtarı</label>
  <input id="key" placeholder="REX-XXXX-XXXX-XXXX" autocomplete="off" spellcheck="false">
  <button id="btn">Giriş Yap</button>
  <div class="err" id="err"></div><div class="ok" id="ok"></div>
</div>
<script>
const $=id=>document.getElementById(id);
const inp=$("key"),btn=$("btn"),err=$("err"),ok=$("ok");
const qk=new URLSearchParams(location.search).get("key");if(qk)inp.value=qk.toUpperCase();
function showE(m){err.textContent=m;err.style.display="block";ok.style.display="none"}
function showO(m){ok.textContent=m;ok.style.display="block";err.style.display="none"}
async function login(){
  const key=inp.value.trim().toUpperCase();if(!key){showE("Anahtar girin");return}
  btn.disabled=true;btn.textContent="Kontrol ediliyor…";
  try{
    const r=await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key})});
    const j=await r.json();
    if(j.ok){showO("Giriş başarılı, yönlendiriliyorsunuz…");setTimeout(()=>location.href="/panel",600);}
    else{showE(j.err||"Geçersiz anahtar");btn.disabled=false;btn.textContent="Giriş Yap";}
  }catch(e){showE("Sunucu hatası: "+e.message);btn.disabled=false;btn.textContent="Giriş Yap";}
}
btn.onclick=login;inp.addEventListener("keydown",e=>{if(e.key==="Enter")login()});
inp.addEventListener("input",e=>{e.target.value=e.target.value.toUpperCase().replace(/[^A-Z0-9-]/g,"")});
</script></body></html>'''

PANEL_HTML = '''<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>REX Stüdyo · Panel</title>
<style>
*{box-sizing:border-box;margin:0}
body{min-height:100vh;background:radial-gradient(900px 500px at 85% -10%,rgba(255,106,43,.14),transparent 60%),#07080b;color:#f2f4f8;font-family:system-ui;padding:30px 20px}
.wrap{max-width:680px;margin:0 auto}
h1{font-size:26px;font-weight:800;margin-bottom:6px}h1 span{color:#ff6a2b}
.sub{color:#8d95a6;font-size:13px;margin-bottom:28px}
.card{background:linear-gradient(180deg,#131720,#0e1117);border:1px solid #232836;border-radius:16px;padding:22px;margin-bottom:16px}
.card h2{font-size:15px;font-weight:700;margin-bottom:14px;color:#ffb07a;letter-spacing:.3px}
.row{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #232836;font-size:14px}
.row:last-child{border:0}.row span{color:#8d95a6}.row b{color:#f2f4f8}
.btn{display:block;text-align:center;padding:15px;border:0;border-radius:10px;font-size:15px;font-weight:800;cursor:pointer;text-decoration:none;margin-top:12px}
.btn.primary{background:#ff6a2b;color:#1a0d04}.btn.primary:hover{background:#ff8a4f}
.btn.danger{background:transparent;color:#ff7580;border:1px solid rgba(255,60,80,.3);font-size:13px;padding:11px}
.tip{font-size:13px;color:#8d95a6;line-height:1.7;margin-top:8px}
</style></head><body>
<div class="wrap">
  <h1>REX<span>Stüdyo</span> · Yayın Paneli</h1>
  <p class="sub">Hoş geldin! Aşağıdan yayın stüdyona giriş yapabilirsin.</p>
  <div class="card">
    <h2>Lisans Bilgileri</h2>
    <div class="row"><span>Plan</span><b id="plan">—</b></div>
    <div class="row"><span>Bitiş</span><b id="expires">—</b></div>
    <div class="row"><span>Durum</span><b id="status" style="color:#58f7a8">Aktif</b></div>
    <div class="row"><span>Cihaz Kilidi</span><b style="color:#58f7a8">Bu cihaza kilitli</b></div>
  </div>
  <div class="card">
    <h2>Yayın Stüdyosu</h2>
    <p class="tip">Aşağıdaki butona basarak stüdyoyu aç. TikTok kullanıcı adını girip "Yayına bağlan" de.</p>
    <a href="/studio" class="btn primary">Stüdyoyu Aç</a>
  </div>
  <a href="/logout" class="btn danger">Çıkış Yap</a>
</div>
<script>
(async()=>{
  try{
    const r=await fetch("/api/session");const j=await r.json();
    if(!j.ok){location.href="https://rexstudyo.site";return}
    document.getElementById("plan").textContent=j.plan||"basic";
    document.getElementById("expires").textContent=j.expires?new Date(j.expires).toLocaleString("tr-TR"):"Süresiz";
  }catch(e){location.href="https://rexstudyo.site"}
})();
</script></body></html>'''

ADMIN_HTML = r'''<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#07080b">
<meta name="robots" content="noindex,nofollow">
<meta name="color-scheme" content="dark">
<title>REX · Yönetim Paneli</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#07080b;--bg2:#0c0e14;--card:#12161f;--card2:#181d29;--line:#242b3c;--line2:#2f3850;
  --text:#f2f4f8;--muted:#8d96aa;--dim:#5d6679;
  --or:#ff6a2b;--or2:#ff8a4f;--ok:#4ade80;--bad:#f87171;--warn:#fbbf24;--cy:#67e8f9;--vi:#a78bfa;
  --r:16px;--r2:12px;
  --st:env(safe-area-inset-top,0px);--sb:env(safe-area-inset-bottom,0px);
  --shadow:0 18px 50px -20px rgba(0,0,0,.7);
}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{background:radial-gradient(900px 480px at 85% -8%,rgba(255,106,43,.11),transparent 60%),radial-gradient(700px 400px at -10% 110%,rgba(103,232,249,.06),transparent 60%),var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased;min-height:100vh;min-height:100dvh;overflow-x:hidden;padding-top:var(--st)}
button,input,select,textarea{font:inherit;color:inherit}
button{cursor:pointer;border:0;background:none;touch-action:manipulation}
a{color:inherit}
input,select,textarea{width:100%;background:var(--bg2);border:1px solid var(--line);border-radius:var(--r2);padding:12px 14px;min-height:48px;font-size:16px;outline:none;transition:border-color .15s,box-shadow .15s}
input:focus,select:focus{border-color:var(--or);box-shadow:0 0 0 4px rgba(255,106,43,.14)}
select{appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);background-position:calc(100% - 18px) 55%,calc(100% - 13px) 55%;background-size:5px 5px;background-repeat:no-repeat;padding-right:36px}
:focus-visible{outline:2px solid var(--cy);outline-offset:2px;border-radius:8px}
.hide{display:none!important}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;word-break:break-all}
.muted{color:var(--muted)}
.dim{color:var(--dim)}
.small{font-size:12.5px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}

/* Düğmeler */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:44px;padding:10px 16px;border-radius:var(--r2);font-weight:700;font-size:14px;background:var(--card2);border:1px solid var(--line2);white-space:nowrap;transition:transform .12s,background .15s,border-color .15s,opacity .15s;user-select:none}
.btn:hover{border-color:#3d4862;background:#1c2331}
.btn:active{transform:scale(.97)}
.btn:disabled{opacity:.5;cursor:wait}
.btn.p{background:linear-gradient(135deg,var(--or),var(--or2));border-color:transparent;color:#1a0d04;box-shadow:0 10px 26px -12px rgba(255,106,43,.8)}
.btn.p:hover{filter:brightness(1.06)}
.btn.ok{color:var(--ok);border-color:rgba(74,222,128,.35);background:rgba(74,222,128,.07)}
.btn.bad{color:var(--bad);border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.06)}
.btn.ghost{background:transparent}
.btn.blk{width:100%}
.btn.sm{min-height:36px;padding:7px 12px;font-size:13px;border-radius:10px}
.btn.icon{width:44px;padding:0}
.btn.sm.icon{width:36px}

/* Giriş */
.login{min-height:100vh;min-height:100dvh;display:grid;place-items:center;padding:22px}
.lbox{width:min(400px,100%);background:var(--card);border:1px solid var(--line);border-radius:24px;padding:30px;box-shadow:var(--shadow);animation:up .4s ease both}
@keyframes up{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.logo{display:flex;align-items:center;gap:10px;font-weight:900;font-size:18px;letter-spacing:.3px;white-space:nowrap}
.mark{width:34px;height:34px;border-radius:11px;background:linear-gradient(135deg,var(--or),var(--or2));display:grid;place-items:center;font-size:17px;color:#1a0d04;font-weight:900;box-shadow:0 8px 20px -8px rgba(255,106,43,.9)}
.logo span{color:var(--or)}
.lbox h2{font-size:19px;margin:22px 0 4px}
.lbox .sub{color:var(--muted);font-size:13.5px;margin-bottom:20px}
.field{display:flex;flex-direction:column;gap:6px;margin-bottom:12px}
.field label{font-size:12px;color:var(--muted);font-weight:700;letter-spacing:.2px}
.err{color:var(--bad);font-size:13px;margin-top:10px;display:none}
.err.show{display:block}
.back{display:block;text-align:center;margin-top:16px;color:var(--muted);font-size:13px;text-decoration:none}
.back:hover{color:var(--text)}

/* Kabuk */
.top{position:sticky;top:0;z-index:30;background:rgba(7,8,11,.82);backdrop-filter:blur(14px) saturate(140%);-webkit-backdrop-filter:blur(14px) saturate(140%);border-bottom:1px solid var(--line);padding:10px 14px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.top-l{display:flex;align-items:center;gap:14px;min-width:0}
.tabs{display:none;gap:4px;background:var(--bg2);border:1px solid var(--line);padding:4px;border-radius:14px}
.tabs button{padding:8px 13px;border-radius:10px;color:var(--muted);font-weight:700;font-size:13.5px;white-space:nowrap;display:flex;align-items:center;gap:6px}
.tabs button:hover{color:var(--text)}
.tabs button.on{background:var(--card2);color:var(--or);box-shadow:inset 0 0 0 1px var(--line2)}
.badge-n{display:inline-grid;place-items:center;min-width:20px;height:20px;padding:0 6px;border-radius:999px;background:var(--or);color:#1a0d04;font-size:11px;font-weight:900}
.top-r{display:flex;gap:8px;align-items:center}
main{max-width:1240px;margin:0 auto;padding:18px 14px calc(104px + var(--sb))}
.view{display:none}
.view.on{display:block;animation:fade .25s ease both}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.ph{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.ph h1{font-size:22px;letter-spacing:-.01em}
.ph p{color:var(--muted);font-size:13.5px;margin-top:2px}
.ph-r{display:flex;gap:8px;flex-wrap:wrap}

/* Kart ve ızgaralar */
.card{background:linear-gradient(180deg,var(--card),#10131b);border:1px solid var(--line);border-radius:var(--r);padding:16px;display:flex;flex-direction:column;gap:12px;min-width:0;position:relative}
.card.click{cursor:pointer;transition:border-color .15s,transform .15s}
.card.click:hover{border-color:var(--line2)}
.card.click:active{transform:scale(.99)}
.grid{display:grid;gap:12px;grid-template-columns:1fr}
.grid2{display:grid;gap:12px;grid-template-columns:1fr}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;min-width:0}
.row-w{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.kv{display:grid;grid-template-columns:auto minmax(0,1fr);gap:7px 14px;font-size:13.5px}
.kv span{color:var(--muted)}
.kv b{font-weight:600;overflow-wrap:anywhere;text-align:right;justify-self:end}
.acts{display:flex;gap:8px;flex-wrap:wrap}
.acts .btn{flex:1 1 auto}
.sep{height:1px;background:var(--line);margin:2px 0}

/* Rozetler */
.badge{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:11.5px;font-weight:800;white-space:nowrap;letter-spacing:.1px}
.badge::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.9}
.b-ok{background:rgba(74,222,128,.13);color:var(--ok)}
.b-pen{background:rgba(251,191,36,.13);color:var(--warn)}
.b-bad{background:rgba(248,113,113,.13);color:var(--bad)}
.b-can{background:rgba(148,163,184,.16);color:#cbd5e1}
.b-dev{background:rgba(103,232,249,.13);color:var(--cy)}
.b-vi{background:rgba(167,139,250,.14);color:var(--vi)}

/* İstatistikler */
.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.stat{background:linear-gradient(180deg,var(--card),#10131b);border:1px solid var(--line);border-radius:var(--r);padding:15px;min-width:0;position:relative;overflow:hidden}
.stat::after{content:"";position:absolute;right:-30px;top:-30px;width:90px;height:90px;border-radius:50%;background:var(--glow,transparent);opacity:.12;filter:blur(10px)}
.stat .lbl{font-size:12px;color:var(--muted);font-weight:700;letter-spacing:.2px}
.stat .val{font-size:26px;font-weight:900;line-height:1.15;margin-top:6px;letter-spacing:-.02em}
.stat .sub{font-size:12px;color:var(--dim);margin-top:4px}
.hero-card{background:radial-gradient(600px 240px at 100% 0%,rgba(255,106,43,.16),transparent 60%),linear-gradient(180deg,var(--card),#10131b);border:1px solid var(--line);border-radius:var(--r);padding:18px}
.hero-card .val{font-size:30px;font-weight:900;letter-spacing:-.02em}
.chart{display:flex;align-items:flex-end;gap:8px;height:150px;margin-top:14px}
.bar{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:6px;height:100%;min-width:0}
.bar i{display:block;width:100%;max-width:38px;border-radius:9px 9px 4px 4px;background:linear-gradient(180deg,var(--or2),var(--or));min-height:4px;transition:height .6s cubic-bezier(.2,.8,.2,1)}
.bar.ok i{background:linear-gradient(180deg,#86efac,var(--ok))}
.bar em{font-style:normal;font-size:11px;color:var(--muted);font-weight:700}
.bar b{font-size:11px;color:var(--text);font-weight:800}
.legend{display:flex;gap:14px;font-size:12px;color:var(--muted);margin-top:10px;flex-wrap:wrap}
.legend span::before{content:"";display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px;vertical-align:middle;background:var(--or)}
.legend span.g::before{background:var(--ok)}

/* Filtre çipleri */
.toolbar{display:flex;flex-direction:column;gap:10px;margin-bottom:14px}
.toolbar .search{position:relative}
.toolbar .search svg{position:absolute;left:14px;top:50%;transform:translateY(-50%);width:17px;height:17px;color:var(--muted);pointer-events:none}
.toolbar .search input{padding-left:42px}
.toolbar .srow{display:grid;grid-template-columns:1fr;gap:10px}
.chips{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;padding:2px 0}
.chips::-webkit-scrollbar{display:none}
.chip{padding:8px 14px;border-radius:999px;border:1px solid var(--line);color:var(--muted);font-size:13px;font-weight:700;white-space:nowrap;background:var(--bg2);min-height:38px;display:inline-flex;align-items:center;gap:7px}
.chip b{font-size:11.5px;background:rgba(255,255,255,.07);padding:1px 7px;border-radius:999px;color:var(--text)}
.chip.on{color:var(--or);border-color:rgba(255,106,43,.5);background:rgba(255,106,43,.11)}
.chip.on b{background:rgba(255,106,43,.22);color:var(--or)}

/* Üye satırları */
.mk{background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:10px 12px;display:flex;justify-content:space-between;align-items:center;gap:10px}
.mk .mono{font-size:12px}
.empty{grid-column:1/-1;text-align:center;color:var(--muted);padding:44px 16px;border:1px dashed var(--line2);border-radius:var(--r);background:rgba(255,255,255,.012)}
.empty b{display:block;color:var(--text);font-size:15px;margin-bottom:4px}
.skel{border-radius:var(--r);height:132px;background:linear-gradient(90deg,var(--card) 25%,var(--card2) 50%,var(--card) 75%);background-size:200% 100%;animation:sh 1.2s infinite;border:1px solid var(--line)}
@keyframes sh{to{background-position:-200% 0}}

/* Yeni anahtar formu */
.form{max-width:560px;display:flex;flex-direction:column;gap:6px}
.keybox{background:rgba(74,222,128,.07);border:1px solid rgba(74,222,128,.28);border-radius:14px;padding:14px;margin-top:8px;display:flex;flex-direction:column;gap:8px}
.keybox code{font:800 16px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--ok);word-break:break-all}
.seg{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.seg button{padding:12px 6px;border-radius:12px;border:1px solid var(--line2);background:var(--bg2);font-weight:800;font-size:13px;color:var(--muted);min-height:52px;line-height:1.2}
.seg button small{display:block;font-size:11px;font-weight:600;color:var(--dim);margin-top:2px}
.seg button[aria-pressed="true"]{border-color:var(--or);color:var(--or);background:rgba(255,106,43,.1)}

/* Ayarlar */
.set{display:grid;gap:12px;grid-template-columns:1fr}
.setrow{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--line);flex-wrap:wrap}
.setrow:last-child{border-bottom:0}
.setrow .t b{display:block;font-size:14.5px}
.setrow .t span{color:var(--muted);font-size:12.5px}
.sess{display:grid;gap:8px}
.sess .mk{align-items:flex-start;flex-direction:column}

/* Alt menü (mobil) */
.bnav{position:fixed;left:0;right:0;bottom:0;z-index:40;background:rgba(9,11,16,.92);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border-top:1px solid var(--line);display:grid;grid-template-columns:repeat(5,1fr);padding:6px 6px calc(6px + var(--sb))}
.bnav button{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:6px 0;color:var(--muted);font-size:10.5px;font-weight:800;border-radius:14px;min-height:56px;letter-spacing:.2px}
.bnav button i{font-style:normal;font-size:19px;line-height:1}
.bnav button.on{color:var(--or)}
.bnav button.on::before{content:"";position:absolute;top:0;width:26px;height:3px;border-radius:0 0 4px 4px;background:var(--or)}
.bnav .dot{position:absolute;top:4px;right:calc(50% - 22px);min-width:17px;height:17px;padding:0 5px;border-radius:999px;background:var(--or);color:#1a0d04;font-size:10px;font-weight:900;display:grid;place-items:center}

/* Alt sayfa */
.ov{position:fixed;inset:0;background:rgba(2,3,6,.62);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);z-index:50;opacity:0;pointer-events:none;transition:opacity .2s}
.ov.open{opacity:1;pointer-events:auto}
.sheet{position:fixed;left:0;right:0;bottom:0;z-index:51;background:var(--card);border-top:1px solid var(--line2);border-radius:24px 24px 0 0;padding:10px 18px calc(18px + var(--sb));transform:translateY(105%);transition:transform .28s cubic-bezier(.2,.8,.2,1);max-height:90vh;overflow:auto;overscroll-behavior:contain;box-shadow:0 -20px 60px rgba(0,0,0,.6)}
.sheet.open{transform:none}
.grab{width:46px;height:5px;border-radius:9px;background:var(--line2);margin:2px auto 14px}
.sheet h3{font-size:17px;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;gap:10px}
.sheet .acts{margin-top:16px}
.sheet .acts .btn{min-height:48px}

/* Bildirim */
#toast{position:fixed;left:50%;bottom:calc(104px + var(--sb));transform:translate(-50%,180%);background:#13201a;border:1px solid rgba(74,222,128,.4);color:var(--ok);padding:12px 18px;border-radius:14px;font-weight:700;font-size:14px;transition:transform .3s cubic-bezier(.2,.8,.2,1);z-index:70;max-width:92vw;text-align:center;box-shadow:var(--shadow)}
#toast.show{transform:translate(-50%,0)}
#toast.bad{background:#211416;border-color:rgba(248,113,113,.45);color:var(--bad)}

/* Masaüstü */
@media (min-width:720px){
  .stats{grid-template-columns:repeat(5,minmax(0,1fr))}
  .grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .grid2{grid-template-columns:repeat(2,minmax(0,1fr))}
  .toolbar{flex-direction:row;align-items:center}
  .toolbar .search{flex:1;max-width:420px}
  .toolbar .chips{flex:1}
  .tabs{display:inline-flex}
  .bnav{display:none}
  main{padding-bottom:40px}
  #toast{bottom:28px}
  .sheet{left:50%;right:auto;width:min(560px,94%);transform:translate(-50%,108%);border-radius:24px;bottom:22px;max-height:86vh}
  .sheet.open{transform:translate(-50%,0)}
  .set{grid-template-columns:1fr 1fr}
}
@media (min-width:1080px){
  .grid{grid-template-columns:repeat(3,minmax(0,1fr))}
  .grid2{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:420px){
  .top-l .logo .txt{display:none}
  .stat .val{font-size:22px}
  .seg{grid-template-columns:repeat(2,1fr)}
  .ph h1{font-size:20px}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;transition-duration:.001ms!important}}
</style>
</head>
<body>

<!-- Giriş -->
<section class="login" id="loginView">
  <div class="lbox">
    <div class="logo"><span class="mark">R</span><span class="txt">REX<span>·</span>Yönetim</span></div>
    <h2>Yönetici girişi</h2>
    <p class="sub">Devam etmek için yönetici şifrenizi girin.</p>
    <div class="field">
      <label for="pass">Şifre</label>
      <input id="pass" type="password" autocomplete="current-password" maxlength="100" placeholder="••••••">
    </div>
    <button class="btn p blk" id="loginBtn">Giriş yap</button>
    <div class="err" id="loginErr" role="alert"></div>
    <a class="back" href="https://rexstudyo.site">← Siteye dön</a>
  </div>
</section>

<!-- Uygulama -->
<div id="app" class="hide">
  <header class="top">
    <div class="top-l">
      <div class="logo"><span class="mark">R</span><span class="txt">REX<span>·</span>Yönetim</span></div>
      <nav class="tabs" aria-label="Bölümler">
        <button data-v="dash"><i>📊</i>Özet</button>
        <button data-v="ord"><i>🧾</i>Siparişler <span class="badge-n hide" id="tabOrdN">0</span></button>
        <button data-v="mem"><i>👥</i>Üyeler</button>
        <button data-v="key"><i>🔑</i>Anahtarlar</button>
        <button data-v="new"><i>＋</i>Yeni anahtar</button>
        <button data-v="set"><i>⚙️</i>Ayarlar</button>
      </nav>
    </div>
    <div class="top-r">
      <button class="btn sm icon" id="refresh" aria-label="Yenile" title="Yenile">↻</button>
      <button class="btn sm bad" id="logout">Çıkış</button>
    </div>
  </header>

  <main>
    <!-- ÖZET -->
    <section class="view on" id="v-dash">
      <div class="ph"><div><h1>Genel bakış</h1><p id="dashDate">—</p></div></div>
      <div class="grid2" style="grid-template-columns:1fr">
        <div class="hero-card">
          <div class="row-w">
            <div><div class="muted small" style="font-weight:700">Bu ayki tahmini gelir</div>
              <div class="val" id="revenue">—</div>
              <div class="sub dim small" id="revenueSub">Onaylı siparişlerden hesaplanır</div>
            </div>
            <button class="btn sm" data-v="ord">Siparişlere git →</button>
          </div>
          <div class="chart" id="chart" aria-label="Son 7 gün sipariş grafiği"></div>
          <div class="legend"><span>Sipariş</span><span class="g">Onaylanan</span></div>
        </div>
      </div>
      <div class="stats" id="stats" style="margin-top:12px"></div>
      <div class="sec-h" style="display:flex;justify-content:space-between;align-items:center;margin:20px 0 10px;gap:10px;flex-wrap:wrap">
        <h2 style="font-size:16px">Bekleyen siparişler</h2>
        <button class="btn sm ghost" data-v="ord">Tümünü gör</button>
      </div>
      <div class="grid" id="dashOrders"></div>
      <div class="sec-h" style="display:flex;justify-content:space-between;align-items:center;margin:22px 0 10px">
        <h2 style="font-size:16px">Son anahtarlar</h2>
        <button class="btn sm ghost" data-v="key">Tümünü gör</button>
      </div>
      <div class="grid" id="dashKeys"></div>
    </section>

    <!-- SİPARİŞLER -->
    <section class="view" id="v-ord">
      <div class="ph"><div><h1>Siparişler</h1><p>Ödemesi gelen siparişleri onaylayın, reddedin veya anahtarını kopyalayın.</p></div></div>
      <div class="toolbar">
        <label class="search"><span class="sr">Sipariş ara</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input id="qOrd" type="search" placeholder="Sipariş no, iletişim veya paket">
        </label>
        <div class="chips" id="chipsOrd"></div>
      </div>
      <div class="grid" id="ordList"></div>
    </section>

    <!-- ÜYELER -->
    <section class="view" id="v-mem">
      <div class="ph"><div><h1>Üyeler</h1><p>Anahtarlar iletişim bilgisine göre gruplanır.</p></div></div>
      <div class="toolbar">
        <label class="search"><span class="sr">Üye ara</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input id="qMem" type="search" placeholder="Telefon veya e-posta ile ara">
        </label>
      </div>
      <div class="grid" id="memList"></div>
    </section>

    <!-- ANAHTARLAR -->
    <section class="view" id="v-key">
      <div class="ph"><div><h1>Lisans anahtarları</h1><p>Karta dokunarak anahtarı yönetin.</p></div></div>
      <div class="toolbar">
        <label class="search"><span class="sr">Anahtar ara</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input id="qKey" type="search" placeholder="Anahtar, sahip veya paket">
        </label>
        <div class="chips" id="chipsKey"></div>
      </div>
      <div class="ph" style="margin:-4px 0 12px"><div class="row" style="gap:8px"><span class="muted small">Sırala:</span>
        <select id="sortKey" style="width:auto;min-height:38px;padding:7px 34px 7px 12px;border-radius:999px;font-size:13px">
          <option value="new">En yeni</option><option value="exp">Bitişe yakın</option><option value="owner">Sahibe göre</option>
        </select></div></div>
      <div class="grid" id="keyList"></div>
    </section>

    <!-- YENİ ANAHTAR -->
    <section class="view" id="v-new">
      <div class="ph"><div><h1>Yeni anahtar üret</h1><p>Siparişe bağlı olmadan doğrudan lisans oluşturun.</p></div></div>
      <div class="card form" style="max-width:600px">
        <label class="field" style="margin:0"><span class="muted small" style="font-weight:700">Paket</span></label>
        <div class="seg" id="nSeg" role="group" aria-label="Paket seçimi"></div>
        <div class="field" style="margin-top:10px"><label for="nOwner">Sahip / iletişim</label><input id="nOwner" maxlength="120" placeholder="05xx xxx xx xx veya e-posta" autocomplete="off"></div>
        <div class="field"><label for="nDays">Süre (gün) — boş bırakırsanız paket süresi kullanılır</label><input id="nDays" type="number" inputmode="numeric" min="1" max="3650" placeholder="Örn. 14"></div>
        <button class="btn p blk" id="nBtn" style="margin-top:6px;min-height:50px">Anahtar üret</button>
        <div class="keybox hide" id="nOut">
          <span class="muted small" style="font-weight:700">Yeni lisans anahtarı</span>
          <code id="nKey"></code>
          <button class="btn sm blk" id="nCopy">📋 Kopyala</button>
        </div>
      </div>
    </section>

    <!-- AYARLAR -->
    <section class="view" id="v-set">
      <div class="ph"><div><h1>Ayarlar</h1><p>Dışa aktarma, oturumlar ve sistem bilgisi.</p></div></div>
      <div class="set">
        <div class="card">
          <h2 style="font-size:15px">Dışa aktarma</h2>
          <div class="setrow"><div class="t"><b>Siparişleri indir</b><span>CSV dosyası (Excel ile açılır)</span></div><button class="btn sm" id="expOrd">CSV indir</button></div>
          <div class="setrow"><div class="t"><b>Anahtarları indir</b><span>Tüm lisanslar ve durumları</span></div><button class="btn sm" id="expKey">CSV indir</button></div>
        </div>
        <div class="card">
          <h2 style="font-size:15px">Aktif oturumlar</h2>
          <div class="sess" id="sessList"></div>
        </div>
        <div class="card">
          <h2 style="font-size:15px">Sistem</h2>
          <div class="setrow"><div class="t"><b>Toplam kayıt</b><span>Anahtar ve sipariş sayısı</span></div><span class="mono" id="sysCount">—</span></div>
          <div class="setrow"><div class="t"><b>Son yenileme</b><span>Veriler 15 saniyede bir güncellenir</span></div><span class="mono" id="sysTime">—</span></div>
          <div class="setrow"><div class="t"><b>Oturumu kapat</b><span>Bu cihazdan çıkış yapın</span></div><button class="btn sm bad" id="logout2">Çıkış</button></div>
        </div>
      </div>
    </section>
  </main>

  <nav class="bnav" id="bnav" aria-label="Alt menü">
    <button data-v="dash" class="on"><i>📊</i>Özet</button>
    <button data-v="ord"><i>🧾</i>Sipariş<span class="dot hide" id="bnOrdN">0</span></button>
    <button data-v="mem"><i>👥</i>Üye</button>
    <button data-v="key"><i>🔑</i>Anahtar</button>
    <button data-v="set"><i>⚙️</i>Ayar</button>
  </nav>
</div>

<div class="ov" id="ov"></div>
<div class="sheet" id="sheet" role="dialog" aria-modal="true" aria-labelledby="shTitle">
  <div class="grab"></div>
  <div id="shBody"></div>
</div>
<div id="toast" role="status" aria-live="polite"></div>

<script>
/* ===== Yardımcılar ===== */
const $ = id => document.getElementById(id);
const ESC = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"};
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ESC[c]);
const PLAN = {trial:"Deneme", weekly:"1 Haftalık", monthly:"1 Aylık", yearly:"Yıllık"};
const PRICE = {trial:100, weekly:250, monthly:600, yearly:0};
const ORD = {pending:["b-pen","Bekliyor"], approved:["b-ok","Onaylandı"], rejected:["b-bad","Reddedildi"]};
const DAY = 86400000;
const fmt = d => d ? new Date(d).toLocaleString("tr-TR", {day:"2-digit", month:"2-digit", year:"numeric", hour:"2-digit", minute:"2-digit"}) : "—";
const fmtD = d => d ? new Date(d).toLocaleDateString("tr-TR", {day:"2-digit", month:"short"}) : "—";
const money = n => n.toLocaleString("tr-TR") + " ₺";
const ts = d => (d ? new Date(d).getTime() : 0);

let D = {keys:[], orders:[], sessions:[]};
let V = "dash", FO = "pending", FK = "ok", SORT = "new", TIMER = null, SHEET = null, LOADED = false, LAST = null, NPLAN = "monthly";

/* ===== Bildirim ===== */
let toastT;
function toast(msg, bad) {
  const t = $("toast");
  t.textContent = msg; t.className = "show" + (bad ? " bad" : "");
  clearTimeout(toastT); toastT = setTimeout(() => t.className = "", 2600);
}
function copy(text) {
  const done = () => toast("Kopyalandı");
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done).catch(() => legacy(text, done));
  } else legacy(text, done);
}
function legacy(text, done) {
  const ta = document.createElement("textarea");
  ta.value = text; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;opacity:0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) { toast("Kopyalanamadı", true); }
  document.body.removeChild(ta);
}

/* ===== API ===== */
async function api(path, body) {
  const o = {credentials: "same-origin", headers: {"Accept": "application/json"}};
  if (body !== undefined) { o.method = "POST"; o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
  const r = await fetch(path, o);
  if (r.status === 401) throw new Error("AUTH");
  if (!r.headers.get("content-type") || r.headers.get("content-type").indexOf("json") < 0) throw new Error("BAD");
  return r.json();
}
function netErr(e) {
  if (e.message === "AUTH") return;
  toast(e.message === "BAD" ? "Sunucu beklenmeyen yanıt verdi" : "Sunucuya ulaşılamadı", true);
}

/* ===== Durum ===== */
function keyStatus(k) {
  if (k.active === false) return "cancel";
  if (k.expires && new Date(k.expires) <= new Date()) return "exp";
  return "ok";
}
function left(k) {
  if (!k.expires) return "Süresiz";
  const d = Math.ceil((new Date(k.expires) - Date.now()) / DAY);
  return d > 0 ? d + " gün" : "Süresi doldu";
}
const byNew = (a, b) => ts(b.created) - ts(a.created);

/* ===== Oturum ===== */
function showLogin() {
  $("app").classList.add("hide"); $("loginView").classList.remove("hide");
  clearInterval(TIMER); TIMER = null; LOADED = false;
}
function showApp() {
  $("loginView").classList.add("hide"); $("app").classList.remove("hide");
  if (!TIMER) TIMER = setInterval(() => { if (!document.hidden && !SHEET) loadAll(true); }, 15000);
}
async function loadAll(silent) {
  if (!silent && !LOADED) {
    $("ordList").innerHTML = skel(2); $("keyList").innerHTML = skel(2); $("memList").innerHTML = skel(2);
  }
  try {
    const [k, o] = await Promise.all([api("/api/admin/keys"), api("/api/admin/orders")]);
    D = {keys: k.keys || [], sessions: k.active_sessions || [], orders: o.orders || []};
    LOADED = true; LAST = new Date();
    showApp(); render();
  } catch (e) {
    if (e.message === "AUTH") showLogin(); else netErr(e);
  }
}
function skel(n) { return Array.from({length: n}, () => '<div class="skel"></div>').join(""); }
async function login() {
  const err = $("loginErr"); err.classList.remove("show");
  const btn = $("loginBtn"); btn.disabled = true; btn.textContent = "Kontrol ediliyor…";
  try {
    const j = await api("/api/admin/login", {pass: $("pass").value});
    if (j.ok) { $("pass").value = ""; loadAll(); }
    else { err.textContent = j.err || "Giriş başarısız"; err.classList.add("show"); }
  } catch (e) { err.textContent = "Sunucuya ulaşılamadı"; err.classList.add("show"); }
  btn.disabled = false; btn.textContent = "Giriş yap";
}
async function logout() {
  try { await fetch("/api/admin/logout", {method: "POST", credentials: "same-origin"}); } catch (e) {}
  location.reload();
}

/* ===== Gezinme ===== */
function go(v) {
  if (!v) return;
  V = v;
  document.querySelectorAll(".view").forEach(s => s.classList.toggle("on", s.id === "v-" + v));
  document.querySelectorAll("[data-v]").forEach(b => b.classList.toggle("on", b.dataset.v === v));
  render();
  window.scrollTo({top: 0, behavior: "smooth"});
}

/* ===== Kartlar ===== */
function empty(title, text) { return `<div class="empty"><b>${title}</b>${text || ""}</div>`; }

function orderCard(o) {
  const st = ORD[o.status] || ["b-can", esc(o.status)];
  const id = esc(o.id);
  const isPending = o.status === "pending";
  return `<article class="card">
    <div class="row"><span class="mono">#${id}</span><span class="badge ${st[0]}">${st[1]}</span></div>
    <div class="kv">
      <span>Paket</span><b>${esc(o.plan_name)}</b>
      <span>İletişim</span><b>${esc(o.contact) || "—"}</b>
      <span>Tarih</span><b>${fmt(o.created)}</b>
    </div>
    ${o.key ? `<div class="row-w" style="background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:10px 12px"><span class="mono small">${esc(o.key)}</span><button class="btn sm" data-copy="${esc(o.key)}">Kopyala</button></div>` : ""}
    ${isPending ? `<div class="acts">
      <button class="btn sm ok" data-oact="ok" data-id="${id}">✓ Onayla</button>
      <button class="btn sm bad" data-oact="no" data-id="${id}">✕ Reddet</button></div>` : ""}
  </article>`;
}

function keyCard(k) {
  const s = keyStatus(k);
  const st = {ok:["b-ok","Aktif"], exp:["b-bad","Süresi doldu"], cancel:["b-can","İptal"]}[s];
  return `<article class="card click" data-sheet="${esc(k.license_key)}" tabindex="0" role="button" aria-label="Anahtarı yönet">
    <div class="row"><span class="mono small">${esc(k.license_key)}</span><span class="badge ${st[0]}">${st[1]}</span></div>
    <div class="kv">
      <span>Paket</span><b>${esc(PLAN[k.plan] || k.plan || "—")}</b>
      <span>Sahip</span><b>${esc(k.owner) || "—"}</b>
      <span>Kalan</span><b>${left(k)}</b>
      <span>Cihaz</span><b>${k.device ? '<span class="badge b-dev">Kilitli</span>' : "Boş"}</b>
    </div>
  </article>`;
}

function memberCard(owner, keys) {
  const active = keys.filter(k => keyStatus(k) === "ok").length;
  const last = keys.map(k => k.expires).filter(Boolean).sort().pop();
  return `<article class="card">
    <div class="row"><b style="font-size:15.5px;overflow-wrap:anywhere;min-width:0">${esc(owner) || "Belirtilmemiş"}</b>
      <span class="badge ${active ? "b-ok" : "b-can"}">${active} aktif</span></div>
    <div class="kv"><span>Toplam anahtar</span><b>${keys.length}</b><span>Son bitiş</span><b>${last ? fmt(last) : "—"}</b></div>
    <div class="sep"></div>
    ${keys.slice(0, 6).map(k => `<div class="mk"><span class="mono small">${esc(k.license_key)}</span><button class="btn sm" data-sheet="${esc(k.license_key)}">Yönet</button></div>`).join("")}
    ${keys.length > 6 ? `<span class="muted small" style="text-align:center">+${keys.length - 6} anahtar daha</span>` : ""}
  </article>`;
}

function chips(id, items, cur, attr) {
  $(id).innerHTML = items.map(([v, l, n]) =>
    `<button class="chip ${cur === v ? "on" : ""}" data-${attr}="${v}" aria-pressed="${cur === v}">${l}${n !== undefined ? ` <b>${n}</b>` : ""}</button>`).join("");
}

/* ===== Görünümler ===== */
function renderStats() {
  const c = {ok:0, exp:0, cancel:0};
  D.keys.forEach(k => c[keyStatus(k)]++);
  const pend = D.orders.filter(o => o.status === "pending").length;
  const appr = D.orders.filter(o => o.status === "approved").length;
  const cards = [
    ["Bekleyen", pend, "var(--warn)", "sipariş", "--warn"],
    ["Aktif lisans", c.ok, "var(--ok)", "anahtar", "--ok"],
    ["Süresi dolan", c.exp, "var(--bad)", "anahtar", "--bad"],
    ["Onaylanan", appr, "var(--text)", "sipariş", "--cy"],
    ["Aktif oturum", D.sessions.length, "var(--cy)", "cihaz", "--cy"]
  ];
  $("stats").innerHTML = cards.map(([l, v, col, sub, glow]) =>
    `<div class="stat" style="--glow:var(${glow})"><div class="lbl">${l}</div><div class="val" style="color:${col}">${v}</div><div class="sub">${sub}</div></div>`).join("");
  $("tabOrdN").textContent = pend; $("tabOrdN").classList.toggle("hide", !pend);
  $("bnOrdN").textContent = pend; $("bnOrdN").classList.toggle("hide", !pend);
}

function renderDash() {
  const now = new Date();
  $("dashDate").textContent = now.toLocaleDateString("tr-TR", {weekday:"long", day:"numeric", month:"long", year:"numeric"});
  // bu ay onaylı gelir (tahmini)
  let rev = 0, cnt = 0;
  D.orders.forEach(o => {
    const d = new Date(o.approved_at || o.created);
    if (o.status === "approved" && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()) {
      rev += PRICE[o.product] || 0; cnt++;
    }
  });
  $("revenue").textContent = money(rev);
  $("revenueSub").textContent = cnt + " onaylı sipariş · sitedeki fiyatlara göre tahmini";
  // son 7 gün grafiği
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - i);
    days.push({d, all: 0, ok: 0, label: d.toLocaleDateString("tr-TR", {weekday:"short"})});
  }
  D.orders.forEach(o => {
    const t = new Date(o.created); t.setHours(0, 0, 0, 0);
    const b = days.find(x => x.d.getTime() === t.getTime());
    if (b) { b.all++; if (o.status === "approved") b.ok++; }
  });
  const max = Math.max(1, ...days.map(x => x.all));
  $("chart").innerHTML = days.map(x => `
    <div class="bar ${x.ok ? "ok" : ""}" title="${x.label}: ${x.all} sipariş, ${x.ok} onaylı">
      <b>${x.all}</b>
      <i style="height:${Math.max(4, Math.round(x.all / max * 100))}%"></i>
      <em>${x.label}</em>
    </div>`).join("");

  const pend = D.orders.filter(o => o.status === "pending").sort(byNew).slice(0, 6);
  $("dashOrders").innerHTML = pend.length ? pend.map(orderCard).join("")
    : empty("Bekleyen sipariş yok 🎉", "Yeni siparişler geldiğinde burada görünür.");
  const recent = D.keys.slice().sort(byNew).slice(0, 4);
  $("dashKeys").innerHTML = recent.length ? recent.map(keyCard).join("")
    : empty("Henüz anahtar yok", "Sipariş onaylayın veya yeni anahtar üretin.");
}

function renderOrders() {
  const q = $("qOrd").value.trim().toLowerCase();
  const count = s => D.orders.filter(o => s === "all" || o.status === s).length;
  chips("chipsOrd", [["pending","Bekleyen",count("pending")], ["approved","Onaylı",count("approved")], ["rejected","Reddedilen",count("rejected")], ["all","Tümü",count("all")]], FO, "fo");
  const list = D.orders
    .filter(o => (FO === "all" || o.status === FO) &&
      (!q || [o.id, o.contact, o.plan_name, o.key].join(" ").toLowerCase().includes(q)))
    .sort(byNew);
  $("ordList").innerHTML = list.length ? list.map(orderCard).join("")
    : empty("Sipariş bulunamadı", q ? "Aramayı değiştirmeyi deneyin." : "Bu filtrede sipariş yok.");
}

function renderMembers() {
  const q = $("qMem").value.trim().toLowerCase();
  const groups = {};
  D.keys.forEach(k => { const o = k.owner || ""; (groups[o] = groups[o] || []).push(k); });
  const names = Object.keys(groups)
    .filter(n => !q || n.toLowerCase().includes(q))
    .sort((a, b) => Math.max(...groups[b].map(k => ts(k.created))) - Math.max(...groups[a].map(k => ts(k.created))));
  $("memList").innerHTML = names.length ? names.map(n => memberCard(n, groups[n].slice().sort(byNew))).join("")
    : empty("Üye bulunamadı", q ? "Aramayı değiştirin." : "Anahtar oluşturulduğunda üyeler burada görünür.");
}

function renderKeys() {
  const q = $("qKey").value.trim().toLowerCase();
  const count = s => D.keys.filter(k => s === "all" || keyStatus(k) === s).length;
  chips("chipsKey", [["ok","Aktif",count("ok")], ["exp","Süresi dolan",count("exp")], ["cancel","İptal",count("cancel")], ["all","Tümü",count("all")]], FK, "fk");
  let list = D.keys.filter(k => (FK === "all" || keyStatus(k) === FK) &&
    (!q || [k.license_key, k.owner, k.plan].join(" ").toLowerCase().includes(q)));
  if (SORT === "exp") list.sort((a, b) => (a.expires ? ts(a.expires) : Infinity) - (b.expires ? ts(b.expires) : Infinity));
  else if (SORT === "owner") list.sort((a, b) => String(a.owner || "").localeCompare(String(b.owner || ""), "tr"));
  else list.sort(byNew);
  $("keyList").innerHTML = list.length ? list.map(keyCard).join("")
    : empty("Anahtar bulunamadı", q ? "Aramayı değiştirin." : "Bu filtrede anahtar yok.");
}

function renderNew() {
  $("nSeg").innerHTML = Object.keys(PLAN).map(p => {
    const d = {trial:"7 gün", weekly:"7 gün", monthly:"30 gün", yearly:"365 gün"}[p];
    return `<button type="button" aria-pressed="${p === NPLAN}" data-nplan="${p}">${PLAN[p]}<small>${d}</small></button>`;
  }).join("");
}

function renderSettings() {
  $("sysCount").textContent = D.keys.length + " anahtar · " + D.orders.length + " sipariş";
  $("sysTime").textContent = LAST ? LAST.toLocaleTimeString("tr-TR") : "—";
  $("sessList").innerHTML = D.sessions.length
    ? D.sessions.map(s => `<div class="mk"><div><span class="mono small">${esc(s.key)}</span></div>
        <div class="muted small">${esc(PLAN[s.plan] || s.plan || "—")} · oturum: ${fmt(s.created)}</div></div>`).join("")
    : '<span class="muted small">Şu anda aktif oturum yok.</span>';
}

function render() {
  renderStats();
  if (V === "dash") renderDash();
  else if (V === "ord") renderOrders();
  else if (V === "mem") renderMembers();
  else if (V === "key") renderKeys();
  else if (V === "new") renderNew();
  else if (V === "set") renderSettings();
}

/* ===== Alt sayfa ===== */
function openSheet(key) {
  const k = D.keys.find(x => x.license_key === key);
  if (!k) return;
  SHEET = key;
  const s = keyStatus(k);
  const stText = {ok:"Aktif", exp:"Süresi doldu", cancel:"İptal"}[s];
  const stCls = {ok:"b-ok", exp:"b-bad", cancel:"b-can"}[s];
  $("shBody").innerHTML = `
    <h3 id="shTitle">Anahtar <span class="badge ${stCls}">${stText}</span></h3>
    <div class="mono" style="background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:14px">${esc(k.license_key)}</div>
    <div class="kv">
      <span>Paket</span><b>${esc(PLAN[k.plan] || k.plan || "—")}</b>
      <span>Sahip</span><b>${esc(k.owner) || "—"}</b>
      <span>Bitiş</span><b>${k.expires ? fmt(k.expires) : "Süresiz"}</b>
      <span>Kalan</span><b>${left(k)}</b>
      <span>Cihaz</span><b>${k.device ? "Kilitli" : "Boş"}</b>
      <span>Son giriş</span><b>${fmt(k.last_login)}</b>
      <span>Son IP</span><b>${esc(k.last_ip) || "—"}</b>
      <span>Giriş sayısı</span><b>${k.login_count || 0}</b>
    </div>
    <div class="acts">
      <button class="btn blk" data-sa="copy">📋 Anahtarı kopyala</button>
      <button class="btn" data-sa="reset">🔓 Cihazı sıfırla</button>
      ${k.active === false
        ? '<button class="btn ok" data-sa="activate">✓ Aktif et</button>'
        : '<button class="btn bad" data-sa="cancel">✕ İptal et</button>'}
      <button class="btn" data-sa="extend" data-days="7">+7 gün</button>
      <button class="btn" data-sa="extend" data-days="30">+30 gün</button>
      <button class="btn bad blk" data-sa="delete">🗑 Anahtarı sil</button>
    </div>`;
  $("ov").classList.add("open"); $("sheet").classList.add("open");
}
function closeSheet() {
  $("ov").classList.remove("open"); $("sheet").classList.remove("open"); SHEET = null;
}
async function sheetAct(a, days) {
  const key = SHEET;
  if (!key) return;
  if (a === "copy") return copy(key);
  const warn = {
    reset: "Cihaz kilidi sıfırlansın mı? Aktif oturumlar kapanır.",
    cancel: "Anahtar iptal edilsin mi? Kullanıcı giriş yapamaz.",
    delete: "Anahtar KALICI olarak silinsin mi? Bu işlem geri alınamaz."
  };
  if (warn[a] && !confirm(warn[a])) return;
  closeSheet();
  await keyAction(a, key, days);
}
async function keyAction(action, key, days) {
  try {
    const j = await api("/api/admin/action", {action, key, days: Number(days) || 0});
    if (j.ok) toast(j.msg); else toast(j.err || "İşlem başarısız", true);
    loadAll(true);
  } catch (e) { netErr(e); }
}

/* ===== Sipariş işlemi ===== */
async function orderAct(id, action) {
  const text = action === "ok" ? "onaylansın ve anahtar üretilsin" : "reddedilsin";
  if (!confirm(`#${id} siparişi ${text} mi?`)) return;
  try {
    const j = await api("/api/admin/order", {id, action});
    if (j.ok) toast("Sipariş işlendi" + (j.key ? ", anahtar hazır" : ""));
    else toast(j.err || "İşlem başarısız", true);
    loadAll(true);
  } catch (e) { netErr(e); }
}

/* ===== Dışa aktarma (CSV) ===== */
function download(name, rows) {
  const cell = v => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"';
  const csv = "\uFEFF" + rows.map(r => r.map(cell).join(";")).join("\r\n");
  const blob = new Blob([csv], {type: "text/csv;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name + "_" + new Date().toISOString().slice(0, 10) + ".csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Dosya indirildi");
}
function exportOrders() {
  download("siparisler", [["No","Tarih","Paket","İletişim","Durum","Anahtar"]].concat(
    D.orders.slice().sort(byNew).map(o => [o.id, fmt(o.created), o.plan_name, o.contact, (ORD[o.status] || [0, o.status])[1], o.key || ""])));
}
function exportKeys() {
  download("anahtarlar", [["Anahtar","Paket","Sahip","Durum","Bitiş","Oluşturulma","Son giriş"]].concat(
    D.keys.slice().sort(byNew).map(k => [k.license_key, PLAN[k.plan] || k.plan, k.owner, {ok:"Aktif",exp:"Süresi doldu",cancel:"İptal"}[keyStatus(k)], k.expires ? fmt(k.expires) : "Süresiz", fmt(k.created), fmt(k.last_login)])));
}

/* ===== Olaylar ===== */
document.addEventListener("click", e => {
  const nplan = e.target.closest("[data-nplan]");
  if (nplan) { NPLAN = nplan.dataset.nplan; return renderNew(); }
  const nav = e.target.closest("[data-v]");
  if (nav) return go(nav.dataset.v);
  const sa = e.target.closest("[data-sa]");
  if (sa) return sheetAct(sa.dataset.sa, sa.dataset.days);
  const cp = e.target.closest("[data-copy]");
  if (cp) return copy(cp.dataset.copy);
  const oa = e.target.closest("[data-oact]");
  if (oa) return orderAct(oa.dataset.id, oa.dataset.oact);
  const fo = e.target.closest("[data-fo]");
  if (fo) { FO = fo.dataset.fo; return renderOrders(); }
  const fk = e.target.closest("[data-fk]");
  if (fk) { FK = fk.dataset.fk; return renderKeys(); }
  const sh = e.target.closest("[data-sheet]");
  if (sh) return openSheet(sh.dataset.sheet);
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeSheet();
  if (e.key === "Enter" && e.target.matches && e.target.matches("[data-sheet]")) openSheet(e.target.dataset.sheet);
});
$("ov").onclick = closeSheet;
["qOrd", "qMem", "qKey"].forEach(id => $(id).addEventListener("input", render));
$("sortKey").onchange = e => { SORT = e.target.value; renderKeys(); };
$("loginBtn").onclick = login;
$("pass").addEventListener("keydown", e => { if (e.key === "Enter") login(); });
$("refresh").onclick = () => loadAll();
$("logout").onclick = logout;
$("logout2").onclick = logout;
$("expOrd").onclick = exportOrders;
$("expKey").onclick = exportKeys;
$("nBtn").onclick = async () => {
  const b = $("nBtn"); b.disabled = true;
  try {
    const j = await api("/api/admin/newkey", {product: NPLAN, owner: $("nOwner").value.trim(), days: $("nDays").value || 0});
    if (j.ok) {
      $("nKey").textContent = j.key; $("nOut").classList.remove("hide");
      toast("Anahtar üretildi"); loadAll(true);
    } else toast(j.err || "Anahtar üretilemedi", true);
  } catch (e) { netErr(e); }
  b.disabled = false;
};
$("nCopy").onclick = () => copy($("nKey").textContent);

loadAll();
</script>
</body>
</html>'''

# ============================================================
# MEVCUT GLOBALS
# ============================================================
clients, clients_lock = [], threading.Lock()
state_lock = threading.RLock()
run_stop = None
worker = None
active_client = None
active_loop = None
ACTIVE_STREAMER = ""
STREAMER_AVATAR = ""
STATUS = {"state": "disconnected", "text": "Yayıncı bekleniyor", "username": "", "since": None}
STATS = {"join": 0, "comment": 0, "follow": 0, "gift": 0, "dia": 0, "like": 0, "share": 0}

def event_payload(payload):
    return ("data: " + json.dumps(payload, ensure_ascii=False, default=str) + "\n\n").encode("utf-8")

def broadcast(payload):
    data = event_payload(payload)
    with clients_lock:
        for q in list(clients):
            try:
                q.put_nowait(data)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                except (queue.Empty, queue.Full):
                    pass

def status(state, text, username=None):
    global STATUS
    with state_lock:
        if username is None:
            username = STATUS.get("username", "")
        STATUS = {"state": state, "text": text, "username": username, "since": time.time() if state == "connected" else STATUS.get("since")}
        snapshot = dict(STATUS)
    print(f"[durum] {state}: {text}")
    broadcast({"type": "status", **snapshot})

def stats_snapshot():
    with state_lock:
        return dict(STATS)

def field(obj, *names, default=None):
    for name in names:
        try:
            value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name)
            if value is not None:
                return value
        except Exception:
            pass
    return default

AVATAR_CACHE = {}

def _urls_of(obj):
    if obj is None:
        return []
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, (list, tuple)):
        out = []
        for o in obj:
            out += _urls_of(o)
        return out
    out = []
    for name in ("m_urls", "url_list", "urls", "urlList", "url"):
        val = field(obj, name, default=None)
        if val:
            out += _urls_of(val)
    return out

def _av_size(url):
    import re as _re
    m = _re.findall(r":(\d{2,4}):(\d{2,4})", url) or _re.findall(r"(\d{2,4})x(\d{2,4})", url)
    return max((int(a) for a, _ in m), default=0)

def pick_avatar(user):
    if not user:
        return ""
    best, best_key = "", (-1, -1)
    names = ("avatar_larger", "avatarLarger", "avatar_large", "avatarLarge", "avatar_jpg", "avatarJpg", "avatar_medium", "avatarMedium", "avatar_thumb", "avatarThumb", "avatar", "profile_picture", "profilePicture")
    for rank, name in enumerate(names):
        for u in _urls_of(field(user, name, default=None)):
            if not (isinstance(u, str) and u.startswith(("http://", "https://"))) or ".heic" in u.lower():
                continue
            key = (_av_size(u), -rank)
            if key > best_key:
                best, best_key = u, key
    return best

def pick_gift_icon(gift):
    if not gift:
        return ""
    for name in ("image", "icon", "icon_url", "picture", "gift_picture", "gift_image"):
        urls = [u for u in _urls_of(field(gift, name, default=None)) if isinstance(u, str) and u.startswith(("http://", "https://"))]
        good = [u for u in urls if ".heic" not in u.lower()]
        if good:
            return good[0]
    return ""

GIFTS_FILE = os.path.join(HERE, "gift_catalog.json")

def _load_gifts():
    try:
        with open(GIFTS_FILE, encoding="utf-8") as f:
            return {g["name"]: g for g in json.load(f) if isinstance(g, dict) and g.get("name")}
    except Exception:
        return {}

def _save_gifts():
    try:
        with open(GIFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(GIFTS.values()), f, ensure_ascii=False, indent=1)
    except Exception as e:
        print("hediye kataloğu kaydedilemedi:", e)

GIFTS = _load_gifts()

GIFT_CAT_URL = "https://beetgames.com/tiktok-gifts.json"
GIFT_CAT_FILE = os.path.join(HERE, "gift_catalog_all.json")

def _build_catalog(raw):
    out = []
    for g in (raw.get("gifts") or []):
        name = str(g.get("name") or "").strip()
        if not name:
            continue
        img = str(g.get("image_url") or "")
        if img.startswith("/"):
            img = "https://beetgames.com" + img
        regions = [str(x).upper() for x in (g.get("regions") or [])]
        out.append({"n": name, "i": img, "c": int(g.get("coins") or 0), "tr": "TR" in regions})
    return out

def _load_catalog_file():
    try:
        with open(GIFT_CAT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

GIFT_CAT = _load_catalog_file()

def _refresh_catalog():
    global GIFT_CAT
    try:
        req = urllib.request.Request(GIFT_CAT_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = json.loads(r.read().decode("utf-8"))
        cat = _build_catalog(raw)
        if cat:
            GIFT_CAT = cat
            with open(GIFT_CAT_FILE, "w", encoding="utf-8") as f:
                json.dump(cat, f, ensure_ascii=False)
            print(f"hediye kataloğu güncellendi: {len(cat)} hediye")
    except Exception as e:
        print("hediye kataloğu indirilemedi, önbellek kullanılıyor:", e)

def _catalog_loop():
    while True:
        _refresh_catalog()
        time.sleep(24 * 3600)

def user_info(event):
    user = field(event, "user", "from_user", default=None)
    username = field(user, "unique_id", "uniqueId", "nickname", "display_id", default="user") if user else "user"
    nickname = field(user, "nickname", "display_name", default=username) if user else username
    avatar = pick_avatar(user)
    username = str(username or "user").lstrip("@")
    if avatar and username not in AVATAR_CACHE:
        print("[AVATAR]", username, "olaydan gelen: ~%dpx" % _av_size(avatar), avatar[:100])
    if avatar:
        _old = AVATAR_CACHE.get(username, "")
        if not _old or _av_size(avatar) >= _av_size(_old):
            AVATAR_CACHE[username] = avatar
        else:
            avatar = _old
    else:
        avatar = AVATAR_CACHE.get(username, "")
    return username, str(nickname or username or "user"), str(avatar or "")

def push(kind, event=None, **extra):
    global STREAMER_AVATAR
    username, nickname, avatar = user_info(event) if event is not None else ("", "", "")
    if avatar and ACTIVE_STREAMER and username.lower() == str(ACTIVE_STREAMER).lstrip("@").lower() and avatar != STREAMER_AVATAR:
        STREAMER_AVATAR = avatar
        broadcast({"type": "streamer_avatar", "username": username, "avatar": avatar, "timestamp": time.time()})
    data = {"type": kind, "username": username, "nickname": nickname, "avatar": avatar, "timestamp": time.time()}
    data.update(extra)
    with state_lock:
        if kind == "gift":
            gname = str(data.get("gift", "") or "")
            if gname:
                old = GIFTS.get(gname, {})
                _gchg = gname not in GIFTS or (bool(data.get("icon")) and data.get("icon") != GIFTS[gname].get("icon"))
                GIFTS[gname] = {"name": gname, "icon": data.get("icon") or old.get("icon", ""), "dia": int(data.get("diamonds", 0) or 0) // max(1, int(data.get("count", 1) or 1))}
                if _gchg:
                    _save_gifts()
            STATS["gift"] += max(1, int(data.get("count", 1) or 1))
            STATS["dia"] += max(0, int(data.get("diamonds", 0) or 0))
        elif kind in STATS:
            increment = max(1, int(data.get("count", 1) or 1)) if kind == "like" else 1
            STATS[kind] += increment
        data["stats"] = dict(STATS)
    print(f"[{kind}] @{username} {data.get('text', '') or data.get('gift', '')}")
    broadcast(data)

def number_from(obj, *names, default=0):
    val = field(obj, *names, default=default)
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return default

def on_event(client, names, callback):
    if tiktok_events is None:
        return False
    for name in names:
        event_cls = getattr(tiktok_events, name, None)
        if event_cls is not None:
            client.on(event_cls)(callback)
            print(f"[event] {name} etkinleştirildi")
            return True
    print(f"[event] Desteklenmeyen olay: {' / '.join(names)}")
    return False

async def run_client(user, stop_token):
    global active_client, active_loop
    if TikTokLiveClient is None:
        status("error", "TikTokLive kurulu değil: " + TIKTOK_IMPORT_ERROR, user)
        return
    while not stop_token.is_set():
        client = None
        try:
            client = TikTokLiveClient(unique_id=user)
            loop = asyncio.get_running_loop()
            with state_lock:
                active_client, active_loop = client, loop

            async def connected(event):
                global STREAMER_AVATAR
                status("connected", f"Yayına bağlanıldı: @{user}", user)
                try:
                    info = getattr(client, "room_info", None)
                    owner = field(info, "owner", default=None) if info else None
                    av = pick_avatar(owner)
                    if av: STREAMER_AVATAR = av
                except Exception as exc:
                    print("Yayıncı profil resmi alınamadı:", repr(exc))
                broadcast({"type": "hello", "username": user, "avatar": STREAMER_AVATAR, "stats": stats_snapshot()})
            async def disconnected(event):
                if not stop_token.is_set():
                    status("connecting", "Bağlantı kesildi; yeniden bağlanılıyor…", user)
            async def joined(event): push("join", event)
            async def left(event): push("leave", event)
            async def commented(event): push("comment", event, text=str(field(event, "comment", "text", default="")))
            async def followed(event): push("follow", event)
            async def liked(event): push("like", event, count=number_from(event, "like_count", "count", default=1))
            async def shared(event): push("share", event)
            async def gifted(event):
                gift = field(event, "gift", default=None)
                streaking = bool(field(event, "streaking", default=False))
                streakable = bool(field(gift, "streakable", default=False))
                if streakable and streaking:
                    return
                count = number_from(event, "repeat_count", "count", default=1)
                diamonds = number_from(gift, "diamond_count", "diamondCount", default=1) * max(1, count)
                push("gift", event, gift=str(field(gift, "name", default="Hediye")), count=max(1, count), diamonds=diamonds, icon=pick_gift_icon(gift))
            async def viewers(event):
                count = number_from(event, "viewer_count", "user_count", "total", "count", default=-1)
                if count < 0:
                    room = field(event, "room_user", "data", default=None)
                    count = number_from(room, "viewer_count", "user_count", "total", "count", default=-1) if room else -1
                if count >= 0:
                    broadcast({"type": "viewers", "count": count, "timestamp": time.time()})

            on_event(client, ("ConnectEvent",), connected)
            on_event(client, ("DisconnectEvent",), disconnected)
            on_event(client, ("JoinEvent",), joined)
            on_event(client, ("LeaveEvent", "MemberLeaveEvent", "UserLeaveEvent"), left)
            on_event(client, ("CommentEvent",), commented)
            on_event(client, ("FollowEvent",), followed)
            on_event(client, ("LikeEvent",), liked)
            on_event(client, ("ShareEvent",), shared)
            on_event(client, ("GiftEvent",), gifted)
            on_event(client, ("RoomUserSeqEvent", "RoomUserSeqMessageEvent", "ViewerCountEvent"), viewers)

            status("connecting", f"@{user} yayını aranıyor…", user)
            await client.connect()
            if not stop_token.is_set():
                status("connecting", "Bağlantı sonlandı; yeniden deneniyor…", user)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            if not stop_token.is_set():
                status("connecting", f"Bağlantı hatası; 5 sn sonra tekrar denenecek ({type(exc).__name__})", user)
                print("TikTok bağlantı hatası:", repr(exc))
        finally:
            if client is not None:
                try:
                    if getattr(client, "connected", False):
                        await client.disconnect()
                except Exception:
                    pass
            with state_lock:
                if active_client is client:
                    active_client = None
                    active_loop = None
        for _ in range(50):
            if stop_token.is_set():
                break
            await asyncio.sleep(0.1)
    with state_lock:
        still_current = run_stop is stop_token or run_stop is None
    if still_current:
        status("disconnected", "Bağlantı durduruldu", user)

def tiktok_thread(user, stop_token):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_client(user, stop_token))
    finally:
        try: loop.close()
        except Exception: pass

def stop_current():
    global run_stop
    with state_lock:
        token = run_stop
        client = active_client
        loop = active_loop
        run_stop = None
    if token:
        token.set()
    if client is not None and loop is not None and loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(client.disconnect(), loop)
        except Exception:
            pass

ARENA_STATE = {}
HD_CACHE = {}

def hd_avatar(username):
    import re as _re, html as _html
    if not username:
        return ""
    hit = HD_CACHE.get(username)
    if hit and time.time() - hit[0] < (1800 if hit[1] else 90):
        return hit[1]
    desk = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    uas = [
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1", "iphone"),
        (desk, "chrome"),
    ]
    def grab(raw):
        text = _html.unescape(raw or "").replace("\\u002F", "/").replace("\\/", "/")
        candidates = []
        try: root = json.loads(text)
        except Exception: root = None
        def walk(obj, depth=0):
            if depth > 18: return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    key = str(k).replace("_", "").lower()
                    if key in ("avatarlarger", "avatarmedium", "avatarthumb", "avatarlarge", "avatar"):
                        candidates.extend(_urls_of(v))
                    if isinstance(v, (dict, list)): walk(v, depth + 1)
            elif isinstance(obj, list):
                for v in obj[:500]: walk(v, depth + 1)
        if root is not None: walk(root)
        for key in ("avatarLarger", "avatarMedium", "avatarThumb"):
            for m in _re.finditer(r'"' + key + r'"\s*:\s*(?:"((?:\\.|[^"\\])*)"|\{[^}]{0,12000}\})', text):
                val = m.group(1)
                if val:
                    try: candidates.append(json.loads('"' + val + '"'))
                    except Exception: candidates.append(val)
                else:
                    candidates.extend(_re.findall(r'https?:\\?/\\?/[^"\s]+', m.group(0)))
        for pat in (
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        ):
            m = _re.search(pat, text, _re.I)
            if m: candidates.append(m.group(1))
        clean = []
        for item in candidates:
            for candidate in _urls_of(item):
                candidate = str(candidate).replace("\\u002F", "/").replace("\\/", "/")
                candidate = _html.unescape(candidate).replace("&amp;", "&")
                if candidate.startswith("http") and ".heic" not in candidate.lower():
                    clean.append(candidate)
        if not clean: return ""
        return max(enumerate(clean), key=lambda pair: (_av_size(pair[1]), -pair[0]))[1]
    url, via = "", ""
    for ua, tag in uas:
        try:
            req = urllib.request.Request("https://www.tiktok.com/@" + username, headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9", "Accept": "text/html,application/xhtml+xml"})
            with urllib.request.urlopen(req, timeout=7) as r:
                page = r.read(4 * 1024 * 1024).decode("utf-8", "ignore")
            url = grab(page)
            if url: via = tag; break
        except Exception as exc:
            print("[HD profil]", username, tag, "hata:", repr(exc)[:70])
    if not url:
        try:
            api = "https://www.tiktok.com/api/user/detail/?" + urllib.parse.urlencode({"uniqueId": username, "aid": "1988", "app_language": "en", "device_platform": "web_pc", "browser_language": "en-US", "region": "TR"})
            req = urllib.request.Request(api, headers={"User-Agent": desk, "Referer": "https://www.tiktok.com/@" + username, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=7) as r:
                url = grab(r.read(3 * 1024 * 1024).decode("utf-8", "ignore"))
            if url: via = "api"
        except Exception as exc:
            print("[HD profil]", username, "api hata:", repr(exc)[:70])
    print("[HD profil]", username, ("BULUNDU (" + via + ", ~" + str(_av_size(url)) + "px)") if url else "BULUNAMADI")
    if len(HD_CACHE) > 500:
        HD_CACHE.pop(next(iter(HD_CACHE)))
    HD_CACHE[username] = (time.time(), url)
    return url

IMG_CACHE = {}
AI_FILE = os.path.join(HERE, "ai_config.json")
AI_HITS = []

def _ai_cfg():
    c = {"provider": "auto", "key": "", "model": "", "url": ""}
    try:
        with open(AI_FILE, encoding="utf-8") as f: c.update(json.load(f))
    except Exception: pass
    key = c.get("key") or ""
    prov = c.get("provider", "auto")
    if prov == "auto":
        for env, pv in (("ANTHROPIC_API_KEY", "anthropic"), ("OPENAI_API_KEY", "openai"), ("GEMINI_API_KEY", "gemini")):
            if not key and os.environ.get(env): key, prov = os.environ[env], pv
        if prov == "auto":
            prov = "anthropic" if key.startswith("sk-ant") else "gemini" if key.startswith("AIza") else "openai" if key.startswith("sk-") else ("ollama" if c.get("url") or c.get("model") else "none")
    c["key"], c["provider"] = key, prov
    return c

def _post_json(url, body, headers, timeout=12):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=dict({"Content-Type": "application/json"}, **headers))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def ai_call(system, user, max_tokens=90):
    c = _ai_cfg()
    p, key, model = c["provider"], c["key"], c.get("model", "")
    if p == "none" or (p != "ollama" and not key):
        raise PermissionError("nokey")
    now = time.time()
    AI_HITS[:] = [t for t in AI_HITS if now - t < 60]
    if len(AI_HITS) >= 40: raise RuntimeError("busy")
    AI_HITS.append(now)
    if p == "anthropic":
        j = _post_json("https://api.anthropic.com/v1/messages", {"model": model or "claude-haiku-4-5", "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]}, {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return "".join(x.get("text", "") for x in j.get("content", []))
    if p == "openai":
        j = _post_json((c.get("url") or "https://api.openai.com/v1") + "/chat/completions", {"model": model or "gpt-4o-mini", "max_tokens": max_tokens, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, {"Authorization": "Bearer " + key})
        return j["choices"][0]["message"]["content"]
    if p == "gemini":
        j = _post_json("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (model or "gemini-2.0-flash", key), {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": {"maxOutputTokens": max_tokens}}, {})
        return j["candidates"][0]["content"]["parts"][0]["text"]
    j = _post_json((c.get("url") or "http://localhost:11434") + "/api/chat", {"model": model or "llama3.1", "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, {}, 25)
    return j["message"]["content"]

PUBLIC_ASSETS = {"/common.js", "/character.js", "/three.js", "/img", "/avatar", "/streamer_avatar", "/favicon.ico"}

class Handler(BaseHTTPRequestHandler):
    disable_nagle_algorithm = True
    def log_message(self, *args): pass

    def send_bytes(self, code, data, content_type="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def _json_cors(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _session(self):
        return get_session(parse_cookie(self.headers.get("Cookie", "")).get("rex_session"))

    def _device_cookie(self):
        return parse_cookie(self.headers.get("Cookie", "")).get("rex_device", "")

    def _client_ip(self):
        xff = self.headers.get("X-Forwarded-For", "")
        if xff: return xff.split(",")[0].strip()
        return self.client_address[0] if self.client_address else ""

    def _admin(self):
        return is_admin_token(parse_cookie(self.headers.get("Cookie", "")).get("rex_admin"))

    def _require_auth(self):
        if AUTH_DISABLED: return True
        if not self._session():
            self.send_response(302)
            self.send_header("Location", SITE_URL)
            self.end_headers()
            return False
        return True

    def _serve_html(self, filename, fallback):
        try:
            with open(os.path.join(HERE, filename), "rb") as f:
                self.send_bytes(200, f.read(), "text/html; charset=utf-8")
        except OSError:
            self.send_bytes(200, fallback.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        global ARENA_STATE
        path = urlparse(self.path).path

        # === Sitedeki sipariş formu (form gönderimi; HTML sayfası döner) ===
        if path == "/siparis":
            ip = self._client_ip()
            raw = self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 5000)).decode("utf-8", "ignore")
            f = {k: v[0] for k, v in parse_qs(raw).items()}
            product = str(f.get("product", "")).strip()
            contact = normalize_contact(f.get("contact"))
            if not _order_rate_ok(ip):
                page = _page_msg("Çok fazla deneme", "Lütfen birkaç dakika sonra tekrar deneyin.")
            elif product not in PRODUCTS:
                page = _page_msg("Paket seçilmedi", "Lütfen bir paket seçip tekrar deneyin.")
            elif not contact:
                page = _page_msg("İletişim bilgisi geçersiz", "Geçerli bir telefon numarası (05xx xxx xx xx) veya e-posta adresi girin.")
            else:
                o, _ = create_order(product, contact, ip, self.headers.get("User-Agent", ""))
                page = _page_order(o)
            self.send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return

        # === Satış sayfasından gelen sipariş (herkese açık) -> Telegram bildirimi ===
        if path == "/api/order":
            try:
                ip = self._client_ip()
                if not _order_rate_ok(ip):
                    self._json_cors(429, {"ok": False, "err": "Çok fazla deneme, biraz sonra tekrar deneyin"}); return
                raw = self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 5000)).decode("utf-8", "ignore")
                try:
                    req = json.loads(raw)
                except Exception:
                    req = {k: v[0] for k, v in parse_qs(raw).items()}
                product = str(req.get("product", "")).strip()
                contact = normalize_contact(req.get("contact"))
                if product not in PRODUCTS:
                    self._json_cors(200, {"ok": False, "err": "Geçersiz paket"}); return
                if not contact:
                    self._json_cors(200, {"ok": False, "err": "Geçerli bir telefon numarası (05xx xxx xx xx) veya e-posta adresi girin"}); return
                o, notified = create_order(product, contact, ip, self.headers.get("User-Agent", ""))
                self._json_cors(200, {"ok": True, "order_id": o["id"], "notified": notified})
            except Exception as e:
                print("[SİPARİŞ] hata:", repr(e))
                self._json_cors(500, {"ok": False, "err": "Sunucu hatası"})
            return

        # === Müşteri: sipariş takibi (sipariş no + iletişim eşleşmesi) ===
        if path == "/api/order/status":
            try:
                ip = self._client_ip()
                if not _order_rate_ok("status:" + ip, 25):
                    self._json_cors(429, {"ok": False, "err": "Çok fazla deneme, biraz sonra tekrar deneyin"}); return
                req = _read_json(self)
                oid = str(req.get("id", "")).strip().upper()
                contact = normalize_contact(req.get("contact"))
                o = _load_orders().get(oid) if oid else None
                if not o or not contact or normalize_contact(o.get("contact")) != contact:
                    self._json_cors(200, {"ok": False, "err": "Sipariş bulunamadı. Sipariş numarasını ve iletişim bilginizi kontrol edin."}); return
                out = {"ok": True, "id": oid, "plan_name": o.get("plan_name", ""),
                       "status": o.get("status", "pending"), "created": o.get("created")}
                if out["status"] == "approved":
                    out["key"] = o.get("key")
                    out["expires"] = o.get("expires")
                self._json_cors(200, out)
            except Exception as e:
                print("[TAKİP] hata:", repr(e))
                self._json_cors(500, {"ok": False, "err": "Sunucu hatası"})
            return

        # === Kullanıcı Login ===
        if path == "/api/login":
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
                key = str(req.get("key", "")).strip().upper()
                ok, info = validate_key(key)
                if not ok:
                    self._json(200, {"ok": False, "err": info}); return
                device = self._device_cookie()
                new_cookie = False
                if not device:
                    device = secrets.token_urlsafe(24)
                    new_cookie = True
                ok2, msg = check_device(key, device)
                if not ok2:
                    self._json(200, {"ok": False, "err": msg}); return
                lock_device(key, device, self._client_ip(), self.headers.get("User-Agent", ""))
                token = new_session(key, info, device)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"rex_session={token}; HttpOnly; Path=/; SameSite=Lax")
                if new_cookie:
                    self.send_header("Set-Cookie", f"rex_device={device}; Max-Age=31536000; Path=/; SameSite=Lax")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "plan": info.get("plan"), "expires": info.get("expires")}, ensure_ascii=False).encode())
            except Exception as e:
                self._json(400, {"ok": False, "err": str(e)})
            return

        # === Admin girişi / çıkışı ===
        if path == "/api/admin/login":
            ip = self._client_ip()
            if _admin_locked(ip):
                self._json(429, {"ok": False, "err": "Çok fazla hatalı deneme. Birkaç dakika bekleyin."}); return
            req = _read_json(self)
            if not ADMIN_PASS or not _same(req.get("pass", ""), ADMIN_PASS):
                _admin_fail(ip)
                self._json(200, {"ok": False, "err": "Hatalı şifre"}); return
            _admin_ok(ip)
            tok = new_admin_session()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", f"rex_admin={tok}; HttpOnly; Path=/; SameSite=Strict")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        if path == "/api/admin/logout":
            tok = parse_cookie(self.headers.get("Cookie", "")).get("rex_admin")
            if tok: drop_admin(tok)
            self.send_response(200)
            self.send_header("Set-Cookie", "rex_admin=; Max-Age=0; Path=/")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        # === Admin: sipariş onay / red ===
        if path == "/api/admin/order":
            if not self._admin():
                self._json(401, {"ok": False, "err": "Yetkisiz"}); return
            req = _read_json(self)
            o, err, key = _decide_order(str(req.get("id", "")).strip().upper(), str(req.get("action", "")))
            if o is None or err:
                self._json(200, {"ok": False, "err": err or "Sipariş bulunamadı", "key": key}); return
            self._json(200, {"ok": True, "key": key, "status": o["status"]})
            return

        # === Admin: anahtar işlemleri (sıfırla, iptal, sil, süre uzat) ===
        if path == "/api/admin/action":
            if not self._admin():
                self._json(401, {"ok": False, "err": "Yetkisiz"}); return
            req = _read_json(self)
            key = str(req.get("key", "")).strip().upper()
            try: days = int(req.get("days") or 0)
            except (TypeError, ValueError): days = 0
            ok, msg = admin_key_action(key, str(req.get("action", "")), days)
            self._json(200, {"ok": True, "msg": msg} if ok else {"ok": False, "err": msg})
            return

        # === Admin: manuel anahtar üretme ===
        if path == "/api/admin/newkey":
            if not self._admin():
                self._json(401, {"ok": False, "err": "Yetkisiz"}); return
            req = _read_json(self)
            p = PRODUCTS.get(str(req.get("product", "")).strip())
            if not p:
                self._json(200, {"ok": False, "err": "Geçersiz paket"}); return
            try: days = min(3650, max(0, int(req.get("days") or 0)))
            except (TypeError, ValueError): days = 0
            days = days or p["days"]
            owner = " ".join(str(req.get("owner", "")).split())[:120]
            key, info = create_key(days, p["plan"], owner, order_id="MANUEL")
            print(f"[ADMIN] manuel anahtar · {p['plan']} · {days} gün")
            self._json(200, {"ok": True, "key": key, "expires": info.get("expires")})
            return

        # === Dış sistemden anahtar üretme (ADMIN_SECRET gerekir) ===
        if path == "/api/create-key":
            if not ADMIN_SECRET or not _same(self.headers.get("X-Admin-Secret", ""), ADMIN_SECRET):
                self._json(401, {"ok": False, "err": "Yetkisiz"}); return
            req = _read_json(self)
            p = PRODUCTS.get(str(req.get("product", "")))
            if not p:
                self._json(200, {"ok": False, "err": "Geçersiz ürün"}); return
            key, info = create_key(p["days"], p["plan"], str(req.get("buyer", ""))[:120])
            print(f"[YENİ KEY] {key} · {p['plan']}")
            self._json(200, {"ok": True, "key": key, "plan": p["plan"], "expires": info["expires"], "days": p["days"]})
            return

        if not self._require_auth(): return

        if path == "/ai":
            try:
                req = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 20000)).decode("utf-8"))
                out = {"ok": True, "text": ai_call(str(req.get("system", ""))[:2500], str(req.get("user", ""))[:1200], min(200, int(req.get("max_tokens", 90) or 90))).strip()}
            except PermissionError: out = {"ok": False, "err": "nokey"}
            except Exception as e:
                out = {"ok": False, "err": "busy" if str(e) == "busy" else "fail"}
                print("AI hatası:", repr(e))
            self.send_bytes(200, json.dumps(out, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/ai_cfg":
            try:
                n = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 5000)).decode("utf-8"))
                old = {}
                try:
                    with open(AI_FILE, encoding="utf-8") as f: old = json.load(f)
                except Exception: pass
                for k in ("provider", "model", "url"):
                    old[k] = str(n.get(k, old.get(k, "")))[:200]
                if str(n.get("key", "")).strip(): old["key"] = str(n["key"]).strip()[:300]
                if n.get("clear"): old["key"] = ""
                with open(AI_FILE, "w", encoding="utf-8") as f: json.dump(old, f)
            except Exception as e:
                print("AI ayarı kaydedilemedi:", repr(e))
            self.send_bytes(200, b"OK")
            return
        if path == "/arena_state":
            try: ARENA_STATE = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 300000)).decode("utf-8"))
            except Exception: pass
            self.send_bytes(200, b"OK")
            return
        self.send_bytes(404, b"no")

    def do_GET(self):
        global ACTIVE_STREAMER, run_stop, worker
        p = urlparse(self.path)

        # === Kullanıcı Doğrulama (Siteden kilit açma isteği gelirse) ===
        if p.path == "/api/verify":
            try:
                q = parse_qs(p.query)
                contact = normalize_contact(q.get("contact", [""])[0])
                if not contact:
                    self._json_cors(200, {"ok": False, "err": "İletişim bilgisi gerekli"}); return
                
                orders = _load_orders()
                # Bu iletişim bilgisine sahip siparişleri bul
                user_orders = [o for o in orders.values() if normalize_contact(o.get("contact")) == contact]
                
                if not user_orders:
                    self._json_cors(200, {"ok": False, "err": "Sipariş bulunamadı"}); return
                    
                approved = any(o.get("status") == "approved" for o in user_orders)
                self._json_cors(200, {"ok": True, "approved": approved})
            except Exception as e:
                print("[VERIFY] hata:", repr(e))
                self._json_cors(500, {"ok": False, "err": "Sunucu hatası"})
            return

        if p.path == "/admin":
            self.send_bytes(200, ADMIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return

        if p.path == "/api/admin/keys":
            if not self._admin():
                self._json(401, {"ok": False, "err": "Yetkisiz"}); return
            keys = _load_keys()
            with SESSIONS_LOCK:
                sessions = [{"key": s["key"], "device": s.get("device"), "plan": s.get("plan"), "created": s.get("created")} for s in SESSIONS.values()]
            fields = ("plan", "owner", "order_id", "expires", "created", "active", "device", "device_locked_at",
                      "last_login", "last_ip", "last_ua", "login_count", "history")
            out_keys = [{"license_key": key, **{f: v.get(f) for f in fields}} for key, v in keys.items()]
            self._json(200, {"ok": True, "keys": out_keys, "active_sessions": sessions})
            return

        if p.path == "/api/admin/orders":
            if not self._admin():
                self._json(401, {"ok": False, "err": "Yetkisiz"}); return
            orders = sorted(_load_orders().values(), key=lambda o: o.get("created", ""), reverse=True)
            self._json(200, {"ok": True, "orders": orders[:300]})
            return

        # === Sipariş takibi (form / bağlantı ile, HTML sayfası döner) ===
        if p.path == "/takip":
            q = parse_qs(p.query)
            oid = str(q.get("id", [""])[0]).strip().upper()[:12]
            contact = normalize_contact(q.get("contact", [""])[0])
            if not oid and not contact:
                page = _page_track_form()
            elif not oid or not contact:
                page = _page_track_form(oid, "Sipariş numarası ve geçerli bir telefon veya e-posta girin.")
            elif not _order_rate_ok("track:" + self._client_ip(), 25):
                page = _page_msg("Çok fazla deneme", "Lütfen birkaç dakika sonra tekrar deneyin.")
            else:
                o = _load_orders().get(oid)
                if not o or normalize_contact(o.get("contact")) != contact:
                    page = _page_track_form(oid, "Sipariş bulunamadı. Sipariş numarasını ve iletişim bilginizi kontrol edin.")
                else:
                    page = _page_track_result(o)
            self.send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if p.path in ("/login", "/giris"):
            if self._session():
                self.send_response(302)
                self.send_header("Location", "/panel")
                self.end_headers()
                return
            self._serve_html("login.html", LOGIN_HTML)
            return

        if p.path == "/logout":
            tok = parse_cookie(self.headers.get("Cookie", "")).get("rex_session")
            if tok:
                with SESSIONS_LOCK: SESSIONS.pop(tok, None)
            self.send_response(302)
            self.send_header("Set-Cookie", "rex_session=; Max-Age=0; Path=/")
            self.send_header("Location", SITE_URL)
            self.end_headers()
            return

        if p.path == "/api/session":
            s = self._session()
            self._json(200, {"ok": bool(s), "plan": s.get("plan") if s else None,
                            "expires": s.get("expires") if s else None,
                            "device": s.get("device") if s else None})
            return

        if p.path not in PUBLIC_ASSETS:
            if not self._require_auth(): return

        if p.path == "/panel":
            self._serve_html("panel.html", PANEL_HTML)
            return

        if p.path in ("/", "/studio", "/lazer", "/arena", "/karpuz", "/minecraft", "/slime", "/cip", "/pos"):
            filename = {"/lazer": "lazer.html", "/arena": "arena.html", "/karpuz": "karpuz.html", "/minecraft": "minecraft.html", "/slime": "slime_atolyesi.html", "/cip": "cip.html", "/pos": "pos.html"}.get(p.path, "studio.html")
            try:
                with open(os.path.join(HERE, filename), "rb") as f:
                    self.send_bytes(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self.send_bytes(500, b"UI file missing")
        elif p.path in ("/common.js", "/character.js"):
            try:
                with open(os.path.join(HERE, p.path.lstrip("/")), "rb") as f:
                    self.send_bytes(200, f.read(), "application/javascript; charset=utf-8")
            except OSError:
                self.send_bytes(404, b"common.js missing")
        elif p.path == "/three.js":
            if os.path.exists(THREE_FILE):
                with open(THREE_FILE, "rb") as f:
                    self.send_bytes(200, f.read(), "application/javascript; charset=utf-8")
            else:
                self.send_bytes(404, b"Three.js not downloaded; check network")
        elif p.path == "/arena_state":
            self.send_bytes(200, json.dumps(ARENA_STATE, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        elif p.path == "/arena_cmd":
            q = parse_qs(p.query)
            broadcast({"type": "cmd", "c": q.get("c", [""])[0][:20], "txt": q.get("txt", [""])[0][:200]})
            self.send_bytes(200, b"OK")
        elif p.path == "/ai_cfg":
            c = _ai_cfg()
            self.send_bytes(200, json.dumps({"provider": c["provider"], "model": c.get("model", ""), "url": c.get("url", ""), "hasKey": bool(c["key"])}).encode(), "application/json; charset=utf-8")
        elif p.path == "/health":
            with state_lock:
                result = {"status": dict(STATUS), "stats": dict(STATS), "streamer": ACTIVE_STREAMER, "events_available": bool(tiktok_events)}
            self.send_bytes(200, json.dumps(result, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        elif p.path == "/connect":
            user = parse_qs(p.query).get("user", [""])[0].strip().lstrip("@").strip()
            if not user or len(user) > 100 or any(c.isspace() for c in user):
                self.send_bytes(400, b"Gecerli TikTok kullanici adi gerekli"); return
            stop_current()
            token = threading.Event()
            with state_lock:
                ACTIVE_STREAMER = user
                run_stop = token
                for k in STATS: STATS[k] = 0
                status_data = {"type": "hello", "username": user, "stats": dict(STATS)}
            broadcast(status_data)
            status("connecting", f"@{user} yayını aranıyor…", user)
            worker = threading.Thread(target=tiktok_thread, args=(user, token), daemon=True, name="RexTikTokLive")
            worker.start()
            self.send_bytes(202, b"CONNECTING")
        elif p.path == "/test":
            q = parse_qs(p.query); kind = q.get("type", ["join"])[0]
            if kind not in ("join", "like", "share", "follow", "comment", "gift"):
                self.send_bytes(400, b"bad type"); return
            n = random.choice(["ayse_k", "mehmet.t", "rex_fan", "zeynep", "can_61", "leylak", "deniz.m", "burak"])
            extra = {"username": n, "nickname": n}
            if kind == "comment":
                extra["text"] = random.choice(["Selam!", "Nasılsın?", "Çok tatlısın", "Adın ne?", "Hangi animeyi seversin?", "1", "2", "Bugün çok yoruldum ama geldim", "Seni seviyorum", "Ben gidiyorum görüşürüz"])
            if kind == "like": extra["count"] = random.randint(1, 15)
            if kind == "gift":
                try: d = max(1, int(q.get("d", ["30"])[0]))
                except ValueError: d = 30
                extra.update(gift="Gül" if d < 100 else "Aslan", count=1, diamonds=d)
            push(kind, None, **extra)
            self.send_bytes(200, b"OK")
        elif p.path == "/stop":
            stop_current()
            status("disconnected", "Bağlantı durdurma istendi", ACTIVE_STREAMER)
            self.send_bytes(200, b"STOPPED")
        elif p.path == "/giftcat":
            self.send_bytes(200, json.dumps(GIFT_CAT, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        elif p.path == "/gifts":
            self.send_bytes(200, json.dumps(list(GIFTS.values()), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        elif p.path == "/events":
            q = queue.Queue(maxsize=500)
            with clients_lock: clients.append(q)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                q.put_nowait(event_payload({"type": "hello", "username": ACTIVE_STREAMER, "avatar": STREAMER_AVATAR, "stats": stats_snapshot()}))
                q.put_nowait(event_payload({"type": "status", **dict(STATUS)}))
                while True:
                    try: chunk = q.get(timeout=12)
                    except queue.Empty: chunk = b": keepalive\n\n"
                    self.wfile.write(chunk); self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError): pass
            finally:
                with clients_lock:
                    if q in clients: clients.remove(q)
        elif p.path == "/avatar":
            import re as _re
            uname = _re.sub(r"[^A-Za-z0-9_.]", "", parse_qs(p.query).get("u", [""])[0])[:40]
            self.send_bytes(200, json.dumps({"url": hd_avatar(uname)}).encode("utf-8"), "application/json; charset=utf-8")
        elif p.path == "/img":
            url = parse_qs(p.query).get("u", [""])[0]
            if url.startswith("http://"): url = "https://" + url[7:]
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            allowed_hosts = ("tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "tiktok.com", "tiktokv.com", "tiktokv.us", "tiktokv.eu", "byteoversea.com", "ibytedtos.com", "ibyteimg.com", "byteimg.com", "muscdn.com", "ttwstatic.com", "beetgames.com")
            allowed = any(host == domain or host.endswith("." + domain) for domain in allowed_hosts)
            if parsed.scheme != "https" or not host or not allowed:
                self.send_bytes(400, b"Invalid image URL"); return
            try:
                hit = IMG_CACHE.get(url)
                if hit:
                    data, content_type = hit
                else:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.tiktok.com/", "Accept": "image/avif,image/webp,image/jpeg,image/*,*/*;q=0.8"})
                    with urllib.request.urlopen(req, timeout=8) as r:
                        content_type = r.headers.get("Content-Type", "image/jpeg")
                        if not content_type.startswith("image/"): raise ValueError("not image")
                        data = r.read(3 * 1024 * 1024 + 1)
                    if len(data) > 3 * 1024 * 1024: raise ValueError("image too large")
                    if len(IMG_CACHE) > 400: IMG_CACHE.pop(next(iter(IMG_CACHE)))
                    IMG_CACHE[url] = (data, content_type)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data)
            except Exception:
                self.send_bytes(502, b"Image unavailable")
        elif p.path == "/streamer_avatar":
            found = None
            for ext, mime in (("png", "image/png"), ("jpg", "image/jpeg"), ("jpeg", "image/jpeg"), ("webp", "image/webp")):
                fp = os.path.join(HERE, "yayinci." + ext)
                if os.path.exists(fp): found = (fp, mime); break
            if not found:
                self.send_bytes(404, b"Not found"); return
            with open(found[0], "rb") as f: data = f.read()
            self.send_bytes(200, data, found[1])
        else:
            self.send_bytes(404, b"Not found")

def main():
    threading.Thread(target=_catalog_loop, daemon=True).start()
    threading.Thread(target=tg_poll_loop, daemon=True, name="RexTelegram").start()
    _c = _tg_cfg()
    if not _c["token"] or not _c["chat_id"]:
        print("\n⚠️  TELEGRAM AYARLI DEĞİL! Sipariş bildirimi gelmez.")
        print("   tg_config.json oluştur: {\"token\": \"BOT_TOKEN\", \"chat_id\": \"CHAT_ID\"}")
        print("   (chat_id için botuna Telegram'dan /start yaz, sana ID'ni söyler)\n")
    else:
        tg_send("🟢 REX Stüdyo sunucusu başladı. Sipariş bildirimleri aktif.")
    if ADMIN_PASS_GENERATED:
        print(f"\n⚠️  admin_pass tanımlı değil. Bu çalışma için geçici şifre: {ADMIN_PASS}")
        print("   Kalıcı şifre için tg_config.json içine \"admin_pass\" ekleyin.\n")
    if not ADMIN_SECRET:
        print("ℹ️  admin_secret yok: /api/create-key kapalı (panelden anahtar üretimi etkilenmez).")
    if not os.path.exists(THREE_FILE):
        try:
            req = urllib.request.Request(THREE_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                with open(THREE_FILE, "wb") as f: f.write(r.read())
        except Exception as exc:
            print("Three.js otomatik indirilemedi; /lazer ekranı için internet/CDN gerekebilir:", exc)
    if not AUTH_DISABLED and not _load_keys():
        print("=" * 55)
        print("  ⚠️  Hiç lisans anahtarı yok. Yönetim panelinden üretebilirsin (/admin).")
        print("=" * 55)
    print("=" * 55)
    print(f"  ✅ REX Stüdyo Sunucusu: http://localhost:{PORT}")
    print(f"  🔐 Müşteri girişi:      http://localhost:{PORT}/login")
    print(f"  🛡️  Yönetim paneli:      http://localhost:{PORT}/admin")
    if AUTH_DISABLED:
        print("  ⚠️  REX_AUTH_DISABLED=1 — auth devre dışı")
    print("=" * 55)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        stop_current(); srv.server_close()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("newkey", "--newkey"):
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        plan = sys.argv[3] if len(sys.argv) > 3 else "monthly"
        owner = sys.argv[4] if len(sys.argv) > 4 else ""
        key, info = create_key(days, plan, owner)
        print(f"\n✅ Lisans anahtarı oluşturuldu:\n   {key}")
        print(f"   Plan: {plan} · Bitiş: {info['expires'] or 'Süresiz'}\n")
        sys.exit(0)
    main()
