"""Тесты веб-доступа: SSRF-защита и преобразование HTML.

Сеть не используется: адреса проверяются на уровне фильтра, а загрузка
страницы подменяется фейковым «опенером», который отдаёт заранее заданный HTML.
"""

from __future__ import annotations

import pytest

from tools import web


# ---------- Фильтр адресов (SSRF) ----------

@pytest.mark.parametrize("host,allowed", [
    ("127.0.0.1", False),
    ("10.1.2.3", False),
    ("192.168.0.10", False),
    ("172.16.5.5", False),
    ("169.254.1.1", False),          # link-local
    ("0.0.0.0", False),
    ("::1", False),
    ("localhost", False),
    ("my-host.local", False),
    ("8.8.8.8", True),
    ("93.184.216.34", True),
    ("", False),
])
def test_public_host_filter(host, allowed):
    ok, reason = web._is_public_host(host)

    assert ok is allowed
    if not allowed:
        assert reason


def test_unresolvable_host_is_rejected(monkeypatch):
    import socket

    def fail(host, port):
        raise socket.gaierror("нет такого хоста")

    monkeypatch.setattr(web.socket, "getaddrinfo", fail)

    ok, reason = web._is_public_host("example.invalid")

    assert ok is False
    assert "не разрешается" in reason


def test_host_resolving_to_private_address_is_rejected(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo",
                        lambda host, port: [(2, 1, 6, "", ("10.0.0.5", 0))])

    ok, reason = web._is_public_host("example.com")

    assert ok is False
    assert "приватный" in reason


# ---------- Защита в fetch_url ----------

def test_local_address_is_blocked(project):
    assert web.fetch_url("http://127.0.0.1:8000/admin").startswith(
        "ERROR: запрос отклонён")


def test_empty_url_is_rejected(project):
    assert web.fetch_url("   ").startswith("ERROR: пустой URL")


def test_web_can_be_disabled(project, apply_config):
    apply_config({"tools": {"web": {"enabled": False}}})

    assert web.fetch_url("https://example.com").startswith("ERROR: веб-доступ отключён")


# ---------- Преобразование HTML ----------

def test_html_to_text_drops_scripts_and_keeps_title():
    title, text = web._html_to_text(
        "<html><head><title>Документ</title><style>p{color:red}</style></head>"
        "<body><script>alert(1)</script><h1>Заголовок</h1><p>Текст</p></body></html>"
    )

    assert title == "Документ"
    assert "Заголовок" in text and "Текст" in text
    assert "alert(1)" not in text
    assert "color:red" not in text


def test_strip_tags_and_truncate():
    assert web._strip_tags("<b>жирный</b> &amp; <i>курсив</i>") == "жирный & курсив"

    long_text = "x" * 100
    truncated = web._truncate(long_text, 10)

    assert truncated.startswith("xxxxxxxxxx")
    assert "обрезано" in truncated
    assert web._truncate("коротко", 0) == "коротко"


# ---------- Загрузка страницы (без сети) ----------

class _FakeHeaders:
    def __init__(self, content_type="text/html", charset="utf-8"):
        self._content_type = content_type
        self._charset = charset

    def get_content_type(self):
        return self._content_type

    def get_content_charset(self):
        return self._charset


class _FakeResponse:
    def __init__(self, body, url, content_type="text/html", charset="utf-8"):
        self._body = body.encode(charset)
        self._url = url
        self.headers = _FakeHeaders(content_type, charset)

    def read(self, size=-1):
        return self._body if size < 0 else self._body[:size]

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    addheaders: list = []

    def __init__(self, response):
        self._response = response

    def open(self, url, timeout=None):
        return self._response


def _patch_transport(monkeypatch, body, content_type="text/html"):
    response = _FakeResponse(body, "https://example.com/page", content_type)
    monkeypatch.setattr(web.urllib.request, "build_opener",
                        lambda *handlers: _FakeOpener(response))
    monkeypatch.setattr(web.socket, "getaddrinfo",
                        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))])


