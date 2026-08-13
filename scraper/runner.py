import argparse
import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

from .classifier import build_alert, rejection_reason, analyze_relevance
from .facebook import scrape_facebook_public, scrape_facebook_sources
from .web_sources import scrape_generic_web
from .merger import merge_alerts
from .state_manager import reconcile

ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def now_iso(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).isoformat(timespec="seconds")


def compact_text(s: str) -> str:
    return " ".join((s or "").split())


async def scrape_web_sources_fast(sources, settings):
    """Webs en paralelo con límite pequeño."""
    semaphore = asyncio.Semaphore(max(1, int(settings.get("web_concurrency", 5))))
    results = {}

    async def worker(source):
        async with semaphore:
            try:
                items = await asyncio.to_thread(scrape_generic_web, source, settings)
                results[source["id"]] = {"items": items, "error": None}
            except Exception as exc:
                results[source["id"]] = {"items": [], "error": str(exc)}

    await asyncio.gather(*(worker(s) for s in sources))
    return results


async def scrape_all_sources_fast(sources, settings):
    fb_sources = [s for s in sources if s["type"] == "facebook_public"]
    web_sources = [s for s in sources if s["type"] == "generic_web"]

    fb_task = asyncio.create_task(scrape_facebook_sources(fb_sources, settings)) if fb_sources else None
    web_task = asyncio.create_task(scrape_web_sources_fast(web_sources, settings)) if web_sources else None

    fb_results = await fb_task if fb_task else {}
    web_results = await web_task if web_task else {}

    results = {}
    results.update(fb_results)
    results.update(web_results)
    return results

def _clean_old_outputs(out_dir: Path):
    """La V3.1 deja la carpeta data simple; elimina salidas antiguas de V2/V3."""
    legacy = [
        "alertas_viales.json", "incidentes_viales.json", "alertas_individuales.json",
        "incidentes_historial.json", "fuentes.json", "alertas_viales.csv",
    ]
    for name in legacy:
        p = out_dir / name
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def _rejected_sample(item, reason):
    analysis = analyze_relevance(item)
    return {
        "reason": reason,
        "relevance_score": analysis.get("score", 0),
        "filter_reasons": analysis.get("reasons", []),
        "detected_event": analysis.get("event"),
        "url": item.item_url,
        "published_at": item.published_at,
        "has_video": bool(item.video_url),
        "has_image": bool(item.image_urls),
        "text_preview": compact_text(item.text)[:520],
    }


