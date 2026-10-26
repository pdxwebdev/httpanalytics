async def go(app):
    from plugins.httpanalytics.capture import install
    from plugins.httpanalytics.store import ensure_indexes

    install()
    try:
        await ensure_indexes(app.config)
    except Exception:
        pass
