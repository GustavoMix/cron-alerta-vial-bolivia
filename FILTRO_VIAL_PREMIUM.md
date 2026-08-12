# Filtro Vial Premium Bolivia — V3.2

El filtro ya no depende de una lista pequeña de palabras.

## Cómo decide si una publicación es vial

Calcula una puntuación de relevancia (0–100) combinando:

- tipo de incidente detectado
- frases viales directas
- contexto de carretera/tránsito
- carretera, avenida, puente, sector o kilómetro detectado
- palabras y expresiones bolivianas
- prioridad de la fuente
- reglas anti-falsos-positivos

Umbral normal: **55/100**.

## Familias cubiertas

### Bloqueos y conflictos con afectación vial
Bloqueos, puntos de bloqueo, piquetes, barricadas, cerco, trancadera,
medidas de presión, movilizaciones, marchas, protestas, vigilias,
concentraciones y paros de transporte.

Una marcha o protesta genérica NO entra automáticamente: debe existir evidencia
de afectación vial, por ejemplo una avenida, carretera, corte, bloqueo,
congestión, tránsito restringido o desvío.

### Estado de rutas
Cierre total/parcial, corte de ruta, tránsito cortado, paso interrumpido,
sin paso, intransitable, paso restringido, media calzada, paso por turnos,
habilitado, rehabilitado, expedito y transitable con precaución.

### Accidentes
Hecho de tránsito, siniestro vial, choque, colisión, atropello, vuelco,
volcadura, embarrancamiento, encunetamiento, vehículo siniestrado,
vehículo/camión/flota varada, cisterna volcada y carga derramada.

### Lluvias y desastres
Derrumbe, deslizamiento, mazamorra, caída de rocas, desprendimiento, riada,
inundación, anegamiento, desborde, crecida de río, torrentera, nevada,
granizada, helada, hielo, niebla, pérdida de plataforma, socavón,
hundimiento y puente colapsado.

### Tráfico urbano
Congestión vehicular, embotellamiento, trancadera, caos vehicular,
colapso vehicular, largas filas, alto flujo vehicular, tráfico lento,
tráfico pesado y circulación lenta.

### Transporte y terminales
Salidas suspendidas, terminal sin salidas, buses/flotas suspendidas,
transporte interdepartamental y paro de transportistas.

### Obras y desvíos
Obra vial, mantenimiento, asfaltado, bacheo, recapado, rehabilitación,
limpieza de vía, maquinaria pesada, desvío, ruta alternativa y vía alterna.

### Controles
Control vehicular, operativo de tránsito, alcoholemia, control de velocidad,
restricción vehicular y semáforos.

## Anti-falsos-positivos

Se penalizan expresiones como:

- tráfico de drogas/personas/armas
- bloqueo de cuenta/tarjeta/celular
- cierre de campaña/gestión
- accidente laboral/doméstico
- ruta turística/gastronómica

## Diagnóstico

En `data/estado_fuentes.json`, las publicaciones descartadas muestran:

- `reason`
- `relevance_score`
- `filter_reasons`
- `detected_event`
- `text_preview`

Así se puede ajustar el filtro con datos reales sin adivinar.