async def run(config_path: Path, out_dir: Path, only: str | None = None):
    cfg = load_config(config_path)
    settings, sources = cfg["settings"], cfg["sources"]
    if only:
        wanted = {x.strip() for x in only.split(",") if x.strip()}
        sources = [s for s in sources if s["id"] in wanted]

    scraped_at = now_iso(settings.get("timezone", "America/La_Paz"))
    individual_alerts, stats = [], []
    max_rejected = int(settings.get("max_rejected_samples_per_source", 3))


    print("==================================================")
    print("MODO RAPIDO: Web en paralelo | Facebook secuencial y pausado")
    print("==================================================")
    print(
        f"Facebook pausa entre fuentes={settings.get('facebook_delay_seconds', 8)}s "
        f"(se detiene toda la corrida de Facebook si una fuente es bloqueada) | "
        f"Web concurrencia={settings.get('web_concurrency', 5)} | "
        f"posts/fuente={settings.get('max_items_per_source', 18)}"
    )

    scrape_results = await scrape_all_sources_fast(sources, settings)

    for idx, source in enumerate(sources, 1):
        print(f"[{idx}/{len(sources)}] TIER {source.get('tier', 3)} {source['id']} - {source['name']}")
        result = scrape_results.get(source["id"], {"items": [], "error": "Sin resultado"})
        if result.get("error"):
            exc = result["error"]
            stats.append({
                "id": source["id"], "name": source["name"], "url": source["url"],
                "type": source["type"], "source_class": source.get("source_class"), "tier": source.get("tier"),
                "region": source.get("region"), "city": source.get("city"), "icon_url": source.get("icon_url"),
                "status": "error", "raw_items": 0, "alerts": 0, "rejected": 0,
                "images_detected": 0, "videos_detected": 0, "rejected_samples": [],
                "error": compact_text(str(exc))[:700],
            })
            print(f"  ERROR: {exc}")
            continue

        raw_items = result.get("items", [])
        built = []
        rejected = []
        for item in raw_items:
            alert = build_alert(item, scraped_at)
            if alert:
                built.append(alert)
            elif len(rejected) < max_rejected:
                rejected.append(_rejected_sample(item, rejection_reason(item)))

        individual_alerts.extend(built)
        icon = next((x.source_icon_url for x in raw_items if x.source_icon_url), source.get("icon_url"))
        img_count = sum(len(x.image_urls or []) for x in raw_items)
        video_count = sum(1 for x in raw_items if x.video_url)
        stats.append({
            "id": source["id"], "name": source["name"], "url": source["url"],
            "type": source["type"], "source_class": source.get("source_class"), "tier": source.get("tier"),
            "region": source.get("region"), "city": source.get("city"), "icon_url": icon,
            "status": "ok", "raw_items": len(raw_items), "alerts": len(built),
            "rejected": max(0, len(raw_items) - len(built)),
            "images_detected": img_count, "videos_detected": video_count,
            "rejected_samples": rejected,
            "error": None,
        })
        print(
            f"  OK publicaciones={len(raw_items)} viales={len(built)} "
            f"descartadas={len(raw_items)-len(built)} fotos={img_count} videos={video_count}"
        )
    individual_alerts = list({a.id: a for a in individual_alerts}.values())
    merged = merge_alerts(
        individual_alerts,
        hours=float(settings.get("merge_window_hours", 24)),
        threshold=float(settings.get("merge_similarity_threshold", 0.24)),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    internal_dir = out_dir / "_interno"
    internal_dir.mkdir(parents=True, exist_ok=True)
    archive_path = internal_dir / "incidentes_historial.json"

    incidents, archive = reconcile(
        merged, archive_path, scraped_at,
        keep_days=int(settings.get("history_keep_days", 14)),
        threshold=float(settings.get("history_match_threshold", 0.63)),
    )
    archive_path.write_text(json.dumps({"generated_at": scraped_at, "incidents": archive}, ensure_ascii=False, indent=2), encoding="utf-8")

    fb_sources = [s for s in sources if s["type"] == "facebook_public"]
    web_sources = [s for s in sources if s["type"] == "generic_web"]

    # JSON PRINCIPAL: este es el único que debería consumir la app.
    main_payload = {
        "schema_version": "3.2-fast",
        "generated_at": scraped_at,
        "timezone": settings.get("timezone", "America/La_Paz"),
        "summary": {
            "facebook_sources": len(fb_sources),
            "web_sources": len(web_sources),
            "sources_ok": sum(1 for s in stats if s["status"] == "ok"),
            "sources_error": sum(1 for s in stats if s["status"] == "error"),
            "raw_publications": sum(s.get("raw_items", 0) for s in stats),
            "vial_publications": len(individual_alerts),
            "incidents": len(incidents),
        },
        "incidents": incidents,
        "sources": [
            {k: x.get(k) for k in ["id","name","url","type","source_class","tier","region","city","icon_url","status"]}
            for x in stats
        ],
    }
    (out_dir / "transito_bolivia.json").write_text(
        json.dumps(main_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Diagnóstico: para saber por qué una fuente dio 0 alertas.
    (out_dir / "estado_fuentes.json").write_text(
        json.dumps({"generated_at": scraped_at, "sources": stats}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fieldnames = [
        "incident_id","published_at","latest_update_at","first_seen_at","last_seen_at",
        "department","municipality","city","event_type","cause","status","lifecycle_status","is_active",
        "closure_scope","severity","confidence","relevance_score","verification","status_conflict","corroborated","source_count",
        "title","description","roads","places","kilometer_mentions","directions","alternative_routes",
        "affected_vehicles","latitude","longitude","location_query","source_icon_url","image_url","image_urls",
        "video_url","video_thumbnail_url","history_count","sources"
    ]
    with (out_dir / "transito_bolivia.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for d in incidents:
            row = {k: d.get(k) for k in fieldnames}
            for key in ["roads","places","kilometer_mentions","directions","alternative_routes","affected_vehicles","image_urls"]:
                row[key] = " | ".join(d.get(key) or [])
            row["sources"] = " | ".join(f"{x['name']} [T{x['tier']}]" for x in d.get("sources", []))
            w.writerow(row)

    _clean_old_outputs(out_dir)

    print("\n==================================================")
    print("SCRAPER V3.2 PREMIUM FAST TERMINADO")
    print("==================================================")
    print(f"Publicaciones encontradas:   {sum(s.get('raw_items',0) for s in stats)}")
    print(f"Publicaciones viales:        {len(individual_alerts)}")
    print(f"Incidentes finales:          {len(incidents)}")
    print("\nUSA ESTOS 2 JSON:")
    print(f"  APP:        {out_dir / 'transito_bolivia.json'}")
    print(f"  DIAGNOSTICO:{out_dir / 'estado_fuentes.json'}")
    return 0


def main():
    p = argparse.ArgumentParser(description="Scraper V3.2 Premium FAST híbrido de tránsito vial de Bolivia")
    p.add_argument("--config", default=str(ROOT / "config" / "sources.yaml"))
    p.add_argument("--out", default=str(ROOT / "data"))
    p.add_argument("--only", default=None, help="IDs de fuentes separados por coma")
    args = p.parse_args()
    return asyncio.run(run(Path(args.config), Path(args.out), args.only))


if __name__ == "__main__":
    raise SystemExit(main())
