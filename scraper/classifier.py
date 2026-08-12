import hashlib
import re
import unicodedata
from typing import List, Optional, Tuple, Dict, Any
from .models import RawItem, Alert


# ================================================================
# FILTRO VIAL PREMIUM - BOLIVIA
# ================================================================
# No depende de una sola palabra. Calcula relevancia combinando:
# - evento/incidente
# - contexto vial
# - afectación al tránsito
# - ubicación vial
# - fuente
# - anti-falsos-positivos
#
# El objetivo es capturar vocabulario realmente usado en Bolivia:
# puntos de bloqueo, medidas de presión, cerco, piquetes, trancadera,
# salidas suspendidas, carretera antigua/nueva, RVF, riada, mazamorra,
# pérdida de plataforma, vehículos varados, etc.


EVENT_PATTERNS = [
    ("bloqueo", [
        r"\bbloque(?:o|os|ado|ada|ados|adas)\b",
        r"\bbloquea(?:n)?\b",
        r"\bdesbloqueo\b",
        r"\bpuntos? de bloqueo\b",
        r"\bpiquetes?\b",
        r"\bbarricadas?\b",
        r"\bcerco (?:vial|a la ciudad|carretero)\b",
        r"\bcaminos? bloqueados?\b",
        r"\brutas? bloqueadas?\b",
        r"\bv[ií]as? bloqueadas?\b",
        r"\btrancadera\b",
    ]),
    ("movilizacion_vial", [
        r"\bmovilizaci[oó]n(?:es)?\b",
        r"\bmarcha(?:s)?\b",
        r"\bmanifestaci[oó]n(?:es)?\b",
        r"\bprotesta(?:s)?\b",
        r"\bmedidas? de presi[oó]n\b",
        r"\bvigilia(?:s)?\b",
        r"\bconcentraci[oó]n(?:es)?\b",
        r"\bcabildo\b",
        r"\bsector(?:es)? movilizad",
        r"\bcampesinos? movilizad",
        r"\btransportistas? movilizad",
    ]),
    ("paro_transporte", [
        r"\bparo (?:de |del )?transporte\b",
        r"\bparo (?:de )?transportistas\b",
        r"\bparo (?:c[ií]vico|indefinido|movilizado)\b",
        r"\bhuelga (?:de )?transport",
        r"\bsuspensi[oó]n (?:del )?servicio de transporte\b",
    ]),
    ("terminal_suspendida", [
        r"\bsalidas? suspendidas?\b",
        r"\bsuspend(?:en|ieron|idas?) (?:las )?salidas\b",
        r"\bno hay salidas\b",
        r"\bterminal(?:es)? (?:cerrada|cerrado|sin salidas)\b",
        r"\bsuspendido el transporte interdepartamental\b",
        r"\bflotas? suspendidas?\b",
    ]),
    ("accidente", [
        r"\baccidente(?:s)?\b",
        r"\bhecho(?:s)? de tr[aá]nsito\b",
        r"\bsiniestro(?:s)? vial(?:es)?\b",
        r"\bchoque(?:s)?\b",
        r"\bcolisi[oó]n(?:es)?\b",
        r"\batropell",
        r"\bimpacto vehicular\b",
        r"\bchoque frontal\b",
        r"\bchoque m[uú]ltiple\b",
        r"\bvuelco\b",
        r"\bvolcadura\b",
        r"\bembarranc",
        r"\bencunet",
        r"\bveh[ií]culo siniestrado\b",
        r"\bveh[ií]culo volcado\b",
    ]),
    ("vehiculo_obstruyendo", [
        r"\bveh[ií]culo varado\b",
        r"\bcami[oó]n varado\b",
        r"\bflota varada\b",
        r"\bcisterna volcad",
        r"\bcarga derramada\b",
        r"\bveh[ií]culo incendiado\b",
        r"\bincendio vehicular\b",
    ]),
    ("derrumbe", [
        r"\bderrumbe(?:s)?\b",
        r"\bdeslizamiento(?:s)?\b",
        r"\bmazamorra(?:s)?\b",
        r"\bca[ií]da de (?:tierra|rocas?|piedras?)\b",
        r"\bdesprendimiento de (?:tierra|rocas?|material)\b",
        r"\balud\b",
    ]),
    ("deterioro_vial", [
        r"\bp[eé]rdida de plataforma\b",
        r"\bplataforma (?:cedi[oó]|cedida|colapsada)\b",
        r"\bhundimiento\b",
        r"\bsocav[oó]n\b",
        r"\bsocavamiento\b",
        r"\bpuente (?:colapsado|dañado|afectado)\b",
        r"\bcalzada (?:dañada|deteriorada)\b",
        r"\bbaches?\b",
        r"\bmal estado de la (?:v[ií]a|carretera|ruta)\b",
    ]),
    ("inundacion", [
        r"\binundaci[oó]n(?:es)?\b",
        r"\banegamiento(?:s)?\b",
        r"\bdesborde(?:s)?\b",
        r"\briada(?:s)?\b",
        r"\bcrecida (?:del |de )?r[ií]o\b",
        r"\btorrentera(?:s)?\b",
        r"\bpaso de agua\b",
    ]),
    ("clima_vial", [
        r"\bnevada(?:s)?\b",
        r"\bnieve\b",
        r"\bgranizada(?:s)?\b",
        r"\bhelada(?:s)?\b",
        r"\bhielo en (?:la )?(?:v[ií]a|carretera|calzada)\b",
        r"\blluvias? intensas?\b",
        r"\bprecipitaciones? intensas?\b",
        r"\bniebla densa\b",
        r"\bvisibilidad reducida\b",
    ]),
    ("cierre_vial", [
        r"\bcierre (?:total |temporal |preventivo |parcial |programado )?(?:de |en )?(?:la |el )?(?:v[ií]a|ruta|carretera|avenida|calle|puente|tramo|acceso)",
        r"\bcorte (?:total |temporal |preventivo |parcial |programado )?(?:de |en )?(?:la |el )?(?:v[ií]a|ruta|carretera|avenida|calle|puente|tramo|tr[aá]nsito)",
        r"\btr[aá]nsito cortado\b",
        r"\bpaso cortado\b",
        r"\bpaso interrumpido\b",
        r"\bsin paso vehicular\b",
        r"\bno hay paso\b",
        r"\bv[ií]a cerrada\b",
        r"\bruta cerrada\b",
        r"\bcarretera cerrada\b",
    ]),
    ("desvio", [
        r"\bdesv[ií]o(?:s)?\b",
        r"\bruta(?:s)? alternativa(?:s)?\b",
        r"\bv[ií]a(?:s)? alternativa(?:s)?\b",
        r"\brutas? alternas?\b",
        r"\bcirculaci[oó]n por v[ií]as alternas\b",
    ]),
    ("obras", [
        r"\bobra(?:s)? vial(?:es)?\b",
        r"\bmantenimiento (?:vial|de carretera|de ruta)\b",
        r"\brehabilitaci[oó]n (?:vial|de la v[ií]a|de carretera)\b",
        r"\basfalt",
        r"\bbacheo\b",
        r"\brecapado\b",
        r"\breparaci[oó]n (?:de la v[ií]a|de carretera|del puente)\b",
        r"\blimpieza de (?:la )?(?:v[ií]a|carretera|ruta)\b",
        r"\bmaquinaria pesada\b",
    ]),
    ("congestion", [
        r"\bcongesti[oó]n(?: vehicular)?\b",
        r"\btr[aá]fico (?:lento|pesado|vehicular|intenso|congestionado)\b",
        r"\bembotellamiento(?:s)?\b",
        r"\btrancadera\b",
        r"\bcaos vehicular\b",
        r"\bcolapso vehicular\b",
        r"\bfilas? de veh[ií]culos\b",
        r"\blargas? filas\b",
        r"\balto flujo vehicular\b",
        r"\bflujo vehicular lento\b",
        r"\bcirculaci[oó]n lenta\b",
    ]),
    ("control_transito", [
        r"\bcontrol vehicular\b",
        r"\boperativo (?:de )?tr[aá]nsito\b",
        r"\bcontrol de tr[aá]fico\b",
        r"\bcontrol de alcoholemia\b",
        r"\balcoholemia\b",
        r"\boperativo vehicular\b",
        r"\bcontrol de velocidad\b",
        r"\brestricci[oó]n vehicular\b",
        r"\bplacas pares?\b",
        r"\bplacas impares?\b",
    ]),
    ("semaforo", [
        r"\bsem[aá]foro(?:s)?\b",
        r"\bsemaforizaci[oó]n\b",
        r"\bsem[aá]foro fuera de servicio\b",
    ]),
    ("habilitacion", [
        r"\bhabilitad[ao]s?\b",
        r"\brehabilitad[ao]s?\b",
        r"\brestableci[oó].{0,35}(?:tr[aá]nsito|circulaci[oó]n|ruta|v[ií]a|paso)\b",
        r"\bexpedit[ao]s?\b",
        r"\bpaso normalizado\b",
        r"\bcirculaci[oó]n normalizada\b",
        r"\bse levant[oó] el bloqueo\b",
        r"\blevantan el bloqueo\b",
    ]),
    ("precaucion", [
        r"\btransitable con precauci[oó]n\b",
        r"\bcircular con precauci[oó]n\b",
        r"\bprecauci[oó]n al circular\b",
        r"\bpaso con precauci[oó]n\b",
    ]),
]


