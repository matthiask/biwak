"""The channel layer's Redis address (specs/collaboration.md): from
``CACHE_URL``, which the cluster sets for the shared Redis (e.g.
``hiredis://redis:6379/1/?key_prefix=…``), unless ``REDIS_URL`` is set
explicitly"""

from urllib.parse import urlsplit, urlunsplit


def channels_redis_url(*, redis_url="", cache_url=""):
    """``REDIS_URL`` as it is, else ``CACHE_URL``'s host, port, password and
    database with the scheme ``redis://`` (``rediss://`` stays) and
    without the query string (the cache's key prefix: the channel layer
    has its own, ``biwak``); "" without either"""
    if redis_url:
        return redis_url
    if not cache_url:
        return ""
    parts = urlsplit(cache_url)
    scheme = "rediss" if parts.scheme == "rediss" else "redis"
    db = parts.path.strip("/")
    return urlunsplit((scheme, parts.netloc, f"/{db}" if db else "", "", ""))


def channel_layer(url):
    """The channel layer's settings for the Redis at ``url``

    Its reads wait longer than channels_redis blocks on ``BZPOPMIN`` for
    the next message (``brpop_timeout``, 5 seconds): redis-py 8 times reads
    out after 5 seconds by default, which killed every websocket that heard
    nothing for 5 seconds (decided 2026-11-21: the pages reconnected every
    6 seconds in production)."""
    from channels_redis.core import RedisChannelLayer

    return {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                {
                    "address": url,
                    "socket_timeout": RedisChannelLayer.brpop_timeout + 5,
                }
            ],
            "prefix": "biwak",
        },
    }
