from scraper.models import RawItem
from scraper.classifier import build_alert, analyze_relevance


def item(text, tier=3, region="Bolivia", city=None):
    return RawItem(
        source_id="test",
        source_name="Test",
        source_url="https://example.com",
        item_url="https://example.com/post",
        text=text,
        region_hint=region,
        city_hint=city,
        source_class="media" if tier == 3 else "facebook_official",
        tier=tier,
    )


def test_bolivia_points_blocking_and_terminals():
    a = build_alert(
        item(
            "La Paz registra 15 puntos de bloqueo. Los cortes de ruta afectan la carretera "
            "La Paz - Oruro y las salidas desde la terminal de buses están suspendidas. "
            "No hay paso vehicular en Patacamaya.",
            tier=1, region="La Paz", city="La Paz",
        ),
        "2026-08-12T10:00:00-04:00",
    )
    assert a is not None
    assert a.event_type in {"bloqueo", "terminal_suspendida", "cierre_vial"}
    assert a.relevance_score >= 55
    assert a.status == "cerrado"


def test_movilizacion_with_road_impact_is_accepted():
    a = build_alert(
        item(
            "Transportistas cumplen una movilización y marcha en Cochabamba. "
            "La protesta bloquea la avenida Blanco Galindo y genera congestión vehicular "
            "en sentido a Quillacollo.",
            region="Cochabamba", city="Cochabamba",
        ),
        "2026-08-12T10:00:00-04:00",
    )
    assert a is not None
    assert a.relevance_score >= 55


def test_general_political_march_without_road_impact_is_rejected():
    analysis = analyze_relevance(
        item(
            "Organizaciones sociales anuncian una marcha nacional para exigir atención "
            "a sus demandas. Los dirigentes brindaron una conferencia de prensa."
        )
    )
    assert analysis["accepted"] is False


def test_traffic_of_drugs_is_false_positive_rejected():
    analysis = analyze_relevance(
        item(
            "La Policía informó un operativo contra el tráfico de drogas y sustancias "
            "controladas. Se aprehendió a dos personas."
        )
    )
    assert analysis["accepted"] is False


def test_embotellamiento_trancadera_is_accepted():
    a = build_alert(
        item(
            "Fuerte trancadera y embotellamiento en el tercer anillo de Santa Cruz. "
            "Hay largas filas de vehículos y circulación lenta hacia la radial 17 1/2.",
            region="Santa Cruz", city="Santa Cruz de la Sierra",
        ),
        "2026-08-12T10:00:00-04:00",
    )
    assert a is not None
    assert a.event_type == "congestion"
    assert a.relevance_score >= 55


def test_riada_platform_loss_is_accepted():
    a = build_alert(
        item(
            "Una riada provocó pérdida de plataforma en la carretera a los Yungas. "
            "La vía está intransitable y hay vehículos varados en el sector.",
            tier=1, region="La Paz",
        ),
        "2026-08-12T10:00:00-04:00",
    )
    assert a is not None
    assert a.event_type in {"inundacion", "deterioro_vial"}
    assert a.severity in {"alta", "critica"}
