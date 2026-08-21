from datetime import datetime
from zoneinfo import ZoneInfo

from scraper.planificador import actualizar_rotacion, planificar_grupos, puntaje

TZ = ZoneInfo("America/La_Paz")


def _fuente(id_, tier=1):
    return {"id": id_, "name": id_, "url": f"https://facebook.com/{id_}", "tier": tier}


def test_fuente_nunca_vista_gana_a_una_con_exito_reciente():
    fuentes = [_fuente("nueva"), _fuente("reciente")]
    ahora = datetime.now(TZ)
    rotacion = {
        "reciente": {"ultimo_exito": (ahora).isoformat(timespec="seconds"), "exitos": 5},
    }
    assert puntaje(fuentes[0], rotacion, ahora) > puntaje(fuentes[1], rotacion, ahora)


def test_bloqueo_permanente_no_acapara_el_primer_turno():
    """Una fuente sin éxitos y con muchos bloqueos seguidos (Facebook le exige
    sesión siempre, no es cuestión de IP) no debe ganarle el turno 0 a una
    fuente que sí es recuperable, aunque esta última ya haya tenido éxito
    hace poco."""
    muerta = _fuente("muerta")
    recuperable = _fuente("recuperable")
    ahora = datetime.now(TZ)
    rotacion = {
        "muerta": {
            "ultimo_intento": ahora.isoformat(timespec="seconds"),
            "exitos": 0,
            "bloqueos": 11,
        },
        "recuperable": {
            "ultimo_exito": ahora.isoformat(timespec="seconds"),
            "exitos": 3,
            "bloqueos": 2,
        },
    }
    grupos = planificar_grupos([muerta, recuperable], rotacion, tamano_grupo=2, ahora=ahora)
    assert len(grupos) == 1
    primero = grupos[0]["fuentes"].split(",")[0]
    assert primero == "recuperable"


def test_bloqueo_permanente_sigue_intentandose_no_se_descarta():
    muerta = _fuente("muerta")
    ahora = datetime.now(TZ)
    rotacion = {"muerta": {"ultimo_intento": ahora.isoformat(timespec="seconds"), "exitos": 0, "bloqueos": 11}}
    grupos = planificar_grupos([muerta], rotacion, tamano_grupo=2, ahora=ahora)
    assert grupos[0]["fuentes"] == "muerta"


def test_actualizar_rotacion_marca_bloqueo_sin_penalizar_como_fallo_propio():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rot.json"
        ahora = datetime.now(TZ).isoformat(timespec="seconds")
        resultados = {
            "x": {"items": [], "error": "Facebook bloqueó/ocultó el contenido público para esta ejecución."}
        }
        estado = actualizar_rotacion(path, resultados, ahora)
        assert estado["x"]["ultimo_estado"] == "bloqueada"
        assert estado["x"]["bloqueos"] == 1
        assert estado["x"].get("fallos_seguidos", 0) == 0
