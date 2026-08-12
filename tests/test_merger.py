from scraper.models import RawItem
from scraper.classifier import build_alert
from scraper.merger import merge_alerts


def mk(source_id, tier, text, url, published="2026-08-12T08:00:00-04:00", video=False):
    item = RawItem(
        source_id=source_id, source_name=source_id, source_url=url, item_url=url,
        text=text, published_at=published, region_hint="Cochabamba", city_hint="Cochabamba",
        source_class="facebook_official" if tier == 1 else "media", tier=tier,
        image_urls=[f"{url}/foto.jpg"],
        video_url=f"{url}/videos/123" if video else None,
        video_thumbnail_url=f"{url}/thumb.jpg" if video else None,
        video_type="facebook_video" if video else None,
    )
    return build_alert(item, "2026-08-12T09:00:00-04:00")


def test_merge_same_bloqueo_media():
    a = mk("transito_cbba", 1, "Bloqueo total en Cochabamba, carretera Cochabamba - Santa Cruz, sector Puente Ichilo.", "https://facebook.com/a", video=True)
    b = mk("medio", 3, "Cochabamba reporta bloqueo en la carretera Cochabamba - Santa Cruz, sector Puente Ichilo.", "https://facebook.com/b")
    merged = merge_alerts([a, b])
    assert len(merged) == 1
    assert merged[0]["source_count"] == 2
    assert merged[0]["corroborated"] is True
    assert merged[0]["has_image"] is True
    assert merged[0]["has_video"] is True
    assert merged[0]["videos"][0]["use_official_embed"] is True
