# Base de datos de logs (PostgreSQL)

La base guarda dos cosas:

1. **Cada request de predicción:** los 8 campos que recibe el modelo, la tarifa, la duración y el total predichos, y la latencia de los modelos y del request completo.
2. **Errores y eventos:** caídas de OSRM y errores inesperados; los 422 también se guardan, como INFO, para tener trazabilidad.

```
database/
├── docker-compose.yml           # levanta PostgreSQL 16
├── .env.example                 # copiar como .env (no se sube a GitHub)
├── init/
│   ├── 01_schema.sql            # tablas e índices
│   └── 02_procedures.sql        # stored procedures
├── db_client.py                 # funciones Python para la API
├── ejemplo_integracion_main.py  # api/main.py con la integración (probado)
├── test_db.py                   # prueba de humo
└── requirements.txt
```

## 1. Levantar la base

Requisito: tener Docker Desktop abierto.

```powershell
cd database
copy .env.example .env        # luego cambia POSTGRES_PASSWORD dentro de .env
docker compose up -d
docker compose ps             # STATUS debe decir "healthy"
cd ..
```

Las tablas y los procedures se crean solos la **primera vez** que se levanta el contenedor.
Si cambian los `.sql`, hay que reiniciar desde cero: `docker compose down -v` y luego `docker compose up -d`.

## 2. Probar

```powershell
pip install -r database/requirements.txt
python database/test_db.py
```

Al final debe salir `Todo OK ✅`. El test borra los registros de prueba que crea.

## 3. Tablas

### `prediction_logs`: una fila por predicción

| Grupo | Columnas |
|---|---|
| Identificación | `prediction_id`, `request_id` (UUID), `created_at`, `pickup_datetime` |
| **8 inputs del modelo** (obligatorios) | `pu_location_id`, `do_location_id`, `pickup_hour`, `pickup_dow`, `is_airport_trip`, `morning_rush`, `night_rush`, `weekend_rush` |
| Información extra (no entra al modelo) | `estimated_distance_miles`, `request_payload` (JSON con coordenadas, passenger_count, etc.) |
| Predicciones | `predicted_fare_usd`, `predicted_duration_min`, `predicted_total_amount_usd`, `model_version` |
| Latencia (ms) | `model_latency_ms` (los dos modelos), `total_latency_ms` (todo `/predict`, incluye OSRM), `fare_latency_ms`, `duration_latency_ms` |

### `error_logs`: una fila por error o evento

`request_id`, `severity`, `component`, `endpoint`, `http_method`, `status_code`, `error_type`, `error_message`, `stack_trace`, `request_payload`.

| Severidad | Cuándo | Ejemplo |
|---|---|---|
| `INFO` | Fuera de alcance, no es error | 422: coordenadas fuera de NYC, body inválido |
| `WARNING` | Anomalía que no es caída | OSRM no encontró ruta (400) |
| `ERROR` | Falla real | OSRM caído (503/504), error del modelo, error inesperado (500) |
| `CRITICAL` | El sistema no puede responder | — |

`request_id` es el mismo UUID en las dos tablas, así que un error se puede relacionar con su request.

## 4. Stored procedures

En PostgreSQL, los procedures que devuelven datos son `FUNCTION` y se llaman con `SELECT`.

| Procedure | Qué hace |
|---|---|
| `sp_log_prediction(...)` | Registra una predicción. Devuelve `prediction_id` y `request_id` |
| `sp_log_error(...)` | Registra un error o evento. Devuelve `error_id` |
| `sp_get_recent_predictions(limit)` | Últimas N predicciones |
| `sp_get_prediction(request_id)` | Una predicción por su `request_id` |
| `sp_latency_stats(desde, hasta)` | Promedio, p50, p95, p99 y máximo por métrica: `total_request`, `models`, `fare_model`, `duration_model` |
| `sp_get_recent_errors(limit)` | Últimos N errores o eventos |
| `sp_error_summary(desde, hasta)` | Errores agrupados por tipo y severidad |

## 5. Guía de integración con la API (FastAPI)

**Ejemplo completo y probado:** `database/ejemplo_integracion_main.py`. Las líneas nuevas están marcadas con `# [BD]`.

### Requisitos

- Agregar `psycopg[binary,pool]>=3.1` al `requirements.txt` de la raíz (`python-dotenv` ya está).
- Ejecutar la API desde la raíz del repo (`uvicorn api.main:app --reload`) e importar con `from database import db_client`.
- La base debe estar levantada y con su `database/.env`. Si la base está caída, la API **sigue respondiendo**: el registro falla, se anota con `logging` y la predicción sale igual.

### Iniciar y cerrar la conexión

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db_client.open_pool()
    yield
    db_client.close_pool()

