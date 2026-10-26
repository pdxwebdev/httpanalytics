"""Site-db aggregates for the analytics dashboard."""

from datetime import datetime, timedelta, timezone

from plugins.httpanalytics.capture import COLLECTION

RANGES = {
    "1h": 3600,
    "24h": 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
    "90d": 90 * 86400,
}
BUCKETS = {
    "1h": 60,
    "24h": 900,
    "7d": 3600,
    "30d": 21600,
    "90d": 86400,
}


def collection(config):
    return config.mongo.async_site_db[COLLECTION]


async def ensure_indexes(config):
    coll = collection(config)
    await coll.create_index("ts", expireAfterSeconds=90 * 86400)
    await coll.create_index([("path", 1), ("ts", -1)])
    await coll.create_index([("vid", 1), ("ts", -1)])


def window(range_key):
    key = range_key if range_key in RANGES else "24h"
    now = datetime.now(timezone.utc)
    return key, now - timedelta(seconds=RANGES[key]), BUCKETS[key]


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


async def overview(config, range_key):
    key, start, bucket = window(range_key)
    coll = collection(config)
    match = {"$match": {"ts": {"$gte": start}}}
    summary = await coll.aggregate(
        [
            match,
            {
                "$group": {
                    "_id": None,
                    "requests": {"$sum": 1},
                    "visitors": {"$addToSet": "$vid"},
                    "ips": {"$addToSet": "$ip"},
                    "bytes": {"$sum": "$bytes"},
                    "avg_ms": {"$avg": "$ms"},
                    "max_ms": {"$max": "$ms"},
                    "errors": {
                        "$sum": {"$cond": [{"$gte": ["$status", 400]}, 1, 0]}
                    },
                    "bots": {"$sum": {"$cond": ["$bot", 1, 0]}},
                }
            },
        ]
    ).to_list(1)
    row = summary[0] if summary else {}
    bucket_ms = bucket * 1000
    series = await coll.aggregate(
        [
            match,
            {
                "$group": {
                    "_id": {
                        "$subtract": [
                            {"$toLong": "$ts"},
                            {"$mod": [{"$toLong": "$ts"}, bucket_ms]},
                        ]
                    },
                    "requests": {"$sum": 1},
                    "visitors": {"$addToSet": "$vid"},
                    "errors": {
                        "$sum": {"$cond": [{"$gte": ["$status", 400]}, 1, 0]}
                    },
                }
            },
            {"$sort": {"_id": 1}},
        ]
    ).to_list(500)
    paths = await _top(coll, match, "$path")
    referers = await _top(coll, {"$match": {**match["$match"], "referer": {"$ne": ""}}}, "$referer")
    statuses = await _counts(coll, match, "$status")
    methods = await _counts(coll, match, "$method")
    browsers = await _counts(coll, match, "$browser")
    countries = await _counts(
        coll, {"$match": {**match["$match"], "country": {"$nin": ["", None]}}}, "$country"
    )
    agents = await _counts(coll, match, "$ua", limit=15)
    live = await coll.find(match["$match"], {"_id": 0, "ua": 0}).sort("ts", -1).limit(40).to_list(40)
    requests = int(row.get("requests") or 0)
    bots = int(row.get("bots") or 0)
    return {
        "range": key,
        "from": start.isoformat(),
        "requests": requests,
        "unique_visitors": len(row.get("visitors") or []),
        "unique_ips": len(row.get("ips") or []),
        "bytes": int(row.get("bytes") or 0),
        "avg_ms": round(float(row.get("avg_ms") or 0), 1),
        "max_ms": round(float(row.get("max_ms") or 0), 1),
        "errors": int(row.get("errors") or 0),
        "error_rate": round((int(row.get("errors") or 0) / requests) * 100, 1) if requests else 0,
        "bots": bots,
        "humans": max(0, requests - bots),
        "series": [
            {
                "t": int(item["_id"]),
                "requests": item["requests"],
                "visitors": len(item.get("visitors") or []),
                "errors": item["errors"],
            }
            for item in series
            if item.get("_id") is not None
        ],
        "paths": paths,
        "referers": referers,
        "statuses": statuses,
        "methods": methods,
        "browsers": browsers,
        "countries": countries,
        "agents": agents,
        "live": [_live(item) for item in live],
    }


async def _top(coll, match, field):
    rows = await coll.aggregate(
        [
            match,
            {
                "$group": {
                    "_id": {"key": field, "vid": "$vid"},
                    "requests": {"$sum": 1},
                    "ms": {"$sum": "$ms"},
                    "errors": {
                        "$sum": {"$cond": [{"$gte": ["$status", 400]}, 1, 0]}
                    },
                    "bytes": {"$sum": "$bytes"},
                }
            },
            {
                "$group": {
                    "_id": "$_id.key",
                    "visitors": {"$sum": 1},
                    "requests": {"$sum": "$requests"},
                    "ms": {"$sum": "$ms"},
                    "errors": {"$sum": "$errors"},
                    "bytes": {"$sum": "$bytes"},
                }
            },
            {"$sort": {"requests": -1}},
            {"$limit": 40},
        ]
    ).to_list(40)
    out = []
    for row in rows:
        reqs = int(row.get("requests") or 0)
        out.append(
            {
                "key": row.get("_id") or "/",
                "requests": reqs,
                "visitors": int(row.get("visitors") or 0),
                "avg_ms": round((row.get("ms") or 0) / reqs, 1) if reqs else 0,
                "errors": int(row.get("errors") or 0),
                "bytes": int(row.get("bytes") or 0),
            }
        )
    return out


async def _counts(coll, match, field, limit=12):
    rows = await coll.aggregate(
        [
            match,
            {"$group": {"_id": field, "requests": {"$sum": 1}}},
            {"$sort": {"requests": -1}},
            {"$limit": limit},
        ]
    ).to_list(limit)
    return [{"key": row.get("_id"), "requests": int(row.get("requests") or 0)} for row in rows]


def _live(item):
    return {
        "ts": _iso(item.get("ts")),
        "path": item.get("path") or "/",
        "method": item.get("method") or "",
        "status": item.get("status") or 0,
        "ms": item.get("ms") or 0,
        "ip": item.get("ip") or "",
        "vid": item.get("vid") or "",
        "browser": item.get("browser") or "",
        "referer": item.get("referer") or "",
        "country": item.get("country") or "",
        "bot": bool(item.get("bot")),
        "bytes": int(item.get("bytes") or 0),
    }
