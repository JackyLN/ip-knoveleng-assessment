from app.services.rate_limit import SlidingWindowRateLimiter


def test_sliding_window_blocks_excess_and_recovers() -> None:
    now = [100.0]
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])

    assert limiter.allow()
    assert limiter.allow()
    assert not limiter.allow()

    now[0] = 110.1
    assert limiter.allow()
