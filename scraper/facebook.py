import asyncio
import random
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin
import re

from .models import RawItem


class FacebookBlockedError(RuntimeError):
    """Facebook mostró una pantalla de bloqueo/login en vez del contenido público."""


VIAL_HINTS = [
    "bloqueo", "bloqueada", "bloqueado", "desbloqueo", "cierre", "cerrada", "cerrado",
    "accidente", "hecho de tránsito", "hecho de transito", "siniestro vial", "choque",
    "colisión", "colision", "atropello", "vuelco", "embarrancamiento", "derrumbe",
    "deslizamiento", "mazamorra", "inundación", "inundacion", "anegamiento",
    "tránsito vehicular", "transito vehicular", "tráfico", "trafico", "congestión",
    "congestion", "desvío", "desvio", "ruta alternativa", "vía alternativa",
    "via alternativa", "transitabilidad", "carretera", "avenida", "doble vía", "doble via",
    "ruta", "puente", "semáforo", "semaforo", "circulación vehicular", "circulacion vehicular",
    "paso vehicular", "paso restringido", "media calzada", "un solo carril", "habilitada",
    "habilitado", "restricción", "restriccion", "precaución", "precaucion",
    "control vehicular", "operativo de tránsito", "operativo de transito", "alcoholemia",
    "salida de buses", "salidas suspendidas", "terminal de buses", "punto de bloqueo",
]

UI_NOISE = {
    "me gusta", "comentar", "compartir", "enviar", "seguir", "seguidores", "reacciones",
    "todos", "más relevantes", "mas relevantes", "ver más", "ver mas", "facebook",
    "reproducir", "pausar", "silenciar", "activar sonido", "crear cuenta", "iniciar sesión",
}


