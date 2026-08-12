# GitHub Actions — versión lista para cron

## Qué ejecutar

El workflow está en:

`.github/workflows/actualizar.yml`

Se ejecuta:

- manualmente con `workflow_dispatch`
- automáticamente cada 30 minutos con `13,43 * * * *`

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
