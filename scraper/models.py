from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any


@dataclass
class RawItem:
    source_id: str
    source_name: str
    source_url: str
    item_url: str
    text: str
    title: str = ""
    published_at: Optional[str] = None
    region_hint: Optional[str] = None
    city_hint: Optional[str] = None
    source_class: str = "media"
    tier: int = 3

    # Multimedia pública. Nunca se extrae un stream MP4 interno de Facebook;
    # se conserva el enlace público del post/video y sus miniaturas/imágenes.
    source_icon_url: Optional[str] = None
    image_urls: List[str] = field(default_factory=list)
    video_url: Optional[str] = None
    video_thumbnail_url: Optional[str] = None
    video_type: Optional[str] = None


@dataclass
class Alert:
    id: str
    source_id: str
    source_name: str
    source_url: str
    source_class: str
    source_tier: int
    source_icon_url: Optional[str]
    url: str
    published_at: Optional[str]
    scraped_at: str

    department: Optional[str]
    municipality: Optional[str]
    city: Optional[str]
    event_type: str
    cause: Optional[str]
    status: str
    closure_scope: Optional[str]
    severity: str
    confidence: float
    relevance_score: int
    filter_reasons: List[str]

    title: str
    description: str
    original_text: str

    roads: List[str]
    places: List[str]
    kilometer_mentions: List[str]
    directions: List[str]
    alternative_routes: List[str]
    affected_vehicles: List[str]
    time_mentions: List[str]
    keywords: List[str]

    latitude: Optional[float]
    longitude: Optional[float]
    location_query: Optional[str]

    image_urls: List[str]
    video_url: Optional[str]
    video_thumbnail_url: Optional[str]
    video_type: Optional[str]

    is_official: bool

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["image_url"] = self.image_urls[0] if self.image_urls else None
        d["has_image"] = bool(self.image_urls)
        d["has_video"] = bool(self.video_url)
        d["media"] = {
            "images": self.image_urls,
            "main_image_url": self.image_urls[0] if self.image_urls else None,
            "video": {
                "url": self.video_url,
                "thumbnail_url": self.video_thumbnail_url,
                "type": self.video_type,
                "provider": "facebook" if (self.video_type or "").startswith("facebook") else ("web" if self.video_url else None),
                "use_official_embed": bool(self.video_url and (self.video_type or "").startswith("facebook")),
            } if self.video_url else None,
        }
        return d
