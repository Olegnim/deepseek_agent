"""Веб-доступ для агента: чтение страниц и поиск без API-ключей.

Используется только стандартная библиотека (urllib + html.parser),
поэтому модуль не добавляет зависимостей.

- fetch_url(url)   — скачивает страницу и отдаёт её текстом (HTML -> текст);
- web_search(query) — поиск через DuckDuckGo (HTML/Lite-эндпоинты).

Включение и лимиты — в agent.config.json (секция tools.web):
    "tools": {"web": {"enabled": true, "timeout": 20,
                      "max_chars": 20000, "results": 5}}

Безопасность: запросы к приватным/локальным адресам (127.0.0.1, 10.x,
192.168.x, link-local, *.local) блокируются — и напрямую, и через редиректы,
чтобы модель не дёргала внутренние сервисы (SSRF).
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import config
from . import digest

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

MAX_FETCH_BYTES = 1_000_000        # максимум скачанного тела, байт
_DDG_HTML = "https://html.duckduckgo.com/html/"
_DDG_LITE = "https://lite.duckduckgo.com/lite/"

_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5",
    "h6", "section", "article", "header", "footer", "pre", "blockquote",
    "ul", "ol", "table", "form", "figure", "aside", "main", "nav",
}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "template"}


# ---------- Вспомогательные ----------

def _web_cfg() -> dict:
    return config.web_settings()


def _is_public_host(host: str | None) -> tuple[bool, str]:
    """Проверяет, что хост публичный (не localhost и не приватная сеть)."""
    if not host:
        return False, "не указан хост"
    host = host.strip().strip("[]").lower()
    if host in {"localhost", "locahost"} or host.endswith(".local"):
        return False, f"{host} — локальный адрес"

    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            return False, f"{host} — приватный/специальный IP"
        return True, ""
    except ValueError:
        pass  # это доменное имя — разрешаем его в адреса

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        return False, f"{host} не разрешается ({e})"

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            continue
        if not ip.is_global:
            return False, f"{host} -> {addr} (приватный адрес)"
    return True, ""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Не даёт редиректу увести запрос на приватный адрес."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname
        ok, reason = _is_public_host(host)
        if not ok:
            raise urllib.error.URLError(f"редирект отклонён: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _TextExtractor(HTMLParser):
    """HTML -> читаемый текст: убирает скрипты/стили, режет по блокам."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> tuple[str, str]:
    """Возвращает (title, текст)."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass  # кривая разметка — отдадим то, что успели разобрать

    raw = "".join(parser.parts)
    raw = raw.replace("\xa0", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r" *\n *", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return parser.title.strip(), raw.strip()


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    text = re.sub(r"\s+", " ", text)
    return text.replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"').strip()


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return (text[:limit].rstrip()
            + f"\n\n[... обрезано: {len(text)} символов, показано {limit}. "
              "Запроси конкретный фрагмент или другой URL.]")


# ---------- fetch_url ----------

def fetch_url(url: str, max_chars: int = 0, query: str = "") -> str:
    """Скачивает URL и возвращает текст страницы (HTML -> plain text).

    max_chars — ограничить вывод (0 = лимит из конфига tools.web.max_chars).
    query — что искать на странице: вместо начала отдаются релевантные абзацы
    (для доков и больших страниц это в разы короче и точнее). Полный текст
    сохраняется в .agent-cache/output, его можно читать через read_range.
    """
    cfg = _web_cfg()
    if not cfg.get("enabled", True):
        return "ERROR: веб-доступ отключён (tools.web.enabled = false)."

    url = (url or "").strip()
    if not url:
        return "ERROR: пустой URL."
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")

    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "ERROR: поддерживаются только http/https."
    ok, reason = _is_public_host(parts.hostname)
    if not ok:
        return f"ERROR: запрос отклонён (SSRF-защита): {reason}"

    timeout = float(cfg.get("timeout") or 20)
    limit = int(max_chars) if max_chars else int(cfg.get("max_chars") or 20000)

    opener = urllib.request.build_opener(_SafeRedirectHandler)
    opener.addheaders = [("User-Agent", USER_AGENT),
                         ("Accept-Language", "ru,en;q=0.9")]

    try:
        with opener.open(url, timeout=timeout) as resp:
            final_url = resp.geturl()
            ctype = (resp.headers.get_content_type() or "").lower()
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read(MAX_FETCH_BYTES + 1)
    except urllib.error.HTTPError as e:
        return f"ERROR: HTTP {e.code} {e.reason} — {url}"
    except urllib.error.URLError as e:
        return f"ERROR: не удалось загрузить {url}: {e.reason}"
    except (socket.timeout, TimeoutError):
        return f"ERROR: таймаут {timeout:g} c при загрузке {url}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    cut = len(raw) > MAX_FETCH_BYTES
    body = raw[:MAX_FETCH_BYTES].decode(charset, errors="replace")

    if "html" in ctype or "<html" in body[:2000].lower():
        title, text = _html_to_text(body)
        head = f"{title}\n{final_url}\n\n" if title else f"{final_url}\n\n"
        text = head + text
    else:
        text = f"{final_url}\n\n{body}"

    if cut:
        text += f"\n\n[... страница обрезана: скачано {MAX_FETCH_BYTES} байт]"
    # Явный лимит от модели — старое поведение (просто обрезка).
    if max_chars:
        return _truncate(text, limit)
    # Бюджет контекста: не больше tools.output.max_chars на результат.
    out_budget = min(limit, int(config.output_settings().get("max_chars") or limit))
    # Задан вопрос — отдаём абзацы, где встречаются слова запроса.
    if query.strip():
        return digest.excerpt(text, digest.keywords_from(query),
                              max_chars=out_budget)
    if len(text) <= out_budget:
        return text
    # Длинная страница без вопроса: показываем начало (не рванную нарезку
    # строк — в тексте страницы много навигации) и подсказываем query.
    saved = digest.save_output("fetch_url", text)
    tail = (f"\n\n[... страница длинная: показано начало ({out_budget} из "
            f"{len(text)} символов). Нужны конкретные места — повтори "
            f"fetch_url(url, query=\"ключевые слова\")")
    if saved:
        tail += f"; полный текст: {saved} — читай read_range(...) точечно"
    tail += "]"
    return text[:out_budget].rstrip() + tail


# ---------- web_search (DuckDuckGo, без API-ключа) ----------

_LINK_RE = re.compile(
    r'<a[^>]+class="[^"]*(?:result__a|result-link)[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.S | re.I,
)
_SNIPPET_RE = re.compile(
    r'class="[^"]*(?:result__snippet|result-snippet)[^"]*"[^>]*>(.*?)</(?:a|td|div)>',
    re.S | re.I,
)


def _clean_ddg_url(url: str) -> str:
    """Разворачивает редирект DuckDuckGo (…/l/?uddg=<encoded>)."""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if "duckduckgo.com/l/" in url or "/l/?uddg=" in url:
        query = urllib.parse.urlsplit(url).query
        target = urllib.parse.parse_qs(query).get("uddg", [""])[0]
        if target:
            return urllib.parse.unquote(target)
    return url


def _ddg_request(endpoint: str, query: str, timeout: float) -> str:
    data = urllib.parse.urlencode({"q": query, "kl": "ru-ru"}).encode()
    req = urllib.request.Request(endpoint, data=data, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(MAX_FETCH_BYTES).decode("utf-8", errors="replace")


def web_search(query: str, num_results: int = 0) -> str:
    """Ищет в интернете через DuckDuckGo и возвращает список результатов."""
    cfg = _web_cfg()
    if not cfg.get("enabled", True):
        return "ERROR: веб-доступ отключён (tools.web.enabled = false)."

    query = (query or "").strip()
    if not query:
        return "ERROR: пустой поисковый запрос."

    limit = int(num_results) if num_results else int(cfg.get("results") or 5)
    limit = max(1, min(limit, 20))
    timeout = float(cfg.get("timeout") or 20)

    html = ""
    last_error = ""
    for endpoint in (_DDG_HTML, _DDG_LITE):
        try:
            html = _ddg_request(endpoint, query, timeout)
        except urllib.error.HTTPError as e:
            html = ""
            last_error = f"HTTP {e.code} {e.reason}"
            continue
        except Exception as e:
            html = ""
            last_error = f"{type(e).__name__}: {e}"
            continue
        if _LINK_RE.search(html):
            break

    links = _LINK_RE.findall(html)
    if not links:
        hint = f"\nПричина: {last_error}" if last_error else ""
        return (f"Совпадений не найдено по запросу: {query}{hint}\n"
                "DuckDuckGo мог ограничить частоту запросов — попробуй позже "
                "или открой конкретный URL через fetch_url.")

    snippets = [_strip_tags(s) for s in _SNIPPET_RE.findall(html)]
    out: list[str] = [f"Результаты по запросу: {query}"]
    seen: set[str] = set()

    for i, (href, title_html) in enumerate(links):
        url = _clean_ddg_url(href)
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        title = _strip_tags(title_html) or "(без заголовка)"
        snippet = ""
        if i < len(snippets):
            snippet = snippets[i]
        block = f"\n{len(seen)}. {title}\n   {url}"
        if snippet:
            block += f"\n   {snippet}"
        out.append(block)
        if len(seen) >= limit:
            break

    if len(out) == 1:
        return f"Совпадений не найдено по запросу: {query}"
    out.append("\n(источник: DuckDuckGo; страницы читай через fetch_url)")
    return "\n".join(out)
