from scraper.models import RawItem
from scraper.classifier import build_alert


def test_bloqueo_cochabamba_detallado():
    item = RawItem(
        source_id="test", source_name="Test Oficial", source_url="https://example.com",
        item_url="https://example.com/1",
        text=(
            "Cochabamba: bloqueo total en la carretera Cochabamba - Santa Cruz, "
            "sector Puente Ichilo, km 122. Ambos sentidos cerrados desde las 08:30. "
            "Se recomienda utilizar la vía antigua como ruta alternativa."
        ),
        published_at="2026-08-12T08:00:00-04:00",
        region_hint="Cochabamba", city_hint="Cochabamba",
        source_class="facebook_official", tier=1,
        source_icon_url="https://example.com/icon.jpg",
        image_urls=["https://example.com/foto.jpg"],
    )
    a = build_alert(item, "2026-08-12T08:45:00-04:00")
    assert a is not None
    assert a.event_type == "bloqueo"
    assert a.status == "cerrado"
    assert a.closure_scope == "total"
    assert a.department == "Cochabamba"
    assert a.kilometer_mentions
    assert a.alternative_routes
    assert a.source_icon_url
    assert a.image_urls
    assert a.confidence >= 0.8


def test_derrumbe_lapaz():
    item = RawItem(
        source_id="test2", source_name="Test", source_url="https://example.com",
        item_url="https://example.com/2",
        text="La Paz: derrumbe por lluvias en la ruta a Yungas. Transitable con precaución.",
        source_class="facebook_official", tier=1, region_hint="La Paz",
    )
    a = build_alert(item, "2026-08-12T08:45:00-04:00")
    assert a.event_type == "derrumbe"
    assert a.department == "La Paz"
    assert a.status == "precaucion"
    assert a.cause in {"lluvia", "derrumbe_deslizamiento"}


def test_hecho_de_transito_es_accidente():
    item = RawItem(
        source_id="transito",
        source_name="Transito",
        source_url="https://example.com",
        item_url="https://example.com/post",
        text="Se atendió un hecho de tránsito con atropello en la avenida Blanco Galindo, km 5.",
        source_class="facebook_official",
        tier=1,
        region_hint="Cochabamba",
        city_hint="Cochabamba",
    )
    a = build_alert(item, "2026-08-12T10:00:00-04:00")
    assert a is not None
    assert a.event_type == "accidente"
    assert a.kilometer_mentions