def test_fetch_url_returns_readable_text(project, monkeypatch):
    _patch_transport(monkeypatch,
                     "<html><title>Статья</title><body><p>Привет, мир</p></body></html>")

    result = web.fetch_url("example.com/article")

    assert "Статья" in result
    assert "Привет, мир" in result
    assert "https://example.com/page" in result      # финальный URL после редиректов


def test_fetch_url_truncates_output(project, monkeypatch):
    _patch_transport(monkeypatch,
                     "<html><body>" + "<p>строка</p>" * 500 + "</body></html>")

    result = web.fetch_url("https://example.com", max_chars=300)

    assert len(result) < 700
    assert "обрезано" in result


def test_fetch_url_long_page_without_query_hints(project, monkeypatch):
    _patch_transport(monkeypatch,
                     "<html><body>" + "<p>длинный текст страницы</p>" * 2000
                     + "</body></html>")

    result = web.fetch_url("https://example.com")

    assert "страница длинная" in result
    assert 'query="ключевые слова"' in result
    assert len(result) < 12000
    saved = result.split("полный текст: ")[1].split(" — ")[0]
    assert (project / saved).is_file()


def test_fetch_url_excerpt_by_query(project, monkeypatch):
    body = "".join(
        f"<p>{'навигация меню' if i % 2 else 'используйте asyncio.gather для задач'}</p>"
        for i in range(2000)
    )
    _patch_transport(monkeypatch, f"<html><body>{body}</body></html>")

    result = web.fetch_url("https://example.com/doc", query="asyncio gather")

    assert "asyncio.gather" in result
    assert "фрагменты по словам" in result


def test_fetch_url_passes_plain_text_through(project, monkeypatch):
    _patch_transport(monkeypatch, "просто текст", content_type="text/plain")

    assert "просто текст" in web.fetch_url("https://example.com/file.txt")


# ---------- Ссылки DuckDuckGo ----------

# ---------- Разбор результатов поиска ----------

_DDG_HTML = (
    '<a rel="nofollow" class="result__a" '
    'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x">Заголовок A</a>'
    '<a class="result__snippet">Описание A</a>'
    '<a rel="nofollow" class="result__a" '
    'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fb&rut=y">Заголовок B</a>'
    '<a class="result__snippet">Описание B</a>'
)


def test_web_search_extracts_titles_urls_and_snippets(project, monkeypatch):
    monkeypatch.setattr(web, "_ddg_request", lambda endpoint, query, timeout: _DDG_HTML)

    result = web.web_search("python asyncio")

    assert "Заголовок A" in result and "https://example.com/a" in result
    assert "Описание A" in result
    assert "Заголовок B" in result
    assert result.count("\n1. ") == 1 and "\n2. " in result
    assert "DuckDuckGo" in result


def test_web_search_respects_num_results(project, monkeypatch):
    monkeypatch.setattr(web, "_ddg_request", lambda endpoint, query, timeout: _DDG_HTML)

    result = web.web_search("запрос", num_results=1)

    assert "Заголовок A" in result
    assert "Заголовок B" not in result


def test_web_search_reports_empty_page(project, monkeypatch):
    monkeypatch.setattr(web, "_ddg_request", lambda endpoint, query, timeout: "<html></html>")

    assert web.web_search("запрос").startswith("Совпадений не найдено")


def test_web_search_survives_endpoint_failure(project, monkeypatch):
    def boom(endpoint, query, timeout):
        raise OSError("сеть недоступна")

    monkeypatch.setattr(web, "_ddg_request", boom)

    result = web.web_search("запрос")

    assert "Совпадений не найдено" in result
    assert "сеть недоступна" in result          # причина показана пользователю


def test_web_search_validation(project, apply_config):
    assert web.web_search("   ").startswith("ERROR: пустой поисковый запрос")

    apply_config({"tools": {"web": {"enabled": False}}})
    assert web.web_search("запрос").startswith("ERROR: веб-доступ отключён")


def test_clean_ddg_url_unwraps_redirect():
    wrapped = ("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage"
               "&rut=abc")

    assert web._clean_ddg_url(wrapped) == "https://example.com/page"
    assert web._clean_ddg_url("https://example.com/direct") == "https://example.com/direct"