STATUS_PATTERNS = [
    ("habilitado", [
        r"\bhabilitad[ao]s?\b", r"\brehabilitad[ao]s?\b", r"\bexpedit[ao]s?\b",
        r"\brestablecid[ao]s?\b", r"\bnormalidad\b", r"\bpaso normalizado\b",
        r"\bcirculaci[oó]n normalizada\b", r"\bse levant[oó] el bloqueo\b",
    ]),
    ("cerrado", [
        r"\bcierre total\b", r"\bintransitable\b", r"\bcerrad[ao]s?\b",
        r"\bbloquead[ao]s?\b", r"\bsuspendid[ao] el tr[aá]nsito\b",
        r"\btr[aá]nsito cortado\b", r"\bpaso interrumpido\b", r"\bsin paso\b",
        r"\bno hay paso\b", r"\bsalidas? suspendidas?\b",
    ]),
    ("restringido", [
        r"\brestricci[oó]n\b", r"\bpaso restringido\b", r"\bmedia calzada\b",
        r"\bparcial\b", r"\bun solo carril\b", r"\bun carril\b",
        r"\bpaso por turnos\b", r"\bpaso controlado\b",
    ]),
    ("precaucion", [
        r"\bprecauci[oó]n\b", r"\btr[aá]nsito lento\b", r"\bcircular con cuidado\b",
        r"\bvisibilidad reducida\b", r"\bcalzada resbaladiza\b",
    ]),
]


