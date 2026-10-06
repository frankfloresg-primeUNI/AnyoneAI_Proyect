# AnyoneAI_Proyect

Repositorio donde trabajaran los miembros del grupo 1 para el proyecto de tarifas y tiempo en taxis en NYC


## Datos

- Data limpia (lista para modelar): `data/processed/train.csv.gz`, `val.csv.gz`, `test.csv.gz`
  - Se leen con `pd.read_csv("data/processed/train.csv.gz", parse_dates=["pickup_datetime"])`
  - `muestra_train.csv`: 10,000 filas de train para revisar en Excel
  - `limpieza_log.csv`: filas eliminadas por cada regla de limpieza
- Data cruda (no está en el repo): descargar de
  https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2022-05.parquet
  y guardarla en `data/` para ejecutar `notebooks/01_limpieza_preprocesamiento.ipynb`.
