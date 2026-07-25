import httpx

from communications_tax_data.collectors.base import get_with_retry


def test_get_with_retry_retries_transient_status(monkeypatch):
    statuses = iter([429, 200])
    sleeps = []

    def handler(request):
        return httpx.Response(next(statuses), request=request)

    monkeypatch.setattr("communications_tax_data.collectors.base.time.sleep", sleeps.append)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = get_with_retry(client, "https://example.test/source")

    assert response.status_code == 200
    assert sleeps == [1.0]


def test_get_with_retry_does_not_retry_permanent_error(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "communications_tax_data.collectors.base.time.sleep",
        lambda _: raise_unexpected_sleep(),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = get_with_retry(client, "https://example.test/missing")

    assert response.status_code == 404
    assert calls == 1


def raise_unexpected_sleep():
    raise AssertionError("permanent errors must not be retried")