def _clean_img(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return None
    low = url.lower()
    if any(x in low for x in ["emoji.php", "rsrc.php", "static.xx.fbcdn.net", "/images/emoji"]):
        return None
    return url


def _clean_fb_url(href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith("/"):
        href = urljoin("https://www.facebook.com", href)
    if not href.startswith(("http://", "https://")):
        return None
    # quitar tracking común pero conservar ids relevantes
    href = href.replace("https://m.facebook.com/", "https://www.facebook.com/")
    return href


def _looks_vial(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in VIAL_HINTS)


def _clean_text_parts(parts: List[str], source_name: str = "") -> str:
    out, seen = [], set()
    src = (source_name or "").strip().lower()
    for raw in parts:
        t = re.sub(r"\s+", " ", (raw or "")).strip()
        if not t:
            continue
        low = t.lower().strip(" .:-")
        if low in UI_NOISE:
            continue
        if src and low == src:
            continue
        # Quitar contadores / botones muy cortos
        if len(t) <= 3 and not any(ch.isalpha() for ch in t):
            continue
        if re.fullmatch(r"\d+[KkMm]?", t):
            continue
        if low not in seen:
            seen.add(low)
            out.append(t)
    return "\n".join(out).strip()


async def _get_source_icon(page, source: Dict[str, Any]) -> str | None:
    explicit = source.get("icon_url")
    if explicit:
        return explicit

    name = source.get("name", "").split(" - ")[0].strip()
    candidates = []

    if name:
        try:
            loc = page.locator("img[src]")
            n = min(await loc.count(), 180)
            for i in range(n):
                img = loc.nth(i)
                alt = (await img.get_attribute("alt")) or ""
                if name.lower() not in alt.lower():
                    continue
                src = _clean_img(await img.get_attribute("src"))
                if not src:
                    continue
                try:
                    size = await img.evaluate("(e)=>({w:e.naturalWidth||e.width||0,h:e.naturalHeight||e.height||0})")
                    area = int(size.get("w", 0)) * int(size.get("h", 0))
                except Exception:
                    area = 0
                candidates.append((area, src))
        except Exception:
            pass

    try:
        meta = page.locator('meta[property="og:image"]')
        if await meta.count():
            src = _clean_img(await meta.first.get_attribute("content"))
            if src:
                candidates.append((1, src))
    except Exception:
        pass

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


async def _article_text(node, source_name: str) -> str:
    """Prioriza el texto real del post y evita botones/contadores del article completo."""
    parts = []

    selectors = [
        'div[dir="auto"]',
        '[data-ad-preview="message"]',
        '[data-ad-comet-preview="message"]',
        'span[dir="auto"]',
    ]
    for selector in selectors:
        try:
            loc = node.locator(selector)
            n = min(await loc.count(), 80)
            for i in range(n):
                try:
                    txt = (await loc.nth(i).inner_text(timeout=1200)).strip()
                except Exception:
                    continue
                if txt:
                    parts.append(txt)
        except Exception:
            pass

    cleaned = _clean_text_parts(parts, source_name)
    if len(cleaned) >= 30:
        return cleaned

    try:
        fallback = (await node.inner_text(timeout=3500)).strip()
    except Exception:
        fallback = ""
    return _clean_text_parts(fallback.splitlines(), source_name)


async def _article_images(node, source_icon_url: str | None) -> List[str]:
    urls = []
    try:
        imgs = node.locator("img[src]")
        n = min(await imgs.count(), 80)
        for i in range(n):
            img = imgs.nth(i)
            src = _clean_img(await img.get_attribute("src"))
            if not src or src == source_icon_url:
                continue
            try:
                size = await img.evaluate("(e)=>({w:e.naturalWidth||e.width||0,h:e.naturalHeight||e.height||0})")
                w, h = int(size.get("w", 0)), int(size.get("h", 0))
            except Exception:
                w = h = 0
            if w and h and (w < 220 or h < 140):
                continue
            alt = ((await img.get_attribute("alt")) or "").lower()
            if any(x in alt for x in ["emoji", "profile picture", "foto del perfil", "reacción", "reaction"]):
                continue
            if src not in urls:
                urls.append(src)
    except Exception:
        pass
    return urls[:12]


async def _article_video(node, item_url: str, image_urls: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Conserva la URL pública del post/reel/video; no extrae streams MP4 internos."""
    video_url = None
    video_type = None
    thumb = None

    try:
        links = node.locator('a[href*="/videos/"], a[href*="/reel/"], a[href*="/watch/"], a[href*="watch?v="]')
        n = min(await links.count(), 20)
        for i in range(n):
            href = _clean_fb_url(await links.nth(i).get_attribute("href"))
            if not href:
                continue
            video_url = href
            low = href.lower()
            video_type = "facebook_reel" if "/reel/" in low else "facebook_video"
            break
    except Exception:
        pass

    if not video_url:
        low = (item_url or "").lower()
        if "/videos/" in low or "/reel/" in low or "watch?v=" in low:
            video_url = item_url
            video_type = "facebook_reel" if "/reel/" in low else "facebook_video"

    if video_url:
        try:
            vids = node.locator("video")
            if await vids.count():
                thumb = _clean_img(await vids.first.get_attribute("poster"))
        except Exception:
            pass
        if not thumb and image_urls:
            thumb = image_urls[0]

    return video_url, thumb, video_type


async def _published_time(node) -> Optional[str]:
    try:
        timeish = node.locator("abbr, time")
        if await timeish.count():
            return (
                await timeish.first.get_attribute("datetime")
                or await timeish.first.get_attribute("title")
                or (await timeish.first.inner_text(timeout=1000)).strip()
            )
    except Exception:
        pass
    try:
        anchors = node.locator("a[aria-label], a[title]")
        n = min(await anchors.count(), 40)
        for i in range(n):
            a = anchors.nth(i)
            candidate = (await a.get_attribute("aria-label")) or (await a.get_attribute("title"))
            if candidate and any(x in candidate.lower() for x in [
                "hora", "ayer", "lunes", "martes", "miércoles", "miercoles", "jueves",
                "viernes", "sábado", "sabado", "domingo", "ago", "jul", "jun", "2026"
            ]):
                return candidate.strip()
    except Exception:
        pass
    return None


async def _enrich_public_post(context, item: RawItem, timeout_ms: int = 25000) -> RawItem:
    """Abre el enlace público del post y usa metadatos/DOM para recuperar mejor caption e imagen.
    No inicia sesión ni evade restricciones.
    """
    if not item.item_url or item.item_url == item.source_url:
        return item
    page = await context.new_page()
    try:
        await page.goto(item.item_url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(1200)

        desc_parts = []
        for selector, attr in [
            ('meta[property="og:description"]', "content"),
            ('meta[name="description"]', "content"),
        ]:
            try:
                loc = page.locator(selector)
                if await loc.count():
                    val = (await loc.first.get_attribute(attr)) or ""
                    if val:
                        desc_parts.append(val)
            except Exception:
                pass

        # Algunos posts exponen el mensaje en dir=auto aunque la página principal no.
        try:
            loc = page.locator('div[dir="auto"]')
            n = min(await loc.count(), 80)
            dom_parts = []
            for i in range(n):
                try:
                    txt = (await loc.nth(i).inner_text(timeout=700)).strip()
                except Exception:
                    continue
                if txt:
                    dom_parts.append(txt)
            dom_text = _clean_text_parts(dom_parts, item.source_name)
            if dom_text:
                desc_parts.append(dom_text)
        except Exception:
            pass

        richer = _clean_text_parts(desc_parts, item.source_name)
        if len(richer) > len(item.text) or (_looks_vial(richer) and not _looks_vial(item.text)):
            item.text = richer

        # og:image suele ser una buena imagen principal del post.
        try:
            og = page.locator('meta[property="og:image"]')
            if await og.count():
                img = _clean_img(await og.first.get_attribute("content"))
                if img and img != item.source_icon_url and img not in item.image_urls:
                    item.image_urls.insert(0, img)
                    item.image_urls = item.image_urls[:12]
        except Exception:
            pass

        # Mantener el enlace público si es video/reel.
        low = item.item_url.lower()
        if not item.video_url and ("/videos/" in low or "/reel/" in low or "watch?v=" in low):
            item.video_url = item.item_url
            item.video_type = "facebook_reel" if "/reel/" in low else "facebook_video"
            if not item.video_thumbnail_url and item.image_urls:
                item.video_thumbnail_url = item.image_urls[0]

        try:
            title_meta = page.locator('meta[property="og:title"]')
            if await title_meta.count():
                title = (await title_meta.first.get_attribute("content")) or ""
                if title and len(title) > 8:
                    item.title = title
        except Exception:
            pass
    except Exception:
        pass
    finally:
        await page.close()
    return item


async def _scrape_facebook_with_context(source: Dict[str, Any], settings: Dict[str, Any], context) -> List[RawItem]:
    """Scrapea una fuente usando un contexto ya creado.
    No inicia sesión ni evade bloqueos de Facebook.
    """
    url = source["url"]
    wait_s = float(settings.get("facebook_wait_seconds", 2.5))
    max_items = int(settings.get("max_items_per_source", 18))
    scroll_rounds = int(settings.get("facebook_scroll_rounds", 2))
    enrich = bool(settings.get("facebook_enrich_posts", True))
    enrich_limit = int(settings.get("facebook_enrich_limit_per_source", 2))
    enrich_timeout = int(settings.get("facebook_enrich_timeout_ms", 12000))

    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(int(wait_s * 1000))

        source_icon_url = await _get_source_icon(page, source)

        # Modo rápido: pocos scrolls, solo hasta conseguir suficientes posts recientes.
        for _ in range(scroll_rounds):
            try:
                count = await page.locator('[role="article"]').count()
                if count >= max_items:
                    break
                await page.mouse.wheel(0, 2200)
                await page.wait_for_timeout(450)
            except Exception:
                break

        raw: List[RawItem] = []
        articles = page.locator('[role="article"]')
        count = min(await articles.count(), max_items)

        for i in range(count):
            node = articles.nth(i)
            txt = await _article_text(node, source.get("name", ""))
            if len(txt) < 20:
                continue

            item_url = url
            try:
                links = node.locator(
                    'a[href*="/posts/"], a[href*="/videos/"], a[href*="/reel/"], '
                    'a[href*="story_fbid="], a[href*="/permalink/"], a[href*="watch?v="]'
                )
                nlinks = min(await links.count(), 20)
                for j in range(nlinks):
                    href = _clean_fb_url(await links.nth(j).get_attribute("href"))
                    if href and any(k in href.lower() for k in [
                        "/posts/", "/videos/", "/reel/", "story_fbid=", "/permalink/", "watch?v="
                    ]):
                        item_url = href
                        break
            except Exception:
                pass

            published = await _published_time(node)
            image_urls = await _article_images(node, source_icon_url)
            video_url, video_thumb, video_type = await _article_video(node, item_url, image_urls)

            raw.append(RawItem(
                source_id=source["id"],
                source_name=source["name"],
                source_url=url,
                item_url=item_url,
                text=txt,
                title="",
                published_at=published,
                region_hint=source.get("region"),
                city_hint=source.get("city"),
                source_class=source.get("source_class", "media"),
                tier=int(source.get("tier", 3)),
                source_icon_url=source_icon_url,
                image_urls=image_urls,
                video_url=video_url,
                video_thumbnail_url=video_thumb,
                video_type=video_type,
            ))

        if not raw:
            # Sin artículos reales en el feed: recién ahora vale la pena
            # revisar si es porque Facebook bloqueó/ocultó el contenido para
            # esta sesión, en vez de confundirlo con una fuente que hoy no
            # tiene posts nuevos. Chequear esto ANTES de intentar leer los
            # artículos daba falsos positivos: Facebook incluye un formulario
            # de login en el DOM de cualquier página pública para visitantes
            # sin sesión, incluso cuando el feed real sí cargó bien arriba.
            body_text = await page.locator("body").inner_text(timeout=7000)
            low = body_text.lower()
            if (
                "temporarily blocked" in low
                or "you’re temporarily blocked" in low
                or "temporalmente bloqueado" in low
                or "correo electrónico o número de celular" in low
                or "correo electronico o numero de celular" in low
                or "olvidaste tu contraseña" in low
                or "email or phone number" in low
                or "forgotten password" in low
            ):
                preview = re.sub(r"\s+", " ", body_text).strip()[:220]
                # Con el mismo muro de login, Facebook no distingue "está
                # bloqueada para esta sesión" de "esta página ya no existe":
                # el título y la URL final (tras redirects) sí cambian entre
                # los dos casos y ayudan a diferenciarlos a simple vista.
                page_title = await page.title()
                raise FacebookBlockedError(
                    f"Facebook bloqueó/ocultó el contenido público para esta ejecución. "
                    f"Título de página: {page_title!r} | URL final: {page.url!r} | "
                    f"Vista previa de la página: {preview!r}"
                )

            title = await page.title()
            desc = ""
            og_image = None
            try:
                el = page.locator('meta[property="og:description"]')
                if await el.count():
                    desc = (await el.first.get_attribute("content")) or ""
            except Exception:
                pass
            try:
                el = page.locator('meta[property="og:image"]')
                if await el.count():
                    og_image = _clean_img(await el.first.get_attribute("content"))
            except Exception:
                pass

            fallback_text = _clean_text_parts(
                [desc, body_text[:5000]], source.get("name", "")
            )
            if len(fallback_text) >= 40:
                images = [og_image] if og_image and og_image != source_icon_url else []
                raw.append(RawItem(
                    source_id=source["id"],
                    source_name=source["name"],
                    source_url=url,
                    item_url=url,
                    text=fallback_text,
                    title=title,
                    published_at=None,
                    region_hint=source.get("region"),
                    city_hint=source.get("city"),
                    source_class=source.get("source_class", "media"),
                    tier=int(source.get("tier", 3)),
                    source_icon_url=source_icon_url,
                    image_urls=images,
                ))

        # Enriquecimiento selectivo: solo los candidatos que realmente lo necesitan.
        if enrich and raw:
            used = 0
            for i, item in enumerate(raw):
                needs = (
                    (not _looks_vial(item.text))
                    or len(item.text) < 120
                    or (item.video_url and not item.image_urls)
                )
                if needs and used < enrich_limit and item.item_url != source["url"]:
                    raw[i] = await _enrich_public_post(
                        context, item, timeout_ms=enrich_timeout
                    )
                    used += 1

        seen, out = set(), []
        for x in raw:
            key = (x.item_url, x.text[:350])
            if key not in seen:
                seen.add(key)
                out.append(x)
        return out[:max_items]
    finally:
        await page.close()


async def scrape_facebook_sources(
    sources: List[Dict[str, Any]],
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Scrapea las páginas de Facebook una por una, con pausa entre cada una,
    reutilizando un único contexto de navegador (como una persona real
    navegando de página en página, no pestañas simultáneas).

    Sin concurrencia y sin User-Agent de bot: ambas cosas son señales fuertes
    de tráfico automatizado para Facebook. Apenas una fuente devuelve la
    pantalla de bloqueo/login, se corta el resto de la corrida en vez de
    seguir insistiendo con las fuentes que quedan — así no se arrastra el
    bloqueo a más fuentes de las necesarias.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright no está instalado. Ejecuta: playwright install chromium"
        ) from exc

    delay_seconds = max(5.0, float(settings.get("facebook_delay_seconds", 8.0)))

    results: Dict[str, Any] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
            ],
        )
        # Un solo contexto para toda la corrida: sin user_agent propio (se usa
        # el de Chromium real por defecto) y con las cookies/sesión persistiendo
        # de una fuente a la siguiente, como en una navegación normal.
        # El tamaño exacto de ventana es una de las señales más baratas para
        # agrupar sesiones automatizadas: si todos los runners reportan
        # 1280x900 clavado, los N jobs paralelos se leen como una sola flota.
        # Variarlo unos píxeles no oculta nada, solo evita que coincidan.
        context = await browser.new_context(
            locale="es-BO",
            timezone_id=settings.get("timezone", "America/La_Paz"),
            viewport={
                "width": random.choice([1280, 1366, 1440, 1512, 1600]),
                "height": random.choice([800, 864, 900, 960]),
            },
            service_workers="block",
        )

        async def route_handler(route):
            rt = route.request.resource_type
            url = route.request.url.lower()
            if rt in {"font", "media"}:
                await route.abort()
                return
            if any(x in url for x in [
                "doubleclick.net", "google-analytics.com", "googletagmanager.com"
            ]):
                await route.abort()
                return
            await route.continue_()

        await context.route("**/*", route_handler)

        # Un solo bloqueo aislado puede ser mala suerte con la IP que le tocó
        # al runner en esta corrida puntual, no necesariamente algo que
        # nuestro propio patrón de tráfico provocó (puede pasar incluso en la
        # primerísima solicitud, antes de haber hecho ninguna otra). Por eso
        # se reintenta esa misma fuente una vez, con una pausa larga, antes de
        # rendirse y saltar el resto de la corrida de Facebook.
        block_retry_delay = max(20.0, float(settings.get("facebook_block_retry_seconds", 30.0)))

        blocked = False
        for i, source in enumerate(sources):
            if blocked:
                results[source["id"]] = {
                    "items": [],
                    "error": "Omitida: Facebook bloqueó otra fuente antes en esta misma corrida.",
                }
                continue

            last_error = None
            for attempt in range(2):
                try:
                    items = await _scrape_facebook_with_context(source, settings, context)
                    results[source["id"]] = {"items": items, "error": None}
                    last_error = None
                    break
                except FacebookBlockedError as exc:
                    last_error = exc
                    if attempt == 0:
                        await asyncio.sleep(block_retry_delay)
                except Exception as exc:
                    results[source["id"]] = {"items": [], "error": str(exc)}
                    last_error = None
                    break

            if isinstance(last_error, FacebookBlockedError):
                results[source["id"]] = {"items": [], "error": str(last_error)}
                blocked = True

            if not blocked and i < len(sources) - 1:
                # Pausa con algo de ruido: una espera exacta de 8.000s entre
                # páginas, repetida igual en todos los jobs, es más delatora
                # que la pausa en sí.
                await asyncio.sleep(delay_seconds * random.uniform(0.8, 1.45))

        await context.close()
        await browser.close()

    return results


async def scrape_facebook_public(source: Dict[str, Any], settings: Dict[str, Any]) -> List[RawItem]:
    """Compatibilidad para ejecutar una sola fuente."""
    result = await scrape_facebook_sources([source], settings)
    row = result[source["id"]]
    if row["error"]:
        raise RuntimeError(row["error"])
    return row["items"]