# Señales de contexto vial. Cuantas más aparezcan, más probable que sea relevante.
ROAD_CONTEXT_PATTERNS = [
    r"\bcarretera(?:s)?\b", r"\bruta(?:s)?\b", r"\bv[ií]a(?:s)?\b",
    r"\bavenida(?:s)?\b", r"\bav\.?\b", r"\bcalle(?:s)?\b",
    r"\bpuente(?:s)?\b", r"\btramo(?:s)?\b", r"\bautopista\b",
    r"\bdoble v[ií]a\b", r"\bred vial fundamental\b", r"\brvf\b",
    r"\btransitabilidad\b", r"\btr[aá]nsito\b", r"\btr[aá]fico\b",
    r"\bcirculaci[oó]n\b", r"\bflujo vehicular\b", r"\bpaso vehicular\b",
    r"\blibre tr[aá]nsito\b", r"\bcalzada\b", r"\bcarril(?:es)?\b",
    r"\bintersecci[oó]n\b", r"\brotonda\b", r"\bredondel\b",
    r"\bdistribuidor\b", r"\banillo\b", r"\bradial\b", r"\bacceso(?:s)?\b",
    r"\bsalida(?:s)?\b", r"\bingreso(?:s)?\b", r"\bkil[oó]metro\b", r"\bkm\.?\b",
    r"\bterminal(?:es)?(?: de buses)?\b", r"\bbuses?\b", r"\bflotas?\b",
    r"\btransporte interdepartamental\b", r"\btransporte p[uú]blico\b",
    r"\bveh[ií]culos?\b", r"\bconductores?\b", r"\btransportistas?\b",
    r"\bcarretera antigua\b", r"\bcarretera nueva\b",
]


# Frases que por sí mismas casi garantizan afectación vial.
DIRECT_VIAL_PHRASES = [
    r"\bpuntos? de bloqueo\b",
    r"\bbloqueo de (?:carretera|ruta|v[ií]a|avenida|calle)\b",
    r"\bbloquea(?:n)? (?:la |el |las |los )?(?:carretera|ruta|v[ií]a|avenida|calle|puente|tr[aá]nsito)\b",
    r"\brutas? bloqueadas?\b",
    r"\bcarreteras? bloqueadas?\b",
    r"\bv[ií]as? bloqueadas?\b",
    r"\bcorte de ruta\b",
    r"\bcorte de tr[aá]nsito\b",
    r"\btr[aá]nsito cortado\b",
    r"\bpaso interrumpido\b",
    r"\bsin paso vehicular\b",
    r"\bno hay paso\b",
    r"\bintransitable\b",
    r"\bsalidas? suspendidas?\b",
    r"\btransporte interdepartamental suspendido\b",
    r"\bcirculaci[oó]n restringida\b",
    r"\bpaso restringido\b",
    r"\bpaso por turnos\b",
    r"\btransitable con precauci[oó]n\b",
    r"\bveh[ií]culos? varados?\b",
    r"\bpasajeros? varados?\b",
    r"\btrancadera\b",
    r"\bembotellamiento\b",
    r"\bcaos vehicular\b",
]


# Movilizaciones/protestas deben combinarse con contexto vial salvo
# casos muy claros de paro de transporte.
SOCIAL_ACTION_PATTERNS = [
    r"\bmovilizaci[oó]n(?:es)?\b", r"\bmarcha(?:s)?\b", r"\bprotesta(?:s)?\b",
    r"\bmanifestaci[oó]n(?:es)?\b", r"\bmedidas? de presi[oó]n\b",
    r"\bvigilia(?:s)?\b", r"\bconcentraci[oó]n(?:es)?\b", r"\bpiquete(?:s)?\b",
    r"\bcerco\b", r"\bcabildo\b", r"\bparo\b", r"\bhuelga\b",
]


# Señales negativas: palabras que pueden parecer viales pero no lo son.
NEGATIVE_PATTERNS = [
    r"\btr[aá]fico de drogas\b",
    r"\btr[aá]fico de sustancias\b",
    r"\btr[aá]fico de personas\b",
    r"\btr[aá]fico de armas\b",
    r"\btr[aá]fico il[ií]cito\b",
    r"\bbloqueo de cuenta\b",
    r"\bbloqueo de tarjeta\b",
    r"\bbloqueo de celular\b",
    r"\bbloqueo de redes\b",
    r"\bcierre de campa[nñ]a\b",
    r"\bcierre de gesti[oó]n\b",
    r"\bcierre de inscripciones\b",
    r"\baccidente laboral\b",
    r"\baccidente dom[eé]stico\b",
    r"\baccidente cerebrovascular\b",
    r"\bruta tur[ií]stica\b",
    r"\bruta gastron[oó]mica\b",
    r"\bruta educativa\b",
    r"\bpuente a[eé]reo\b",
]


