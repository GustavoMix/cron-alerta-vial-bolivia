import httpx
from scraper.web_sources import _BROWSER_USER_AGENT, _get_with_retry


def test_403_reintenta_una_vez_con_user_agent_de_navegador():
    """Algunos WAF de sitios .gob.bo bloquean cualquier User-Agent que se
    identifique como bot, aunque sea uno educado. El primer intento usa
    nuestro UA real por transparencia; solo ante un 403 se reintenta una vez
    con un UA de navegador estándar."""
    intentos = []

    def handler(request):
        intentos.append(request.headers.get("user-agent"))
        if len(intentos) == 1:
            return httpx.Response(403)
        return httpx.Response(200, text="ok")

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": "BoliviaVialBot/2.0 (+public-road-information; polite crawler)"},
    )
    r = _get_with_retry(client, "https://simat.cochabamba.bo/", timeout=10)

    assert r.status_code == 200
    assert len(intentos) == 2
    assert "BoliviaVialBot" in intentos[0]
    assert intentos[1] == _BROWSER_USER_AGENT


def test_200_no_reintenta():
    intentos = []

    def handler(request):
        intentos.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = _get_with_retry(client, "https://example.com/", timeout=10)

    assert r.status_code == 200
    assert len(intentos) == 1


def test_timeout_reintenta_una_vez_con_mas_margen():
    intentos = []

    def handler(request):
        intentos.append(request)
        if len(intentos) == 1:
            raise httpx.TimeoutException("timed out", request=request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = _get_with_retry(client, "https://amun.lapaz.bo/", timeout=10)

    assert r.status_code == 200
    assert len(intentos) == 2


def test_404_no_se_confunde_con_bloqueo_waf_no_reintenta():
    intentos = []

    def handler(request):
        intentos.append(request)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        _get_with_retry(client, "https://example.com/borrado", timeout=10)
        assert False, "debía lanzar HTTPStatusError"
    except httpx.HTTPStatusError:
        pass
    assert len(intentos) == 1
