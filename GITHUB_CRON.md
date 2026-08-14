# GitHub Actions — versión lista para cron

## Qué ejecutar

El workflow está en:

`.github/workflows/actualizar.yml`

Se ejecuta:

- manualmente con `workflow_dispatch`
- automáticamente cada 30 minutos con `13,43 * * * *`

## Estrategia de IPs (por qué el workflow tiene varios jobs)

Facebook deja pasar ~2 fuentes por IP en una misma corrida antes de degradar
el contenido (te devuelve un login wall o solo el `og:description` en vez del
post real). Meter más trucos dentro de un solo job (más scrolls, otro
user-agent, etc.) no cambia eso: la IP sigue siendo la misma.

La mitigación es repartir las ~30 páginas Facebook en grupos chicos
(`FB_GROUP_SIZE`, por defecto 2) y correr cada grupo en su **propio job** de
GitHub Actions. Cada job usa un runner efímero distinto, y cada runner sale a
internet con su propia IP — así que más grupos = más IPs reales, no más
trucos por job.

El workflow queda en 4 jobs:

1. **plan** — lee `config/sources.yaml` y arma la matriz de grupos
   (`scripts/plan_scrape_groups.py`).
2. **scrape-facebook** — un job por grupo (matrix), cada uno con
   `python -m scraper.runner --mode scrape --only <ids> --partial-out ...`.
   Sube el resultado como artifact. `fail-fast: false` para que un grupo
   bloqueado no cancele a los demás.
3. **scrape-web** — scrapea las fuentes web (no dependen de IP de Facebook),
   con `--only-type generic_web`.
4. **merge** — descarga todos los artifacts (`partial-*`), combina alertas y
   estadísticas con `--mode merge`, escribe `data/` y hace el commit/push.
   Corre con `if: always()` para no perder lo que sí se pudo scrapear aunque
   algún grupo haya fallado.

Para ajustar cuántas fuentes van por IP, cambia `FB_GROUP_SIZE` en el `env:`
del workflow (menos = más jobs pero menos riesgo de bloqueo por grupo).

## Archivos que guarda en GitHub

- `data/transito_bolivia.json`
- `data/transito_bolivia.csv`
- `data/estado_fuentes.json`
- `data/_interno/incidentes_historial.json`

El último archivo es importante porque permite conservar el historial de incidentes entre ejecuciones.

## Antes de depender del cron

1. Sube todo el proyecto.
2. Abre la pestaña **Actions**.
3. Selecciona **Actualizar tránsito Bolivia**.
4. Ejecuta **Run workflow** una vez manualmente.
5. Comprueba que termine en verde.
6. Revisa que los archivos de `data/` hayan sido creados/actualizados.

## Repositorio privado

Puede ser privado. El workflow usa el `GITHUB_TOKEN` del propio repositorio y `contents: write` para guardar los resultados.

Si la rama principal tiene reglas de protección que impiden pushes directos de GitHub Actions, el paso `git push` puede fallar y tendrás que ajustar esas reglas.
