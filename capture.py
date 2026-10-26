"""Record HTTP requests without storing query strings, cookies, or headers."""

import hashlib
import inspect
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from tornado.ioloop import IOLoop
from tornado.web import RequestHandler

from yadacoin.http.base import BaseHandler

COLLECTION = "http_analytics"
COOKIE = "yada_vid"
SKIP_PREFIXES = ("/analytics/api", "/httpanalyticsstatic")
_INSTALLED = False

_BOT = re.compile(
    r"bot|spider|crawl|slurp|curl|wget|python-requests|go-http|headless|scrapy|httpie",
    re.I,
)


def install():
    global _INSTALLED
    if _INSTALLED or getattr(RequestHandler, "_yada_analytics", False):
        _INSTALLED = True
        return
    orig_prepare = RequestHandler.prepare
    orig_finish = RequestHandler.on_finish

    async def prepare(self, *args, **kwargs):
        self._analytics_t0 = time.monotonic()
        result = orig_prepare(self, *args, **kwargs)
        if inspect.isawaitable(result):
            await result
        try:
            ensure_visitor(self)
        except Exception:
            pass
        return result

    def on_finish(self):
        try:
            schedule(self)
        except Exception:
            pass
        return orig_finish(self)

    RequestHandler.prepare = prepare
    RequestHandler.on_finish = on_finish
    # BaseHandler.prepare does not call RequestHandler.prepare.
    orig_base = BaseHandler.prepare

    async def base_prepare(self, *args, **kwargs):
        self._analytics_t0 = time.monotonic()
        result = orig_base(self, *args, **kwargs)
        if inspect.isawaitable(result):
            await result
        try:
            ensure_visitor(self)
        except Exception:
            pass
        return result

    BaseHandler.prepare = base_prepare
    RequestHandler._yada_analytics = True
    BaseHandler._yada_analytics = True
    _INSTALLED = True


def ensure_visitor(handler):
    if getattr(handler, "_finished", False):
        return ""
    current = handler.get_cookie(COOKIE) or ""
    if not _cookie_ok(current):
        current = uuid.uuid4().hex
        handler.set_cookie(
            COOKIE,
            current,
            expires_days=365,
            httponly=True,
            samesite="Lax",
            path="/",
        )
    return current


def _cookie_ok(value):
    return bool(re.fullmatch(r"[a-f0-9]{32}", value or ""))


def skip_path(path):
    path = path or "/"
    return any(path.startswith(prefix) for prefix in SKIP_PREFIXES)


def browser_name(ua):
    ua = ua or ""
    low = ua.lower()
    if "edg/" in low:
        return "Edge"
    if "chrome/" in low or "crios/" in low:
        return "Chrome"
    if "firefox/" in low or "fxios/" in low:
        return "Firefox"
    if "safari/" in low:
        return "Safari"
    if "curl/" in low:
        return "curl"
    if "wget/" in low:
        return "wget"
    if "python-requests" in low:
        return "python-requests"
    if "go-http-client" in low:
        return "go-http"
    if not ua:
        return "unknown"
    return "Other"


def clean_referer(value):
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except Exception:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    path = parts.path or "/"
    return f"{parts.scheme}://{parts.netloc}{path}"[:180]


def build_record(handler):
    request = getattr(handler, "request", None)
    if request is None:
        return None
    if (getattr(request, "method", "") or "").upper() == "OPTIONS":
        return None
    path = (getattr(request, "path", None) or "/").split("?")[0] or "/"
    if skip_path(path):
        return None
    headers = getattr(request, "headers", None) or {}
    ua = str(headers.get("User-Agent") or "")[:180]
    ip = str(getattr(request, "remote_ip", "") or "")[:64]
    cookie = ""
    try:
        cookie = handler.get_cookie(COOKIE) or ""
    except Exception:
        cookie = ""
    seed = cookie if _cookie_ok(cookie) else f"{ip}|{ua}"
    vid = hashlib.sha256(seed.encode("utf-8", "replace")).hexdigest()[:16]
    started = getattr(handler, "_analytics_t0", None)
    ms = 0.0
    if started:
        ms = max(0.0, (time.monotonic() - started) * 1000.0)
    status = 0
    try:
        status = int(handler.get_status())
    except Exception:
        status = 0
    nbytes = 0
    try:
        raw = handler._headers.get("Content-Length")
        if raw:
            nbytes = int(raw)
    except Exception:
        nbytes = 0
    country = str(
        headers.get("CF-IPCountry") or headers.get("X-Country") or ""
    )[:8]
    now = datetime.now(timezone.utc)
    return {
        "ts": now,
        "t": now.timestamp(),
        "path": path[:200],
        "method": str(getattr(request, "method", "") or "")[:12],
        "status": status,
        "ms": round(ms, 2),
        "ip": ip,
        "vid": vid,
        "ua": ua,
        "browser": browser_name(ua),
        "referer": clean_referer(str(headers.get("Referer") or headers.get("Referrer") or "")),
        "host": str(getattr(request, "host", "") or "")[:120],
        "bytes": nbytes,
        "country": country,
        "bot": bool(_BOT.search(ua)),
    }


def schedule(handler):
    doc = build_record(handler)
    if not doc:
        return
    IOLoop.current().spawn_callback(_insert, handler, doc)


async def _insert(handler, doc):
    try:
        config = getattr(handler, "config", None)
        if config is None:
            from yadacoin.core.config import Config

            config = Config()
        mongo = getattr(config, "mongo", None)
        db = getattr(mongo, "async_site_db", None)
        if db is None:
            return
        await db[COLLECTION].insert_one(doc)
    except Exception:
        return