KEY_TERMS = [
    # bloqueos / conflicto
    "bloqueo", "bloqueos", "desbloqueo", "punto de bloqueo", "puntos de bloqueo",
    "piquete", "piquetes", "barricada", "barricadas", "cerco", "trancadera",
    "medida de presión", "medidas de presión", "movilización", "movilizaciones",
    "marcha", "marchas", "protesta", "protestas", "manifestación", "vigilia",
    "concentración", "paro", "paro transporte", "paro de transportistas",
    "campesinos movilizados", "transportistas movilizados",

    # cierre / estado
    "cierre", "cierre total", "cierre parcial", "corte de vía", "corte de ruta",
    "corte de tránsito", "tránsito cortado", "paso interrumpido", "sin paso",
    "no hay paso", "intransitable", "cerrado", "habilitado", "rehabilitado",
    "expedito", "paso restringido", "paso por turnos", "media calzada",
    "circulación restringida", "transitable con precaución", "libre tránsito",

    # accidentes
    "accidente", "hecho de tránsito", "siniestro vial", "choque", "colisión",
    "atropello", "vuelco", "volcadura", "embarrancamiento", "encunetamiento",
    "vehículo varado", "vehículos varados", "cisterna volcada", "carga derramada",

    # fenómenos / carretera
    "derrumbe", "deslizamiento", "mazamorra", "caída de rocas", "riada",
    "inundación", "anegamiento", "desborde", "crecida de río", "torrentera",
    "nevada", "nieve", "granizada", "helada", "hielo en la vía", "niebla",
    "pérdida de plataforma", "plataforma cedida", "hundimiento", "socavón",
    "socavamiento", "puente colapsado", "mal estado de la vía", "bache",

    # tráfico urbano
    "tráfico", "tránsito", "congestión", "congestión vehicular", "embotellamiento",
    "caos vehicular", "colapso vehicular", "fila de vehículos", "largas filas",
    "alto flujo vehicular", "flujo vehicular", "circulación lenta",

    # infraestructura / ubicación
    "carretera", "ruta", "avenida", "calle", "puente", "tramo", "doble vía",
    "autopista", "anillo", "radial", "rotonda", "redondel", "distribuidor",
    "intersección", "acceso", "salida", "ingreso", "kilómetro", "km",
    "red vial fundamental", "rvf", "transitabilidad",

    # desvío / obras
    "desvío", "ruta alternativa", "vía alternativa", "vía alterna",
    "obra vial", "mantenimiento vial", "asfaltado", "bacheo", "recapado",
    "rehabilitación vial", "limpieza de vía", "maquinaria pesada",

    # terminales / transporte
    "salidas suspendidas", "salida de buses", "terminal de buses",
    "transporte interdepartamental", "flotas", "buses", "transportistas",

    # controles
    "control vehicular", "operativo de tránsito", "control de tráfico",
    "alcoholemia", "control de velocidad", "restricción vehicular",

    # semáforos
    "semáforo", "semaforización",
]


DEPT_ALIASES = {
    "La Paz": [
        "la paz", "el alto", "yungas", "achocalla", "viacha", "patacamaya",
        "desaguadero", "copacabana", "caranavi", "chulumani", "sica sica",
        "konani", "achica arriba", "batallas", "tiwanaku", "guaqui",
        "palos blancos", "la asunta", "coroico", "yolosa", "rio seco", "río seco",
    ],
    "Cochabamba": [
        "cochabamba", "sacaba", "quillacollo", "sipe sipe", "parotani",
        "chapare", "chimoré", "chimore", "villa tunari", "colomi", "paracti",
        "tiraque", "vinto", "colcapirhua", "punata", "cliza", "mizque",
        "cruce vacas", "bulo bulo", "entre ríos", "entre rios",
    ],
    "Santa Cruz": [
        "santa cruz", "montero", "warnes", "cotoca", "la guardia", "el torno",
        "guarayos", "san ignacio de velasco", "camiri", "yapacaní", "yapacani",
        "mineros", "portachuelo", "san julián", "san julian", "cuatro cañadas",
        "paila", "la ramada", "plan 3000", "doble vía a la guardia",
        "carretera al norte", "valles cruceños", "san josé de chiquitos",
    ],
}

CITY_ALIASES = {
    "La Paz": ["ciudad de la paz", "la paz"],
    "El Alto": ["el alto"],
    "Cochabamba": ["ciudad de cochabamba", "cochabamba"],
    "Sacaba": ["sacaba"],
    "Quillacollo": ["quillacollo"],
    "Santa Cruz de la Sierra": ["santa cruz de la sierra"],
    "Montero": ["montero"],
    "Warnes": ["warnes"],
    "La Guardia": ["la guardia"],
    "Cotoca": ["cotoca"],
}

MUNICIPALITY_ALIASES = {
    "La Paz": ["municipio de la paz", "ciudad de la paz"],
    "El Alto": ["municipio de el alto", "el alto"],
    "Viacha": ["viacha"],
    "Achocalla": ["achocalla"],
    "Patacamaya": ["patacamaya"],
    "Caranavi": ["caranavi"],
    "Cochabamba": ["municipio de cochabamba", "cercado", "ciudad de cochabamba"],
    "Sacaba": ["sacaba"],
    "Quillacollo": ["quillacollo"],
    "Sipe Sipe": ["sipe sipe"],
    "Villa Tunari": ["villa tunari"],
    "Vinto": ["vinto"],
    "Santa Cruz de la Sierra": ["santa cruz de la sierra"],
    "Warnes": ["warnes"],
    "Montero": ["montero"],
    "La Guardia": ["la guardia"],
    "Cotoca": ["cotoca"],
    "El Torno": ["el torno"],
    "Portachuelo": ["portachuelo"],
    "San Julián": ["san julián", "san julian"],
}

