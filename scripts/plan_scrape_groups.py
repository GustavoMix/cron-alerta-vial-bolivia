"""Genera la matriz de grupos para el workflow de GitHub Actions.

Facebook deja pasar solo ~2 fuentes por IP antes de degradar el contenido
(login wall / og:description en vez del post real). La mitigación real es
correr cada grupo pequeño de fuentes Facebook en su propio job de GitHub
Actions: cada job usa un runner efímero con su propia IP de salida.

Imprime en stdout un JSON `{"include": [{"group": "...", "ids": "a,b"}]}`
listo para `strategy.matrix` vía `fromJson(...)`.
"""

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    group_size = max(1, int(os.environ.get("FB_GROUP_SIZE", "2")))
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    fb_ids = [s["id"] for s in cfg["sources"] if s["type"] == "facebook_public"]

    groups = [fb_ids[i:i + group_size] for i in range(0, len(fb_ids), group_size)]
    include = [
        {"group": f"fb-{i + 1:02d}", "ids": ",".join(group)}
        for i, group in enumerate(groups)
    ]

    json.dump({"include": include}, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
