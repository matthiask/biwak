from django.test import SimpleTestCase

from biwak.redis_url import channels_redis_url


class ChannelsRedisURLTest(SimpleTestCase):
    def test_from_the_cache_url(self):
        for cache_url, expected in [
            ("hiredis://redis:6379/1/?key_prefix=biwak", "redis://redis:6379/1"),
            ("hiredis://redis:6379/1", "redis://redis:6379/1"),
            ("hiredis://redis:6379/", "redis://redis:6379"),
            ("hiredis://redis:6379", "redis://redis:6379"),
            ("redis://redis:6379/2/?key_prefix=x", "redis://redis:6379/2"),
            ("redis://redis:6379", "redis://redis:6379"),
            ("redis://:secret@redis:6379/3", "redis://:secret@redis:6379/3"),
            ("rediss://redis:6380/0", "rediss://redis:6380/0"),
        ]:
            with self.subTest(cache_url=cache_url):
                self.assertEqual(channels_redis_url(cache_url=cache_url), expected)

    def test_redis_url_overrides(self):
        self.assertEqual(
            channels_redis_url(
                redis_url="redis://other:6379/5", cache_url="hiredis://redis:6379/1"
            ),
            "redis://other:6379/5",
        )

    def test_neither(self):
        self.assertEqual(channels_redis_url(), "")


class ChannelLayerTimeoutTest(SimpleTestCase):
    def test_reads_outlast_the_blocking_pop(self):
        """redis-py 8 times out reads after 5 seconds by default, as long
        as channels_redis blocks on BZPOPMIN waiting for messages: every
        websocket without traffic died after 5 seconds (and the page
        reconnected, every 6 seconds)"""
        from channels_redis.core import RedisChannelLayer

        from biwak.redis_url import channel_layer

        config = channel_layer("redis://redis:6379/1")
        layer = RedisChannelLayer(**config["CONFIG"])
        pool = layer.create_pool(0)
        timeout = pool.connection_kwargs.get("socket_timeout")
        self.assertIsNotNone(timeout)
        self.assertGreater(timeout, layer.brpop_timeout)
        self.assertEqual(pool.connection_kwargs["host"], "redis")
        self.assertEqual(config["CONFIG"]["prefix"], "biwak")
