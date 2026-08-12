import hashlib
import json
import re
import unicodedata
from pathlib import Path
from dateutil import parser as dateparser


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(d):
    text = " ".join([
        d.get("title") or "", (d.get("description") or "")[:800],
        " ".join(d.get("roads") or []), " ".join(d.get("places") or []),
        " ".join(d.get("kilometer_mentions") or []),
    ])
    return {x for x in _norm(text).split() if len(x) >= 4}


def _jac(a, b):
    A, B = _tokens(a), _tokens(b)
    return len(A & B) / len(A | B) if A and B else 0.0


def _same_event(a, b):
    ea, eb = a.get("event_type"), b.get("event_type")
    if ea == eb:
        return True
    return {ea, eb} <= {"bloqueo", "cierre_vial", "habilitacion"}


def _set_overlap(a, b, key):
    A = {_norm(x) for x in (a.get(key) or []) if x}
    B = {_norm(x) for x in (b.get(key) or []) if x}
    return bool(A & B)


def match_score(cur, old):
    if cur.get("department") and old.get("department") and cur["department"] != old["department"]:
        return 0.0
    if not _same_event(cur, old):
        return 0.0
    score = 0.35
    if cur.get("department") == old.get("department") and cur.get("department"): score += 0.12
    if cur.get("city") == old.get("city") and cur.get("city"): score += 0.08
    if cur.get("municipality") == old.get("municipality") and cur.get("municipality"): score += 0.05
    if _set_overlap(cur, old, "roads"): score += 0.20
    if _set_overlap(cur, old, "places"): score += 0.08
    if _set_overlap(cur, old, "kilometer_mentions"): score += 0.06
    score += min(_jac(cur, old), 0.25)
    return min(score, 1.0)


def _incident_id(d):
    canonical = "|".join([
        d.get("department") or "", d.get("city") or "", d.get("event_type") or "",
        (d.get("roads") or [""])[0], (d.get("places") or [""])[0],
        (d.get("kilometer_mentions") or [""])[0],
    ])
    return "inc_" + hashlib.sha1(_norm(canonical).encode("utf-8")).hexdigest()[:14]


def _lifecycle(d):
    st = d.get("status")
    ev = d.get("event_type")
    if st == "habilitado" or ev == "habilitacion":
        return "finalizado", False
    if st in {"cerrado", "restringido", "precaucion"}:
        return "activo", True
    return "desconocido", None


def _history_entry(d, at, reason):
    return {
        "at": d.get("published_at") or at,
        "detected_at": at,
        "reason": reason,
        "status": d.get("status"),
        "lifecycle_status": _lifecycle(d)[0],
        "severity": d.get("severity"),
        "closure_scope": d.get("closure_scope"),
        "source_count": d.get("source_count", 1),
        "sources": [x.get("name") for x in d.get("sources", [])][:12],
        "url": (d.get("all_urls") or [d.get("url")])[0] if (d.get("all_urls") or [d.get("url")]) else None,
    }


def load_archive(path: Path):
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj.get("incidents", [])
    except Exception:
        return []


def _days_old(iso, now):
    try:
        a, b = dateparser.parse(iso), dateparser.parse(now)
        return abs((b - a).total_seconds()) / 86400.0
    except Exception:
        return 0


def reconcile(current, archive_path: Path, generated_at: str, keep_days=14, threshold=0.63):
    previous = load_archive(archive_path)
    used = set()
    enriched = []

    for cur in current:
        best_i, best_score = None, 0.0
        for i, old in enumerate(previous):
            if i in used:
                continue
            score = match_score(cur, old)
            if score > best_score:
                best_i, best_score = i, score

        old = previous[best_i] if best_i is not None and best_score >= threshold else None
        if old is not None:
            used.add(best_i)
            cur["incident_id"] = old.get("incident_id") or _incident_id(cur)
            cur["first_seen_at"] = old.get("first_seen_at") or generated_at
            history = list(old.get("history") or [])
            changed = any([
                old.get("status") != cur.get("status"),
                old.get("closure_scope") != cur.get("closure_scope"),
                old.get("severity") != cur.get("severity"),
                old.get("source_count") != cur.get("source_count"),
            ])
            if changed:
                history.append(_history_entry(cur, generated_at, "actualizacion"))
            cur["history"] = history[-60:]
        else:
            cur["incident_id"] = _incident_id(cur)
            cur["first_seen_at"] = generated_at
            cur["history"] = [_history_entry(cur, generated_at, "primera_deteccion")]

        lifecycle, active = _lifecycle(cur)
        cur["lifecycle_status"] = lifecycle
        cur["is_active"] = active
        cur["last_seen_at"] = generated_at
        cur["seen_this_run"] = True
        cur["history_count"] = len(cur["history"])
        enriched.append(cur)

    # Archivo conserva incidentes recientes que no aparecieron en esta ejecución,
    # pero NO los marca como resueltos automáticamente.
    archive = list(enriched)
    for i, old in enumerate(previous):
        if i in used:
            continue
        if _days_old(old.get("last_seen_at") or old.get("first_seen_at"), generated_at) > keep_days:
            continue
        copy = dict(old)
        copy["seen_this_run"] = False
        if copy.get("lifecycle_status") == "activo":
            copy["lifecycle_status"] = "sin_actualizacion"
        archive.append(copy)

    # Dedup por incident_id; el actual gana.
    dedup = {}
    for item in archive:
        key = item.get("incident_id") or _incident_id(item)
        if key not in dedup or item.get("seen_this_run"):
            dedup[key] = item
    archive = list(dedup.values())[:800]
    return enriched, archive
