import re
import unicodedata
from dateutil import parser as dateparser

STOP = {
    "de","la","el","los","las","en","a","y","del","por","para","un","una","se",
    "con","que","al","su","sus","es","esta","este","desde","hasta","sobre","tras",
    "bolivia","departamento","ciudad","informo","informó","reporta","reportó"
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\s\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(alert) -> set[str]:
    text = " ".join([
        alert.title or "", alert.description[:900] if alert.description else "",
        " ".join(alert.roads or []), " ".join(alert.places or []),
        " ".join(alert.kilometer_mentions or []),
    ])
    return {x for x in _norm(text).split() if len(x) >= 4 and x not in STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _time_hours(a, b):
    if not a or not b:
        return None
    try:
        da, db = dateparser.parse(a), dateparser.parse(b)
        if da.tzinfo is None or db.tzinfo is None:
            return None
        return abs((da - db).total_seconds()) / 3600.0
    except Exception:
        return None


def _same_place(a, b):
    if a.department and b.department and a.department != b.department:
        return False
    if a.city and b.city and a.city != b.city:
        ra = {_norm(x) for x in (a.roads or [])}
        rb = {_norm(x) for x in (b.roads or [])}
        if not (ra & rb):
            return False
    return True


def _overlap(vals_a, vals_b):
    A = {_norm(x) for x in (vals_a or []) if x}
    B = {_norm(x) for x in (vals_b or []) if x}
    return bool(A & B)


def same_incident(a, b, hours=24, threshold=0.24):
    if a.event_type != b.event_type:
        compatible = {a.event_type, b.event_type} <= {"bloqueo", "cierre_vial", "habilitacion"}
        if not compatible:
            return False
    if not _same_place(a, b):
        return False
    delta = _time_hours(a.published_at, b.published_at)
    if delta is not None and delta > hours:
        return False

    sim = _jaccard(_tokens(a), _tokens(b))
    strong_place = (
        _overlap(a.roads, b.roads) or _overlap(a.places, b.places)
        or _overlap(a.kilometer_mentions, b.kilometer_mentions)
    )
    return sim >= (max(0.10, threshold - 0.12) if strong_place else threshold)


def _rank(alert):
    return (
        -int(alert.source_tier), float(alert.confidence),
        {"alta": 3, "media": 2, "baja": 1}.get(alert.severity, 0),
        len(alert.description or ""),
    )


def _verification_label(tiers, source_count):
    if source_count <= 1:
        return "una_fuente"
    if 1 in tiers and 2 in tiers:
        return "oficial_cruzada"
    if 1 in tiers:
        return "facebook_oficial_confirmado"
    if 2 in tiers:
        return "web_oficial_confirmado"
    return "multiples_medios"


def _confidence(base, tiers, source_count):
    score = float(base)
    if source_count >= 2: score += 0.08
    if source_count >= 3: score += 0.05
    if 1 in tiers and 2 in tiers: score += 0.08
    elif 1 in tiers: score += 0.04
    return round(min(score, 0.99), 2)


def _unique_extend(cluster, attr, limit=20):
    out = []
    for a in cluster:
        for x in getattr(a, attr, []) or []:
            if x and x not in out:
                out.append(x)
    return out[:limit]



def _date_key(value):
    try:
        d = dateparser.parse(value) if value else None
        return d.timestamp() if d and d.tzinfo else float("-inf")
    except Exception:
        return float("-inf")


def _resolve_status(cluster, best):
    statuses = [a.status for a in cluster if a.status and a.status != "desconocido"]
    distinct = sorted(set(statuses))
    dated = [a for a in cluster if _date_key(a.published_at) != float("-inf")]
    latest = max(dated, key=lambda a: (_date_key(a.published_at), -a.source_tier)) if dated else best
    chosen = latest.status if latest.status != "desconocido" else best.status
    evidence = []
    for a in sorted(cluster, key=lambda x: (_date_key(x.published_at), -x.source_tier), reverse=True):
        evidence.append({
            "status": a.status, "published_at": a.published_at, "source_id": a.source_id,
            "source_name": a.source_name, "tier": a.source_tier, "url": a.url,
        })
    return chosen, len(distinct) > 1, evidence[:12], latest


def merge_alerts(alerts, hours=24, threshold=0.24):
    clusters = []
    for alert in alerts:
        for cluster in clusters:
            if any(same_incident(alert, x, hours, threshold) for x in cluster):
                cluster.append(alert)
                break
        else:
            clusters.append([alert])

    out = []
    for cluster in clusters:
        best = sorted(cluster, key=_rank, reverse=True)[0]
        d = best.to_dict()
        resolved_status, status_conflict, status_evidence, latest_alert = _resolve_status(cluster, best)
        d["status"] = resolved_status
        d["status_conflict"] = status_conflict
        d["status_evidence"] = status_evidence
        d["latest_update_at"] = latest_alert.published_at or best.published_at
        # Si el mismo incidente contiene el bloqueo original y luego una habilitación,
        # conservar el tipo de incidente original y usar "status=habilitado" como estado actual.
        if d.get("event_type") == "habilitacion":
            original = next((a for a in cluster if a.event_type in {"bloqueo", "cierre_vial", "derrumbe", "inundacion", "accidente"}), None)
            if original:
                d["event_type"] = original.event_type

        sources, seen_sources, urls = [], set(), []
        for a in sorted(cluster, key=lambda x: x.source_tier):
            if a.source_id not in seen_sources:
                seen_sources.add(a.source_id)
                sources.append({
                    "id": a.source_id, "name": a.source_name, "class": a.source_class,
                    "tier": a.source_tier, "page_url": a.source_url, "post_url": a.url,
                    "icon_url": a.source_icon_url, "published_at": a.published_at,
                })
            if a.url and a.url not in urls:
                urls.append(a.url)

        tiers = sorted({a.source_tier for a in cluster})
        images = _unique_extend(cluster, "image_urls", 20)
        videos = []
        for a in cluster:
            if a.video_url and all(v["url"] != a.video_url for v in videos):
                videos.append({
                    "url": a.video_url,
                    "thumbnail_url": a.video_thumbnail_url,
                    "type": a.video_type,
                    "provider": "facebook" if (a.video_type or "").startswith("facebook") else "web",
                    "use_official_embed": bool((a.video_type or "").startswith("facebook")),
                    "source_id": a.source_id,
                })

        # Tomar coordenadas únicamente cuando alguna fuente las publicó explícitamente.
        coord_alert = next((a for a in cluster if a.latitude is not None and a.longitude is not None), None)
        if coord_alert:
            d["latitude"], d["longitude"] = coord_alert.latitude, coord_alert.longitude

        # Causa y cierre: preferir el dato de mejor fuente, pero rellenar si faltaba.
        if not d.get("cause"):
            d["cause"] = next((a.cause for a in cluster if a.cause), None)
        if not d.get("closure_scope"):
            d["closure_scope"] = next((a.closure_scope for a in cluster if a.closure_scope), None)

        d["roads"] = _unique_extend(cluster, "roads", 14)
        d["places"] = _unique_extend(cluster, "places", 14)
        d["kilometer_mentions"] = _unique_extend(cluster, "kilometer_mentions", 10)
        d["directions"] = _unique_extend(cluster, "directions", 10)
        d["alternative_routes"] = _unique_extend(cluster, "alternative_routes", 12)
        d["affected_vehicles"] = _unique_extend(cluster, "affected_vehicles", 10)
        d["time_mentions"] = _unique_extend(cluster, "time_mentions", 14)
        d["keywords"] = _unique_extend(cluster, "keywords", 25)
        d["image_urls"] = images
        d["image_url"] = images[0] if images else None
        d["has_image"] = bool(images)
        d["videos"] = videos[:8]
        d["video_url"] = videos[0]["url"] if videos else None
        d["video_thumbnail_url"] = videos[0].get("thumbnail_url") if videos else None
        d["has_video"] = bool(videos)
        d["media"] = {
            "images": images,
            "main_image_url": images[0] if images else None,
            "videos": videos[:8],
        }
        d["sources"] = sources
        d["source_count"] = len(sources)
        d["verification"] = _verification_label(tiers, len(sources))
        d["confidence"] = _confidence(best.confidence, tiers, len(sources))
        d["corroborated"] = len(sources) >= 2
        d["all_urls"] = urls[:20]
        d["merged_items"] = len(cluster)
        out.append(d)

    out.sort(key=lambda x: (
        x.get("published_at") or "",
        {"alta": 3, "media": 2, "baja": 1}.get(x.get("severity"), 0),
        x.get("confidence", 0),
    ), reverse=True)
    return out
