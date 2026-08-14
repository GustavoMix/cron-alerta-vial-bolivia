import argparse
import asyncio
import csv
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

from .classifier import build_alert, rejection_reason, analyze_relevance
from .facebook import scrape_facebook_public, scrape_facebook_sources
from .models import RawItem
from .planificador import (
    actualizar_rotacion,
    cargar_rotacion,
    matriz_github,
    planificar_grupos,
)
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


async def scrape_all_sources_fast(sources, settings, preloaded_facebook_results=None):
    """Si preloaded_facebook_results viene dado, no se vuelve a scrapear Facebook
    (ya se hizo en otro job de CI, con otra IP de runner) y se usan esos
    resultados tal cual."""
    fb_sources = [s for s in sources if s["type"] == "facebook_public"]
    web_sources = [s for s in sources if s["type"] == "generic_web"]

    if preloaded_facebook_results is not None:
        web_task = asyncio.create_task(scrape_web_sources_fast(web_sources, settings)) if web_sources else None
        fb_results = preloaded_facebook_results
        web_results = await web_task if web_task else {}
    else:
        fb_task = asyncio.create_task(scrape_facebook_sources(fb_sources, settings)) if fb_sources else None
        web_task = asyncio.create_task(scrape_web_sources_fast(web_sources, settings)) if web_sources else None
        fb_results = await fb_task if fb_task else {}
        web_results = await web_task if web_task else {}

    results = {}
    results.update(fb_results)
    results.update(web_results)
    return results


