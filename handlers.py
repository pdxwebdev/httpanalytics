import os
import time

from tornado.web import StaticFileHandler

from yadacoin.http.base import BaseHandler

from plugins.httpanalytics.capture import install
from plugins.httpanalytics.store import overview

_ROOT = os.path.dirname(__file__)
_STATIC = os.path.join(_ROOT, "static")
_PAGE = os.path.join(_ROOT, "templates", "index.html")

install()


def asset_version():
    latest = 0
    for folder in ("", "js"):
        path = os.path.join(_STATIC, folder) if folder else _STATIC
        try:
            names = os.listdir(path)
        except OSError:
            continue
        for name in names:
            if not name.endswith((".css", ".js", ".html")):
                continue
            try:
                latest = max(latest, int(os.path.getmtime(os.path.join(path, name))))
            except OSError:
                continue
    return str(latest or int(time.time()))


class AnalyticsStatic(StaticFileHandler):
    def get_cache_time(self, path, modified, mime_type):
        return 0

    def set_extra_headers(self, path):
        self.set_header("Cache-Control", "no-store")


class AnalyticsHandler(BaseHandler):
    async def prepare(self, exceptions=None):
        await super().prepare(exceptions=exceptions)
        if self._finished:
            return
        if self.request.method == "OPTIONS":
            return
        if not await self.wallet_is_unlocked():
            if (self.request.path or "").startswith("/analytics/api"):
                self.set_status(401)
                self.render_as_json({"status": False, "error": "operator session required"})
                return
            self.redirect("/operator")
            return


class AnalyticsPage(AnalyticsHandler):
    async def get(self):
        with open(_PAGE, "r", encoding="utf-8") as handle:
            html = handle.read().replace("__ASSET__", asset_version())
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.set_header("Cache-Control", "no-store")
        self.finish(html)


class AnalyticsOverview(AnalyticsHandler):
    async def get(self):
        data = await overview(self.config, self.get_query_argument("range", "24h"))
        self.render_as_json(data)


HANDLERS = [
    (r"/analytics/?", AnalyticsPage),
    (r"/analytics/api/overview", AnalyticsOverview),
    (r"/httpanalyticsstatic/(.*)", AnalyticsStatic, {"path": _STATIC}),
]