CAUSE_PATTERNS = [
    ("protesta_bloqueo", [
        r"\bprotesta\b", r"\bparo\b", r"\bmovilizaci[oó]n\b",
        r"\bsector(?:es)? movilizad", r"\bmedidas? de presi[oó]n\b",
        r"\bdemanda(?:s)?\b", r"\bpiquetes?\b", r"\bvigilia\b", r"\bcerco\b",
    ]),
    ("conflicto_transporte", [
        r"\btransportistas?\b", r"\bmototaxistas?\b", r"\bchoferes?\b",
        r"\bsindicato de transporte\b", r"\bfederaci[oó]n de transport",
    ]),
    ("accidente", [
        r"\baccidente\b", r"\bchoque\b", r"\bcolisi[oó]n\b", r"\bvuelco\b",
        r"\batropell", r"\bembarranc",
    ]),
    ("lluvia", [
        r"\blluvia", r"\bprecipitaci[oó]n", r"\btormenta", r"\btemporal\b",
    ]),
    ("nieve_hielo", [
        r"\bnevada\b", r"\bnieve\b", r"\bhelada\b", r"\bhielo\b",
    ]),
    ("derrumbe_deslizamiento", [
        r"\bderrumbe\b", r"\bdeslizamiento\b", r"\bmazamorra\b",
        r"\bca[ií]da de rocas", r"\bdesprendimiento\b",
    ]),
    ("inundacion_riada", [
        r"\binundaci[oó]n\b", r"\banegamiento\b", r"\bdesborde\b",
        r"\briada\b", r"\bcrecida\b",
    ]),
    ("deterioro_vial", [
        r"\bp[eé]rdida de plataforma\b", r"\bsocav[oó]n\b",
        r"\bhundimiento\b", r"\bmal estado de la v[ií]a\b",
    ]),
    ("obras_mantenimiento", [
        r"\bobra(?:s)?\b", r"\bmantenimiento\b", r"\basfalt",
        r"\brehabilitaci[oó]n", r"\bbacheo\b", r"\brecapado\b",
    ]),
    ("evento", [
        r"\bentrada folkl[oó]rica\b", r"\bdesfile\b", r"\bprocesi[oó]n\b",
        r"\bevento deportivo\b", r"\bmarat[oó]n\b", r"\bferia\b",
    ]),
]


ROAD_RE = re.compile(
    r"\b(?:ruta(?: nacional)?|rn\.?|rf\.?|carretera(?: antigua| nueva)?|avenida|av\.?|calle|puente|tramo|doble v[ií]a|autopista|diagonal|distribuidor|anillo|radial)\s+"
    r"[^\n,.;:]{2,150}?"
    r"(?=\s+(?:sector|zona|altura de|desde|hasta|se encuentra|est[aá]|permanece|debido|por|entre|km|kil[oó]metro)\b|[,.;:]|$)",
    re.IGNORECASE,
)
SECTOR_RE = re.compile(
    r"\b(?:sector|zona|altura de|intersecci[oó]n de|altura del?|cruce|puente|tranca|surtidor|localidad|comunidad)\s+"
    r"[^\n,.;:]{1,110}?"
    r"(?=\s+(?:desde|hasta|se encuentra|est[aá]|permanece|debido|por|con|km|kil[oó]metro)\b|[,.;:]|$)",
    re.IGNORECASE,
)
KM_RE = re.compile(r"\b(?:km\.?|kil[oó]metro)\s*\d+(?:[.,]\d+)?(?:\s*(?:al|a|-|–)\s*(?:km\.?\s*)?\d+(?:[.,]\d+)?)?\b", re.I)
TIME_RE = re.compile(r"\b(?:2[0-3]|[01]?\d):[0-5]\d\b|\b(?:desde|hasta)\s+las?\s+(?:2[0-3]|[01]?\d)(?::[0-5]\d)?\b", re.I)
COORD_RE = re.compile(r"(?<!\d)(-?(?:1?[0-9]|[1-8][0-9]|90)\.\d{4,8})\s*[,;/]\s*(-?(?:1?[0-7][0-9]|[1-9]?[0-9]|180)\.\d{4,8})(?!\d)")

DIRECTION_PATTERNS = [
    re.compile(r"\b(?:sentido|direcci[oó]n)\s+([^,.;]{3,80})", re.I),
    re.compile(r"\b([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ .-]{2,40})\s*(?:→|->|hacia|a)\s*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ .-]{2,40})", re.I),
    re.compile(r"\bambos sentidos\b", re.I),
]

ALT_ROUTE_PATTERNS = [
    re.compile(r"\b(?:ruta|v[ií]a|desv[ií]o) alternativa(?: recomendada)?\s*[:\-]?\s*([^.;\n]{4,170})", re.I),
    re.compile(r"\b(?:se recomienda|recomiendan|utilizar|usar|circular por|desviar por|desv[ií]o por|tomar)\s+([^.;\n]{4,170})", re.I),
]