async def scrape_facebook_group(config_path: Path, group_ids: set[str], raw_out: Path) -> int:
    """Modo fan-out: scrapea solo las fuentes de Facebook en group_ids y guarda
    el resultado crudo (sin clasificar) en raw_out. Pensado para correr cada
    grupo en un job de CI distinto -con su propia IP de runner- y combinarlos
    después con --facebook-raw-in en el job final."""
    cfg = load_config(config_path)
    settings, sources = cfg["settings"], cfg["sources"]
    fb_sources = [s for s in sources if s["type"] == "facebook_public" and s["id"] in group_ids]
    if not fb_sources:
        raise SystemExit(f"Ninguna fuente de Facebook coincide con el grupo: {sorted(group_ids)}")

    print(f"Scrapeando grupo de Facebook ({len(fb_sources)} fuentes): {[s['id'] for s in fb_sources]}")
    results = await scrape_facebook_sources(fb_sources, settings)

    serializable = {}
    for source_id, result in results.items():
        serializable[source_id] = {
            "items": [asdict(item) for item in result.get("items", [])],
            "error": result.get("error"),
        }

    raw_out.parent.mkdir(parents=True, exist_ok=True)
    raw_out.write_text(
        json.dumps(
            {"scraped_at": now_iso(settings.get("timezone", "America/La_Paz")), "results": serializable},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    ok = sum(1 for r in results.values() if not r.get("error"))
    print(f"Grupo terminado: {ok}/{len(fb_sources)} fuentes OK. Guardado en {raw_out}")
    return 0


def planificar_facebook(config_path: Path, rotacion_path: Path, tamano_grupo: int) -> str:
    """Arma la matrix de GitHub Actions para el fan-out de Facebook, usando el
    historial de rotación para decidir a qué fuente le toca el primer turno de
    cada grupo (que es el que casi siempre esquiva el bloqueo)."""
    cfg = load_config(config_path)
    settings, sources = cfg["settings"], cfg["sources"]
    fb_sources = [s for s in sources if s["type"] == "facebook_public"]
    if not fb_sources:
        raise SystemExit("No hay fuentes de Facebook en la configuración")

    ahora = datetime.now(ZoneInfo(settings.get("timezone", "America/La_Paz")))
    rotacion = cargar_rotacion(rotacion_path)
    grupos = planificar_grupos(fb_sources, rotacion, tamano_grupo, ahora)

    print(
        f"Planificadas {len(fb_sources)} fuentes de Facebook en {len(grupos)} grupos "
        f"de hasta {tamano_grupo} (una IP de runner por grupo).",
        file=sys.stderr,
    )
    for grupo in grupos:
        print(f"  {grupo['nombre']}: {grupo['fuentes']}", file=sys.stderr)

    return matriz_github(grupos)


def _load_facebook_raw(paths: list[Path]) -> dict:
    """Junta los resultados de scrape_facebook_group de varios grupos en un
    solo dict {source_id: {"items": [RawItem...], "error": str|None}}."""
    combined: dict = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for source_id, entry in data.get("results", {}).items():
            combined[source_id] = {
                "items": [RawItem(**d) for d in entry.get("items", [])],
                "error": entry.get("error"),
            }
    return combined

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


async def run(
    config_path: Path,
    out_dir: Path,
    only: str | None = None,
    facebook_raw_in: list[Path] | None = None,
):
    cfg = load_config(config_path)
    settings, sources = cfg["settings"], cfg["sources"]
    if only:
        wanted = {x.strip() for x in only.split(",") if x.strip()}
        sources = [s for s in sources if s["id"] in wanted]

    scraped_at = now_iso(settings.get("timezone", "America/La_Paz"))
    individual_alerts, stats = [], []
    max_rejected = int(settings.get("max_rejected_samples_per_source", 3))

    preloaded_facebook_results = _load_facebook_raw(facebook_raw_in) if facebook_raw_in else None

    print("==================================================")
    if preloaded_facebook_results is not None:
        print("MODO RAPIDO: Web en paralelo | Facebook ya scrapeado en jobs separados")
    else:
        print("MODO RAPIDO: Web en paralelo | Facebook secuencial y pausado")
    print("==================================================")
    print(
        f"Facebook pausa entre fuentes={settings.get('facebook_delay_seconds', 8)}s "
        f"(se detiene toda la corrida de Facebook si una fuente es bloqueada) | "
        f"Web concurrencia={settings.get('web_concurrency', 5)} | "
        f"posts/fuente={settings.get('max_items_per_source', 18)}"
    )

    scrape_results = await scrape_all_sources_fast(
        sources, settings, preloaded_facebook_results=preloaded_facebook_results
    )

    # Memoria de rotación: qué fuente de Facebook sí trajo datos esta vez. La
    # próxima corrida usa esto para darle el primer turno -el que esquiva el
    # bloqueo- a las que llevan más tiempo sin aparecer.
    fb_ids = {s["id"] for s in sources if s["type"] == "facebook_public"}
    fb_results = {sid: r for sid, r in scrape_results.items() if sid in fb_ids}
    if fb_results:
        actualizar_rotacion(
            out_dir / "_interno" / "facebook_rotacion.json", fb_results, scraped_at
        )

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
    p.add_argument(
        "--facebook-scrape-group-out", default=None,
        help="Modo fan-out: scrapea solo las fuentes de Facebook listadas en --only y "
             "guarda el resultado crudo (sin clasificar) en este archivo, sin escribir "
             "los JSON finales. Pensado para correr cada grupo en un job de CI distinto "
             "(con su propia IP de runner) y combinarlos después con --facebook-raw-in.",
    )
    p.add_argument(
        "--facebook-raw-in", default=None,
        help="Uno o más archivos generados con --facebook-scrape-group-out, separados por "
             "coma. Si se pasa, no se vuelve a scrapear Facebook: se usan esos resultados "
             "ya guardados y solo se scrapean las fuentes web antes de clasificar y "
             "escribir los JSON finales.",
    )
    p.add_argument(
        "--planificar-facebook", action="store_true",
        help="Imprime 'matriz=<json>' con los grupos de fuentes de Facebook para el "
             "fan-out de CI, repartidos por prioridad de rotación. Pensado para "
             "redirigirse a $GITHUB_OUTPUT y consumirse con fromJSON().",
    )
    p.add_argument(
        "--tamano-grupo", type=int, default=2,
        help="Fuentes de Facebook por grupo/job al planificar (default 2). Facebook "
             "corta después de 1-2 páginas por IP, así que grupos chicos pierden "
             "menos fuentes en cascada.",
    )
    args = p.parse_args()

    if args.planificar_facebook:
        rotacion_path = Path(args.out) / "_interno" / "facebook_rotacion.json"
        print(f"matriz={planificar_facebook(Path(args.config), rotacion_path, args.tamano_grupo)}")
        return 0

    if args.facebook_scrape_group_out:
        if not args.only:
            raise SystemExit("--facebook-scrape-group-out requiere --only con los IDs del grupo")
        group_ids = {x.strip() for x in args.only.split(",") if x.strip()}
        return asyncio.run(
            scrape_facebook_group(Path(args.config), group_ids, Path(args.facebook_scrape_group_out))
        )

    facebook_raw_in = None
    if args.facebook_raw_in:
        facebook_raw_in = [Path(x.strip()) for x in args.facebook_raw_in.split(",") if x.strip()]

    return asyncio.run(run(Path(args.config), Path(args.out), args.only, facebook_raw_in))


if __name__ == "__main__":
    raise SystemExit(main())
