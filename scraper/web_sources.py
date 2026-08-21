from urllib.parse import urljoin, urlparse
from typing import List, Dict, Any, Optional, Tuple
import httpx
from bs4 import BeautifulSoup
from .models import RawItem


DATE_META_NAMES = {
    "article:published_time", "date", "datepublished", "publishdate",
    "pubdate", "last-modified", "article:modified_time",
}


def _extract_date(soup: BeautifulSoup):
    for meta in soup.find_all("meta"):
        name = (meta.get("property") or meta.get("name") or "").lower()
        if name in DATE_META_NAMES:
            value = meta.get("content")
            if value:
                return value
    t = soup.find("time")
    if t:
        return t.get("datetime") or t.get_text(" ", strip=True)
    return None


def _extract_title(soup: BeautifulSoup):
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    return soup.title.get_text(" ", strip=True) if soup.title else ""


def _extract_main_text(soup: BeautifulSoup):
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    candidates = []
    for selector in ["article", "main", ".entry-content", ".post-content", ".content", "#content"]:
        for node in soup.select(selector):
            txt = node.get_text(" ", strip=True)
            if len(txt) > 120:
                candidates.append(txt)
    if candidates:
        return max(candidates, key=len)
    body = soup.body
    return body.get_text(" ", strip=True) if body else soup.get_text(" ", strip=True)


def _relevant(text: str, keywords):
    low = (text or "").lower()
    return any(k.lower() in low for k in keywords)


def _source_icon(soup: BeautifulSoup, base_url: str):
    # Preferir logos explícitos antes que og:image (que suele ser foto de noticia).
    for selector in ['img[class*="logo"][src]', 'img[id*="logo"][src]', 'header img[src]']:
        node = soup.select_one(selector)
        if node and node.get("src"):
            return urljoin(base_url, node["src"])
    for rel_name in ["apple-touch-icon", "icon", "shortcut icon"]:
        for node in soup.find_all("link", href=True):
            rel = " ".join(node.get("rel") or []).lower()
            if rel_name in rel:
                return urljoin(base_url, node["href"])
    return None


def _article_images(soup: BeautifulSoup, base_url: str, source_icon_url: str | None = None):
    urls = []
    for prop in ["og:image", "twitter:image"]:
        node = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if node and node.get("content"):
            u = urljoin(base_url, node["content"])
            if u != source_icon_url and u not in urls:
                urls.append(u)
    for selector in ["article img[src]", "main img[src]", ".entry-content img[src]", ".post-content img[src]"]:
        for img in soup.select(selector):
            src = img.get("data-src") or img.get("src")
            if not src:
                continue
            u = urljoin(base_url, src)
            if u == source_icon_url or u in urls:
                continue
            urls.append(u)
            if len(urls) >= 12:
                return urls
    return urls[:12]


def _article_video(soup: BeautifulSoup, base_url: str, images: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    # Video oficial del sitio; en Facebook esta función no se usa.
    for prop in ["og:video:url", "og:video", "twitter:player"]:
        node = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if node and node.get("content"):
            u = urljoin(base_url, node["content"])
            return u, images[0] if images else None, "web_video"
    iframe = soup.select_one('iframe[src*="youtube.com"], iframe[src*="youtu.be"], iframe[src*="vimeo.com"], iframe[src*="facebook.com/plugins/video"]')
    if iframe and iframe.get("src"):
        return urljoin(base_url, iframe["src"]), images[0] if images else None, "web_embed"
    video = soup.find("video")
    if video:
        poster = urljoin(base_url, video.get("poster")) if video.get("poster") else (images[0] if images else None)
        # No obliga a que exista src; puede ser un reproductor JS.
        src = video.get("src")
        source_node = video.find("source", src=True)
        if not src and source_node:
            src = source_node.get("src")
        if src:
            return urljoin(base_url, src), poster, "web_video"
    return None, None, None


def _make_item(source, source_url, item_url, soup, text, source_icon_url):
    images = _article_images(soup, item_url, source_icon_url)
    video_url, video_thumb, video_type = _article_video(soup, item_url, images)
    return RawItem(
        source_id=source["id"], source_name=source["name"], source_url=source_url,
        item_url=item_url, text=text, title=_extract_title(soup), published_at=_extract_date(soup),
        region_hint=source.get("region"), city_hint=source.get("city"),
        source_class=source.get("source_class", "web_official"), tier=int(source.get("tier", 2)),
        source_icon_url=source_icon_url, image_urls=images,
        video_url=video_url, video_thumbnail_url=video_thumb, video_type=video_type,
    )


_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _get_with_retry(client: httpx.Client, url: str, timeout: float):
    """Un solo reintento para dos fallas puntuales que no tienen que ver con
    que el sitio esté caído: algunos WAF de sitios .gob.bo bloquean cualquier
    User-Agent que se identifique como bot sin importar qué tan educado sea
    (probamos primero con el nuestro, por transparencia), y algunos sitios
    lentos necesitan más margen del que conviene usar por default en el resto
    de las fuentes."""
    try:
        r = client.get(url, timeout=timeout)
        if r.status_code == 403:
            r = client.get(url, headers={"User-Agent": _BROWSER_USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        return r
    except httpx.TimeoutException:
        return client.get(url, timeout=timeout * 2)


def scrape_generic_web(source: Dict[str, Any], settings: Dict[str, Any]) -> List[RawItem]:
    url = source["url"]
    timeout = settings.get("request_timeout_seconds", 25)
    max_items = int(settings.get("max_items_per_source", 30))
    keywords = settings.get("keywords", [])
    headers = {
        "User-Agent": settings.get("user_agent"),
        "Accept-Language": "es-BO,es;q=0.9,en;q=0.6",
    }
    items: List[RawItem] = []

    with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout) as client:
        r = _get_with_retry(client, url, timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        source_icon_url = source.get("icon_url") or _source_icon(soup, str(r.url))

        base_text = _extract_main_text(BeautifulSoup(r.text, "html.parser"))
        if _relevant(base_text, keywords):
            items.append(_make_item(source, url, str(r.url), soup, base_text, source_icon_url))

        if not source.get("follow_links", False):
            return items[:max_items]

        host = urlparse(str(r.url)).netloc
        links, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = urljoin(str(r.url), a["href"])
            p = urlparse(href)
            if p.scheme not in {"http", "https"} or p.netloc != host:
                continue
            probe = f"{a.get_text(' ', strip=True)} {href}"
            if not _relevant(probe, keywords):
                continue
            clean = href.split("#")[0]
            if clean not in seen:
                seen.add(clean)
                links.append(clean)

        for link in links[:max_items]:
            try:
                rr = client.get(link)
                if rr.status_code >= 400:
                    continue
                ss = BeautifulSoup(rr.text, "html.parser")
                txt = _extract_main_text(BeautifulSoup(rr.text, "html.parser"))
                if not _relevant(txt, keywords):
                    continue
                items.append(_make_item(source, url, str(rr.url), ss, txt, source_icon_url))
            except Exception:
                continue

    dedup = {x.item_url: x for x in items}
    return list(dedup.values())[:max_items]