VEHICLE_PATTERNS = {
    "todos": [r"\btodo tipo de veh[ií]culos\b", r"\btr[aá]nsito vehicular\b"],
    "transporte_pesado": [r"\btransporte pesado\b", r"\bveh[ií]culos pesados\b", r"\bcamiones\b", r"\btractocamiones\b"],
    "buses": [r"\bbuses\b", r"\bflotas\b", r"\btransporte interdepartamental\b"],
    "transporte_publico": [r"\btransporte p[uú]blico\b", r"\bmicros\b", r"\bminibuses\b", r"\btrufis\b"],
    "motocicletas": [r"\bmotocicletas?\b", r"\bmotos\b", r"\bmototaxistas?\b"],
    "particulares": [r"\bveh[ií]culos particulares\b", r"\bautom[oó]viles\b"],
}


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", " ", s).strip()


def norm_lower(s: str) -> str:
    return normalize(s).lower()


def _unique(items: List[str], limit: int) -> List[str]:
    out = []
    seen = set()
    for x in items:
        x = normalize(x).strip(" ,.;:-")
        k = x.lower()
        if x and k not in seen:
            seen.add(k)
            out.append(x)
        if len(out) >= limit:
            break
    return out


def _count_matches(patterns: List[str], text: str) -> int:
    return sum(1 for p in patterns if re.search(p, text, re.I))


def detect_event(text: str) -> str:
    t = norm_lower(text)
    scored = []
    for idx, (event, patterns) in enumerate(EVENT_PATTERNS):
        hits = _count_matches(patterns, t)
        if hits:
            # Bloqueo/cierre/directos ganan sobre movilización genérica.
            priority = {
                "bloqueo": 20, "cierre_vial": 19, "terminal_suspendida": 18,
                "accidente": 17, "derrumbe": 16, "inundacion": 15,
                "deterioro_vial": 14, "vehiculo_obstruyendo": 13,
                "congestion": 12, "paro_transporte": 11, "desvio": 10,
                "obras": 9, "clima_vial": 8, "movilizacion_vial": 7,
                "control_transito": 6, "semaforo": 5, "habilitacion": 4,
                "precaucion": 3,
            }.get(event, 0)
            scored.append((hits, priority, -idx, event))
    if not scored:
        return "otro"
    scored.sort(reverse=True)
    return scored[0][3]


def detect_status(text: str, event_type: str) -> str:
    t = norm_lower(text)
    for status, patterns in STATUS_PATTERNS:
        if any(re.search(p, t, re.I) for p in patterns):
            return status
    if event_type in {"bloqueo", "terminal_suspendida", "cierre_vial"}:
        return "cerrado"
    if event_type in {"derrumbe", "inundacion", "accidente", "congestion", "deterioro_vial", "clima_vial"}:
        return "precaucion"
    if event_type in {"movilizacion_vial", "paro_transporte"}:
        return "restringido"
    return "desconocido"


def detect_department(text: str, hint: Optional[str]) -> Optional[str]:
    t = norm_lower(text)
    best, best_hits = None, 0
    for dept, names in DEPT_ALIASES.items():
        hits = sum(1 for x in names if x in t)
        if hits > best_hits:
            best, best_hits = dept, hits
    return best or hint


def detect_city(text: str, hint: Optional[str]) -> Optional[str]:
    t = norm_lower(text)
    for city, names in sorted(CITY_ALIASES.items(), key=lambda x: max(map(len, x[1])), reverse=True):
        if any(x in t for x in names):
            return city
    return hint


def detect_municipality(text: str, city: Optional[str]) -> Optional[str]:
    t = norm_lower(text)
    for municipality, names in sorted(MUNICIPALITY_ALIASES.items(), key=lambda x: max(map(len, x[1])), reverse=True):
        if any(x in t for x in names):
            return municipality
    return city


def detect_cause(text: str, event: str) -> Optional[str]:
    t = norm_lower(text)
    for cause, patterns in CAUSE_PATTERNS:
        if any(re.search(p, t, re.I) for p in patterns):
            return cause
    if event == "accidente":
        return "accidente"
    if event == "derrumbe":
        return "derrumbe_deslizamiento"
    if event == "inundacion":
        return "inundacion_riada"
    if event == "deterioro_vial":
        return "deterioro_vial"
    return None


def detect_closure_scope(text: str, status: str) -> Optional[str]:
    t = norm_lower(text)
    if re.search(r"\b(?:cierre|bloqueo) total\b|\bambos sentidos\b|\bintransitable\b|\bsin paso\b|\bno hay paso\b", t):
        return "total"
    if re.search(r"\bparcial\b|\bmedia calzada\b|\bun carril\b|\bun solo carril\b|\bpaso restringido\b|\bpaso por turnos\b", t):
        return "parcial"
    if status == "habilitado":
        return "sin_cierre"
    return None


def extract_terms(text: str) -> Tuple[List[str], List[str], List[str], List[str], List[str], List[str], List[str], List[str]]:
    clean = normalize(text)
    roads = [m.group(0) for m in ROAD_RE.finditer(clean)]
    places = [m.group(0) for m in SECTOR_RE.finditer(clean)]
    kms = [m.group(0) for m in KM_RE.finditer(clean)]
    times = [m.group(0) for m in TIME_RE.finditer(clean)]

    directions = []
    for pat in DIRECTION_PATTERNS:
        for m in pat.finditer(clean):
            if m.lastindex == 2:
                directions.append(f"{m.group(1).strip()} -> {m.group(2).strip()}")
            elif m.lastindex:
                directions.append(m.group(1).strip())
            else:
                directions.append(m.group(0).strip())

    alternatives = []
    for pat in ALT_ROUTE_PATTERNS:
        for m in pat.finditer(clean):
            alternatives.append(m.group(1).strip())

    affected = []
    low = clean.lower()
    for vehicle, patterns in VEHICLE_PATTERNS.items():
        if any(re.search(p, low, re.I) for p in patterns):
            affected.append(vehicle)

    keywords = [kw for kw in KEY_TERMS if kw in low]
    return (
        _unique(roads, 12), _unique(places, 12), _unique(kms, 10),
        _unique(directions, 8), _unique(alternatives, 10),
        _unique(affected, 10), _unique(times, 12), _unique(keywords, 35),
    )


