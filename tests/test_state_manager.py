import json
from pathlib import Path
from scraper.state_manager import reconcile


def base(status="cerrado"):
    return {
        "id":"x", "event_type":"bloqueo", "department":"Cochabamba", "municipality":"Cochabamba",
        "city":"Cochabamba", "roads":["carretera Cochabamba - Santa Cruz"], "places":["sector Puente Ichilo"],
        "kilometer_mentions":["km 122"], "title":"Bloqueo Puente Ichilo", "description":"Bloqueo Puente Ichilo km 122",
        "status":status, "closure_scope":"total" if status=="cerrado" else "sin_cierre", "severity":"alta",
        "source_count":1, "sources":[{"name":"Tránsito"}], "published_at":"2026-08-12T08:00:00-04:00",
        "all_urls":["https://example.com/1"]
    }


def test_history_status_change(tmp_path: Path):
    archive = tmp_path / "hist.json"
    first, arc = reconcile([base("cerrado")], archive, "2026-08-12T08:10:00-04:00")
    archive.write_text(json.dumps({"incidents": arc}), encoding="utf-8")
    second_input = base("habilitado")
    second_input["published_at"] = "2026-08-12T10:00:00-04:00"
    second, _ = reconcile([second_input], archive, "2026-08-12T10:05:00-04:00")
    assert second[0]["incident_id"] == first[0]["incident_id"]
    assert second[0]["lifecycle_status"] == "finalizado"
    assert second[0]["is_active"] is False
    assert second[0]["history_count"] >= 2
