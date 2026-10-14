# AnyoneAI_Proyect

Repositorio donde trabajaran los miembros del grupo 1 para el proyecto de tarifas y tiempo en taxis en NYC


## Datos

Data limpia en parquet, un dataset por target:

- `data/processed/amount/` → train / val / test para `fare_amount` (USD)
- `data/processed/trip_duration/` → train / val / test para `trip_duration_min` (minutos)
- `data/processed/limpieza_log.csv` → filas eliminadas por cada regla

Split: train 1–21, val 22–26, test 27–31 de mayo 2022.

Data cruda (no está en el repo): descargar de
https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2022-05.parquet
y guardarla en `data/` para ejecutar `notebooks/01_limpieza_preprocesamiento.ipynb`.