def relevance_for(item: RawItem, text: str, event: str, roads: List[str], places: List[str], kms: List[str], keywords: List[str]) -> Dict[str, Any]:
    """
    Puntuación 0-100.
    55+ => entra como alerta vial.
    45-54 => entra solo si es fuente oficial tier 1 y tiene evento fuerte.
    """
    t = norm_lower(text)
    score = 0
    reasons = []

    negative_hits = _count_matches(NEGATIVE_PATTERNS, t)
    if negative_hits:
        score -= min(70, 45 + 10 * (negative_hits - 1))
        reasons.append(f"anti_falso_positivo:{negative_hits}")

    direct_hits = _count_matches(DIRECT_VIAL_PHRASES, t)
    if direct_hits:
        score += min(45, 28 + 6 * (direct_hits - 1))
        reasons.append(f"frase_vial_directa:{direct_hits}")

    context_hits = _count_matches(ROAD_CONTEXT_PATTERNS, t)
    if context_hits:
        score += min(30, context_hits * 5)
        reasons.append(f"contexto_vial:{context_hits}")

    event_bonus = {
        "bloqueo": 30, "cierre_vial": 30, "terminal_suspendida": 28,
        "accidente": 26, "derrumbe": 28, "inundacion": 27,
        "deterioro_vial": 24, "vehiculo_obstruyendo": 22,
        "congestion": 24, "paro_transporte": 22, "desvio": 22,
        "obras": 18, "clima_vial": 18, "movilizacion_vial": 14,
        "control_transito": 16, "semaforo": 12, "habilitacion": 20,
        "precaucion": 12, "otro": 0,
    }.get(event, 0)
    score += event_bonus
    if event_bonus:
        reasons.append(f"evento:{event}")

    if roads:
        score += min(18, 9 + 3 * (len(roads) - 1))
        reasons.append(f"via_detectada:{len(roads)}")
    if places:
        score += min(10, 5 + 2 * (len(places) - 1))
        reasons.append(f"sector_detectado:{len(places)}")
    if kms:
        score += 8
        reasons.append("kilometro_detectado")

    if len(keywords) >= 2:
        score += min(10, 2 + len(keywords))
        reasons.append(f"terminos_viales:{len(keywords)}")

    social_hits = _count_matches(SOCIAL_ACTION_PATTERNS, t)
    if social_hits:
        reasons.append(f"accion_social:{social_hits}")
        # Una marcha/protesta sin señales viales no debe entrar automáticamente.
        if event == "movilizacion_vial" and context_hits == 0 and direct_hits == 0 and not roads:
            score -= 28
            reasons.append("movilizacion_sin_afectacion_vial_clara")

    # Fuentes oficiales ayudan, pero no convierten cualquier publicación en vial.
    if item.tier == 1:
        score += 5
        reasons.append("fuente_oficial_facebook")
    elif item.tier == 2:
        score += 3
        reasons.append("fuente_oficial_web")

    score = max(0, min(100, score))
    accepted = score >= 55
    if not accepted and item.tier == 1 and score >= 45 and event in {
        "bloqueo","cierre_vial","terminal_suspendida","accidente","derrumbe",
        "inundacion","congestion","paro_transporte","deterioro_vial"
    }:
        accepted = True
        reasons.append("umbral_oficial_reducido")

    return {
        "score": score,
        "accepted": accepted,
        "reasons": reasons,
        "negative_hits": negative_hits,
        "context_hits": context_hits,
        "direct_hits": direct_hits,
    }


def extract_coordinates(text: str) -> Tuple[Optional[float], Optional[float]]:
    for m in COORD_RE.finditer(text or ""):
        lat, lon = float(m.group(1)), float(m.group(2))
        if -23.5 <= lat <= -9.0 and -70.5 <= lon <= -56.5:
            return lat, lon
        if -23.5 <= lon <= -9.0 and -70.5 <= lat <= -56.5:
            return lon, lat
    return None, None


def location_query_for(roads, places, municipality, city, dept) -> Optional[str]:
    parts = []
    if roads:
        parts.append(roads[0])
    elif places:
        parts.append(places[0])
    for x in [municipality, city, dept, "Bolivia"]:
        if x and x not in parts:
            parts.append(x)
    return ", ".join(parts) if parts else None


