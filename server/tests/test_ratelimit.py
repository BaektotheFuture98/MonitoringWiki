import pytest

from wiki_mcp.ratelimit import RateLimited, RateLimiter


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_limits_within_window():
    clock = Clock()
    limiter = RateLimiter(2, 60.0, clock=clock)
    limiter.check("a")
    limiter.check("a")
    with pytest.raises(RateLimited):
        limiter.check("a")
    limiter.check("b")


def test_window_slides():
    clock = Clock()
    limiter = RateLimiter(1, 60.0, clock=clock)
    limiter.check("a")
    clock.t = 60.0
    limiter.check("a")