app = FastAPI(lifespan=lifespan)
```

### `db_client.log_prediction(...)`

Se llama al final de `/predict`, después de predecir.

| Parámetro | Tipo | Obligatorio | Qué es |
|---|---|:---:|---|
| `features` | dict | ✅ | El **mismo dict que recibe el modelo** (salida de `build_features`). Debe tener los 8 campos. Si hay claves extra, se ignoran |
| `pickup_datetime` | datetime | ✅ | `trip.pickup_datetime` |
| `model_latency_ms` | float | ✅ | Tiempo de los dos modelos |
| `total_latency_ms` | float | ✅ | Tiempo total de `/predict` |
| `predicted_fare_usd` | float | * | Tarifa predicha |
| `predicted_duration_min` | float | * | Duración predicha |
| `predicted_total_amount_usd` | float | | Tarifa + cargos |
| `fare_latency_ms`, `duration_latency_ms` | float | | Tiempo de cada modelo |
| `estimated_distance_miles` | float | | Distancia que se muestra en el front |
| `model_version` | str | | Ej. `"mock"`, `"v1"` |
| `request_payload` | dict | | `trip.model_dump(mode="json")` |
| `request_id` | UUID | | Si no se manda, la base genera uno |
| `client_source` | str | | `"frontend"`, `"swagger"`, etc. |

\* Al menos una de las dos predicciones. Los tipos de numpy (por ejemplo, la salida de `model.predict`) y los flags 0/1 se convierten solos.

```python
db_client.log_prediction(
    request_id=request_id,
    pickup_datetime=trip.pickup_datetime,
    features=features,
    predicted_fare_usd=fare_amount,
    predicted_duration_min=trip_duration_min,
    predicted_total_amount_usd=total_amount,
    model_latency_ms=(t_fin_modelos - t_modelos) * 1000,
    fare_latency_ms=(t_fare - t_modelos) * 1000,
    duration_latency_ms=(t_fin_modelos - t_fare) * 1000,
    total_latency_ms=(time.perf_counter() - t_inicio) * 1000,
    estimated_distance_miles=distance_miles,
    model_version=MODEL_VERSION,
    request_payload=payload,
    client_source="frontend",
)
```

### `db_client.log_error(...)` y `db_client.log_exception(exc, ...)`

| Parámetro | Tipo | Obligatorio | Qué es |
|---|---|:---:|---|
| `error_type` | str | ✅ | Ej. `"OutOfServiceAreaError"`, `"OSRMError"` |
| `error_message` | str | ✅ | Mensaje del error |
| `severity` | str | | `INFO`, `WARNING`, `ERROR` (default) o `CRITICAL` |
| `request_id` | UUID | | El mismo del request |
| `component` | str | | `api`, `zones`, `osrm`, `fare_model`, `duration_model` |
| `endpoint`, `http_method`, `status_code` | str / str / int | | Ej. `"/predict"`, `"POST"`, `422` |
| `request_payload` | dict | | Body del request |
| `stack_trace` | str | | Traceback (`log_exception` lo llena solo) |

`log_exception(exc, ...)` llena `error_type`, `error_message` y `stack_trace` a partir de la excepción. Acepta los demás parámetros igual que `log_error`.

```python
# Coordenadas fuera de NYC -> INFO
except (InvalidCoordinatesError, OutOfServiceAreaError) as error:
    db_client.log_error(
        error_type=type(error).__name__, error_message=str(error), severity="INFO",
        request_id=request_id, component="zones", endpoint="/predict", http_method="POST",
        status_code=422, request_payload=payload,
    )
    raise HTTPException(status_code=422, detail=str(error)) from error

# OSRM caído -> ERROR (get_route ya lanza HTTPException 503/504/400)
except HTTPException as error:
    db_client.log_error(
        error_type="OSRMError", error_message=str(error.detail),
        severity="ERROR" if error.status_code >= 500 else "WARNING",
        request_id=request_id, component="osrm", endpoint="/predict", http_method="POST",
        status_code=error.status_code, request_payload=payload,
    )
    raise
```

Como la distancia ya no entra al modelo, si OSRM falla también se podría seguir con la predicción y mostrar la distancia como "no disponible". Eso lo decide el equipo.

Los manejadores globales para body inválido (422) y errores inesperados (500) están al final de `ejemplo_integracion_main.py`.

### Lecturas para un dashboard (opcional)

`get_recent_predictions(limit)`, `get_prediction(request_id)`, `latency_stats()`, `get_recent_errors(limit)` y `error_summary()` devuelven listas de dicts. Se pueden exponer como endpoints `GET` si el frontend las necesita.

## 6. Conectarse a la base

- **Terminal:** `docker exec -it taxi_db psql -U taxi_app -d taxi_predictions` (dentro: `\dt` lista las tablas y `\q` sale)
- **DBeaver / extensión PostgreSQL de VS Code:** host `localhost`, puerto `5432`, base `taxi_predictions`, usuario y clave los de `database/.env`.

## 7. Comandos útiles

| Acción | Comando (desde `database/`) |
|---|---|
| Detener la base (los datos se conservan) | `docker compose stop` |
| Volver a encenderla | `docker compose start` |
| Ver los logs del contenedor | `docker compose logs -f db` |
| **Reiniciar desde cero** (borra los datos y vuelve a ejecutar `init/`) | `docker compose down -v` y luego `docker compose up -d` |

- El puerto solo es accesible desde tu PC (`127.0.0.1`).
- Si el puerto 5432 ya está ocupado (porque tienes otro PostgreSQL instalado), cambia `POSTGRES_PORT=5433` en `.env`.