def severity_for(event: str, status: str, text: str) -> str:
    t = norm_lower(text)
    critical_markers = [
        "fallecidos", "múltiples fallecidos", "puente colapsado", "pérdida total de plataforma",
        "aislado", "incomunicado", "sin paso por varios días",
    ]
    if any(x in t for x in critical_markers):
        return "critica"
    high_markers = [
        "cierre total", "intransitable", "fallecido", "heridos", "derrumbe",
        "mazamorra", "deslizamiento", "bloqueo indefinido", "ambos sentidos",
        "suspendidas las salidas", "no hay paso", "pasajeros varados",
        "vehículos varados", "vehiculos varados",
    ]
    if any(x in t for x in high_markers):
        return "alta"
    if event in {
        "bloqueo", "accidente", "cierre_vial", "inundacion", "derrumbe",
        "terminal_suspendida", "deterioro_vial", "vehiculo_obstruyendo"
    }:
        return "media"
    if status == "restringido" or event in {"congestion","movilizacion_vial","paro_transporte"}:
        return "media"
    return "baja"


def confidence_for(item: RawItem, event: str, dept: Optional[str], keywords: List[str], roads: List[str], relevance_score: int) -> float:
    score = 0.36
    if item.tier == 1:
        score += 0.24
    elif item.tier == 2:
        score += 0.18
    elif item.tier == 3:
        score += 0.07
    if event != "otro":
        score += 0.10
    if dept:
        score += 0.06
    if roads:
        score += 0.06
    if len(keywords) >= 2:
        score += 0.03
    if item.published_at:
        score += 0.03
    score += min(0.10, relevance_score / 1000.0)
    return round(min(score, 0.99), 2)


def title_from(item: RawItem, event: str, dept: Optional[str]) -> str:
    base = normalize(item.title)
    if base and len(base) >= 12:
        return base[:220]
    txt = normalize(item.text)
    first = re.split(r"(?<=[.!?])\s+", txt)[0]
    if len(first) > 20:
        return first[:220]
    return f"{event.replace('_', ' ').title()} - {dept or item.region_hint or 'Bolivia'}"


def analyze_relevance(item: RawItem) -> Dict[str, Any]:
    text = normalize(item.text)
    if len(text) < 20:
        return {
            "accepted": False, "score": 0, "event": "otro",
            "reason": "texto_muy_corto", "reasons": ["texto_muy_corto"],
        }

    event = detect_event(text)
    roads, places, kms, directions, alternatives, affected, times, keywords = extract_terms(text)
    rel = relevance_for(item, text, event, roads, places, kms, keywords)

    reason = "aceptable" if rel["accepted"] else "relevancia_vial_insuficiente"
    if rel["negative_hits"] and rel["score"] < 55:
        reason = "posible_falso_positivo_no_vial"
    elif event == "movilizacion_vial" and not rel["accepted"]:
        reason = "movilizacion_sin_afectacion_vial_clara"
    elif event == "otro" and not keywords:
        reason = "sin_senal_vial_en_el_texto"

    return {
        **rel,
        "event": event,
        "reason": reason,
        "roads": roads,
        "places": places,
        "kms": kms,
        "directions": directions,
        "alternatives": alternatives,
        "affected": affected,
        "times": times,
        "keywords": keywords,
    }


def rejection_reason(item: RawItem) -> str:
    return analyze_relevance(item)["reason"]


def build_alert(item: RawItem, scraped_at: str) -> Optional[Alert]:
    text = normalize(item.text)
    analysis = analyze_relevance(item)
    if not analysis["accepted"]:
        return None

    event = analysis["event"]
    roads = analysis["roads"]
    places = analysis["places"]
    kms = analysis["kms"]
    directions = analysis["directions"]
    alternatives = analysis["alternatives"]
    affected = analysis["affected"]
    times = analysis["times"]
    keywords = analysis["keywords"]

    dept = detect_department(text, item.region_hint)
    city = detect_city(text, item.city_hint)
    municipality = detect_municipality(text, city)
    status = detect_status(text, event)
    cause = detect_cause(text, event)
    closure_scope = detect_closure_scope(text, status)
    severity = severity_for(event, status, text)
    confidence = confidence_for(item, event, dept, keywords, roads, analysis["score"])
    lat, lon = extract_coordinates(text)
    location_query = location_query_for(roads, places, municipality, city, dept)

    unique_base = f"{item.source_id}|{item.item_url}|{text[:500]}"
    uid = hashlib.sha1(unique_base.encode("utf-8")).hexdigest()[:16]

    return Alert(
        id=uid,
        source_id=item.source_id,
        source_name=item.source_name,
        source_url=item.source_url,
        source_class=item.source_class,
        source_tier=item.tier,
        source_icon_url=item.source_icon_url,
        url=item.item_url or item.source_url,
        published_at=item.published_at,
        scraped_at=scraped_at,
        department=dept,
        municipality=municipality,
        city=city,
        event_type=event,
        cause=cause,
        status=status,
        closure_scope=closure_scope,
        severity=severity,
        confidence=confidence,
        relevance_score=analysis["score"],
        filter_reasons=analysis["reasons"],
        title=title_from(item, event, dept),
        description=text[:5000],
        original_text=text[:12000],
        roads=roads,
        places=places,
        kilometer_mentions=kms,
        directions=directions,
        alternative_routes=alternatives,
        affected_vehicles=affected,
        time_mentions=times,
        keywords=keywords,
        latitude=lat,
        longitude=lon,
        location_query=location_query,
        image_urls=item.image_urls or [],
        video_url=item.video_url,
        video_thumbnail_url=item.video_thumbnail_url,
        video_type=item.video_type,
        is_official=(item.tier in {1, 2}),
    )
