"""Planificador de rotación para el scraping de Facebook.

Facebook corta el acceso público por IP/sesión después de 1 o 2 páginas. Eso no
se arregla con pausas más largas ni con otro User-Agent: el límite lo lleva la
IP del runner, no nuestro patrón de tráfico. Entonces la estrategia no es
"evitar el bloqueo" sino trabajar con él:

1. Muchos grupos chicos en vez de pocos grandes. Cada job de CI es una IP
   distinta, y de cada IP sacamos sus ~2 solicitudes buenas antes del corte.
   Con grupos de 2, casi ninguna fuente se pierde en cascada detrás de otra.

2. Repartir en round-robin, no en bloques. Las fuentes se ordenan por
   prioridad y se van repartiendo una por grupo, así las N más urgentes caen
   cada una en el *primer* turno de un grupo distinto — que es el turno que
   casi siempre pasa. Partirlas en bloques haría que la 1ª y la 2ª prioridad
   compitan dentro del mismo job.

3. Memoria entre corridas. Se guarda cuándo fue el último éxito de cada fuente
   y la que lleva más tiempo sin datos sube al primer turno en la corrida
   siguiente. Como el cron corre cada 30 minutos, en pocas vueltas todas las
   fuentes pasan por un turno bueno, aunque en una corrida puntual algunas
   queden bloqueadas.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

# Una fuente que nunca tuvo éxito debe ganarle a cualquiera que sí lo tuvo,
# por vieja que sea; este valor solo tiene que ser mayor a cualquier antigüedad
# realista en horas.
HORAS_NUNCA_VISTA = 10_000.0

# Las fuentes oficiales (tier 1) son las que de verdad publican cortes y
# desvíos; los medios (tier 3) suelen repetir lo mismo más tarde.
PESO_TIER = {1: 1.6, 2: 1.2, 3: 1.0}


def cargar_rotacion(path: Path) -> Dict[str, Any]:
    """Lee el estado de rotación. Si no existe o está corrupto, arranca vacío:
    la primera corrida simplemente prioriza por tier."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    fuentes = data.get("fuentes")
    return fuentes if isinstance(fuentes, dict) else {}


def _horas_desde(iso: str | None, ahora: datetime) -> float:
    if not iso:
        return HORAS_NUNCA_VISTA
    try:
        visto = datetime.fromisoformat(iso)
    except Exception:
        return HORAS_NUNCA_VISTA
    if visto.tzinfo is None:
        visto = visto.replace(tzinfo=ahora.tzinfo)
    return max(0.0, (ahora - visto).total_seconds() / 3600.0)


def puntaje(source: Dict[str, Any], rotacion: Dict[str, Any], ahora: datetime) -> float:
    """Cuánto 'merece' esta fuente el primer turno de un grupo. Más alto, antes."""
    estado = rotacion.get(source["id"], {})
    peso = PESO_TIER.get(int(source.get("tier", 3)), 1.0)

    # Una fuente que nunca tuvo éxito y ya acumuló varios bloqueos seguidos
    # probablemente no es un tema de IP -eso lo arregla la rotación normal-
    # sino que Facebook le exige sesión siempre, a cualquier visitante. Medir
    # su antigüedad desde el último ÉXITO (que nunca llega) la deja en
    # HORAS_NUNCA_VISTA para siempre, y ni descontándole el 90% le gana
    # cualquier otra fuente: un número enorme sigue siendo enorme. Por eso acá
    # se mide desde el último INTENTO -que pasa casi todas las corridas- y con
    # un peso chico: así entra en el reparto casi nunca, pero no queda del
    # todo excluida por si algún día Facebook le cambia la política.
    exitos = int(estado.get("exitos", 0))
    bloqueos = int(estado.get("bloqueos", 0))
    if exitos == 0 and bloqueos >= 4:
        horas_intento = _horas_desde(estado.get("ultimo_intento"), ahora)
        return horas_intento * peso * 0.05

    horas = _horas_desde(estado.get("ultimo_exito"), ahora)
    valor = horas * peso

    # Una fuente que falla seguido por algo que no es un bloqueo (página
    # renombrada, borrada, privada) no debería acaparar los turnos buenos
    # corrida tras corrida: se la sigue intentando, pero más atrás.
    fallos = int(estado.get("fallos_seguidos", 0))
    if fallos >= 3:
        valor *= 0.35
    elif fallos == 2:
        valor *= 0.7

    return valor


