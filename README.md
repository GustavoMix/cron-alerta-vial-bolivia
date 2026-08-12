# V3.2 PREMIUM FAST

Esta edición acelera la ejecución sin cambiar el filtro vial premium:

- 1 solo Chromium compartido.
- 3 páginas Facebook en paralelo.
- 5 webs en paralelo.
- 2 scrolls por página en vez de 5.
- hasta 18 publicaciones recientes por fuente.
- máximo 2 enriquecimientos pesados por fuente.
- dependencias se instalan solo la primera vez.

## En Windows

Primera vez:

`00_PRIMERA_INSTALACION.bat`

Después, para todas las ejecuciones normales:

`01_EJECUTAR_RAPIDO.bat`

El resultado principal sigue siendo:

`data\transito_bolivia.json`

El diagnóstico sigue siendo:

`data\estado_fuentes.json`

---

# Scraper Tránsito Bolivia — V3.2 Premium

La versión V3.2 incorpora un **filtro vial específico para Bolivia**, con puntuación
de relevancia y anti-falsos-positivos. Reconoce bloqueos, movilizaciones que
afectan vías, paros de transporte, trancaderas/embotellamientos, terminales
suspendidas, lluvias/riadas/mazamorras, deterioro de plataforma, accidentes,
desvíos, obras y habilitación de rutas.

Consulta `FILTRO_VIAL_PREMIUM.md` para ver el detalle.

Versión simplificada y corregida.

## Archivos que debes mirar

Solo necesitas estos dos JSON:

- `data/transito_bolivia.json` -> **principal para la app**. Contiene fuentes e incidentes completos.
- `data/estado_fuentes.json` -> **diagnóstico**. Indica qué encontró cada fuente y por qué una publicación fue descartada.

Además:

- `data/transito_bolivia.csv` -> revisión en Excel.
- `data/_interno/incidentes_historial.json` -> historial técnico persistente; la app no necesita leerlo.

La V3.1 elimina automáticamente los JSON antiguos de V2/V3 para no llenar la carpeta `data`.

## Cómo interpretar estado_fuentes.json

Ejemplo:

```json
{
  "raw_items": 2,
  "alerts": 0,
  "rejected": 2,
  "videos_detected": 2,
  "rejected_samples": [
    {
      "reason": "sin_senal_vial_en_el_texto",
      "text_preview": "...",
      "url": "..."
    }
  ]
}
```

Eso significa que Facebook entregó 2 publicaciones y había 2 videos, pero ninguna publicación contenía suficiente información vial en el texto recuperado. Un video detectado no se convierte automáticamente en una alerta vial.

## Mejoras de Facebook V3.1

- Prioriza `div[dir=auto]` y otros nodos de mensaje para recuperar el caption real.
- Filtra botones como Me gusta, Comentar y Compartir.
- Si el texto parece incompleto, abre el enlace público del post para intentar enriquecer descripción e imagen.
- No inicia sesión, no evade CAPTCHA y no extrae MP4 internos.
- Amplía vocabulario vial: hecho de tránsito, siniestro vial, atropello, corte de vía, alcoholemia, doble vía, paso vehicular, etc.

## Datos de cada incidente

Cuando la publicación realmente los menciona, el JSON puede contener:

- departamento, municipio y ciudad
- ruta/carretera/avenida/calle
- sector, puente, cruce y kilómetro
- sentido afectado
- ruta o desvío alternativo
- causa
- cierre total/parcial
- estado actual
- severidad
- vehículos afectados
- coordenadas si fueron publicadas
- historial de cambios
- fuentes que corroboran
- confianza
- icono de la fuente
- fotos
- video/miniatura y enlace público

**Importante:** el scraper no inventa rutas. Si el post solo dice “accidente en Cochabamba” y no nombra una avenida/carretera, `roads` quedará vacío.

## Ejecutar

Doble clic en:

`00_INSTALAR_Y_PROBAR.bat`