def planificar_grupos(
    sources: List[Dict[str, Any]],
    rotacion: Dict[str, Any],
    tamano_grupo: int = 2,
    ahora: datetime | None = None,
) -> List[Dict[str, Any]]:
    """Ordena las fuentes por prioridad y las reparte en round-robin entre
    tantos grupos como hagan falta para que ninguno pase de tamano_grupo."""
    if ahora is None:
        ahora = datetime.now(ZoneInfo("America/La_Paz"))

    tamano_grupo = max(1, int(tamano_grupo))
    ordenadas = sorted(
        sources,
        key=lambda s: (-puntaje(s, rotacion, ahora), s["id"]),
    )

    n_grupos = max(1, -(-len(ordenadas) // tamano_grupo))  # techo de la división
    cubos: List[List[str]] = [[] for _ in range(n_grupos)]
    for i, source in enumerate(ordenadas):
        cubos[i % n_grupos].append(source["id"])

    return [
        {
            "nombre": f"g{i + 1:02d}",
            "orden": i,
            "fuentes": ",".join(ids),
        }
        for i, cubos_i in enumerate(cubos)
        if (ids := cubos_i)
    ]


def matriz_github(grupos: List[Dict[str, Any]]) -> str:
    """Serializa los grupos como una matrix de GitHub Actions en una sola línea,
    lista para pasarse por fromJSON() desde el output de un job."""
    return json.dumps({"include": grupos}, ensure_ascii=False, separators=(",", ":"))


def actualizar_rotacion(
    path: Path,
    resultados: Dict[str, Any],
    scraped_at: str,
    conservar_dias: int = 30,
) -> Dict[str, Any]:
    """Registra cómo le fue a cada fuente de Facebook en esta corrida, para que
    la próxima sepa a quién le toca el primer turno.

    resultados: {source_id: {"items": [...], "error": str|None}}
    """
    rotacion = cargar_rotacion(path)

    try:
        ahora = datetime.fromisoformat(scraped_at)
    except Exception:
        ahora = datetime.now(ZoneInfo("America/La_Paz"))

    for source_id, resultado in resultados.items():
        estado = dict(rotacion.get(source_id, {}))
        error = resultado.get("error")
        items = resultado.get("items") or []

        estado["ultimo_intento"] = scraped_at

        if error:
            texto = str(error).lower()
            if texto.startswith("omitida"):
                # No llegó a intentarse de verdad: no cuenta ni como éxito ni
                # como fallo propio de la fuente.
                estado["ultimo_estado"] = "omitida"
                rotacion[source_id] = estado
                continue
            if "bloque" in texto or "blocked" in texto:
                # El bloqueo es de la IP, no un problema de esta fuente, así que
                # no se penaliza su prioridad: al contrario, sigue envejeciendo
                # y subirá sola en la próxima corrida.
                estado["ultimo_estado"] = "bloqueada"
                estado["bloqueos"] = int(estado.get("bloqueos", 0)) + 1
            else:
                estado["ultimo_estado"] = "error"
                estado["fallos_seguidos"] = int(estado.get("fallos_seguidos", 0)) + 1
                estado["ultimo_error"] = " ".join(str(error).split())[:200]
        elif items:
            estado["ultimo_estado"] = "ok"
            estado["ultimo_exito"] = scraped_at
            estado["fallos_seguidos"] = 0
            estado["exitos"] = int(estado.get("exitos", 0)) + 1
            estado.pop("ultimo_error", None)
        else:
            # Cargó bien pero no había nada nuevo que traer: cuenta como turno
            # gastado, así que se refresca la antigüedad y baja la prioridad.
            estado["ultimo_estado"] = "sin_publicaciones"
            estado["ultimo_exito"] = scraped_at
            estado["fallos_seguidos"] = 0

        rotacion[source_id] = estado

    # Olvidar fuentes que ya no están en la configuración.
    limite = ahora - timedelta(days=max(1, conservar_dias))
    vigentes = {
        sid: est
        for sid, est in rotacion.items()
        if _horas_desde(est.get("ultimo_intento"), ahora) <= (ahora - limite).total_seconds() / 3600.0
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"actualizado": scraped_at, "fuentes": vigentes},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return vigentes
