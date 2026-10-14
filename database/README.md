# Base de datos de logs (PostgreSQL)

Esta base guarda dos cosas:

1. **Cada request de predicción:** los inputs del usuario, las features, la predicción de tarifa y de duración, y la latencia en ms.
2. **Un log de errores:** errores de validación, de los modelos o de la API.

```
database/
├── docker-compose.yml     # levanta PostgreSQL 16
├── .env.example           # copiar como .env (no se sube a GitHub)
├── init/
│   ├── 01_schema.sql      # tablas e índices
│   └── 02_procedures.sql  # stored procedures
├── db_client.py           # funciones Python para la API
├── test_db.py             # prueba de humo
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

## 2. Probar

```powershell
pip install -r database/requirements.txt
python database/test_db.py
```

Al final debe salir `Todo OK ✅`. El test borra los registros de prueba que crea.

## 3. Tablas

| Tabla | Una fila por | Columnas clave |
|---|---|---|
| `prediction_logs` | request de predicción | `request_id`, `pickup_datetime`, `pu_location_id`, `do_location_id`, `trip_distance`, features, `predicted_fare_usd`, `predicted_duration_min`, `latency_ms`, `fare_latency_ms`, `duration_latency_ms`, `request_payload` (JSON) |
| `error_logs` | error | `request_id`, `severity` (WARNING/ERROR/CRITICAL), `component`, `endpoint`, `status_code`, `error_type`, `error_message`, `stack_trace` |

`request_id` es el mismo UUID en ambas tablas, así que un error se puede relacionar con su request.

## 4. Stored procedures

En PostgreSQL, los procedures que devuelven datos son `FUNCTION` y se llaman con `SELECT`.

| Procedure | Qué hace |
|---|---|
| `sp_log_prediction(...)` | Registra una predicción. Devuelve `prediction_id` y `request_id` |
| `sp_log_error(...)` | Registra un error. Devuelve `error_id` |
| `sp_get_recent_predictions(limit)` | Últimas N predicciones |
| `sp_get_prediction(request_id)` | Una predicción por su `request_id` |
| `sp_latency_stats(desde, hasta)` | Promedio, p50, p95, p99 y máximo de latencia (por defecto, últimas 24 h) |
| `sp_get_recent_errors(limit)` | Últimos N errores |
| `sp_error_summary(desde, hasta)` | Errores agrupados por tipo y severidad |

Ejemplo en SQL:

```sql
SELECT * FROM sp_log_prediction(
    p_pickup_datetime        => '2022-05-10 08:30',
    p_pu_location_id         => 161,
    p_do_location_id         => 132,
    p_trip_distance          => 17.4,
    p_latency_ms             => 12.3,
    p_predicted_fare_usd     => 52.0,
    p_predicted_duration_min => 38.6
);

SELECT * FROM sp_latency_stats();
```

## 5. Uso desde FastAPI

`db_client.py` se encarga de la conexión. Para usarlo, cópialo a la carpeta de la API o agrega `database/` al `PYTHONPATH`.
Si la base falla, las funciones de escritura **no tumban la API**: registran el problema con `logging` y devuelven `None`.

```python
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import db_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_client.open_pool()
    yield
    db_client.close_pool()


app = FastAPI(lifespan=lifespan)


class TripRequest(BaseModel):
    pickup_datetime: datetime
    PULocationID: int = Field(ge=1, le=265)
    DOLocationID: int = Field(ge=1, le=265)
    trip_distance: float = Field(gt=0)


@app.post("/predict")
def predict(trip: TripRequest, request: Request):
    request_id = uuid.uuid4()
    request.state.request_id = request_id
    features = build_features(trip)               # función de la API

    t0 = time.perf_counter()
    fare = fare_model.predict(features)           # modelos del equipo
    t1 = time.perf_counter()
    duration = duration_model.predict(features)
    t2 = time.perf_counter()

    db_client.log_prediction(
        request_id=request_id,
        pickup_datetime=trip.pickup_datetime,
        pu_location_id=trip.PULocationID,
        do_location_id=trip.DOLocationID,
        trip_distance=trip.trip_distance,
        features=features,
        predicted_fare_usd=fare,
        predicted_duration_min=duration,
        latency_ms=(t2 - t0) * 1000,
        fare_latency_ms=(t1 - t0) * 1000,
        duration_latency_ms=(t2 - t1) * 1000,
        request_payload=trip.model_dump(mode="json"),
        client_source="frontend",
    )
    return {"request_id": str(request_id), "fare_usd": round(fare, 2), "duration_min": round(duration, 1)}


@app.get("/health")
def health():
    return {"api": "ok", "database": "ok" if db_client.ping() else "down"}


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errores = jsonable_encoder(exc.errors())
    db_client.log_error(
        error_type="ValidationError", error_message=str(errores), severity="WARNING",
        component="api", endpoint=request.url.path, http_method=request.method, status_code=422,
    )
    return JSONResponse(status_code=422, content={"detail": errores})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    db_client.log_exception(
        exc, request_id=getattr(request.state, "request_id", None),
        component="api", endpoint=request.url.path, http_method=request.method, status_code=500,
    )
    return JSONResponse(status_code=500, content={"detail": "Error interno"})
```

Notas:

- `db_client` acepta tipos de numpy (por ejemplo, el resultado de `model.predict`) y flags 0/1. Los convierte solo.
- `pickup_datetime` se guarda como hora local de NYC, sin zona horaria.
- `db_client` es síncrono. Úsalo en endpoints `def` (FastAPI los ejecuta en un hilo aparte) o dentro de `run_in_threadpool` si el endpoint es `async def`.
- Lecturas para un dashboard: `get_recent_predictions()`, `latency_stats()`, `get_recent_errors()` y `error_summary()`.

## 6. Conectarse a la base

- **Terminal:** `docker exec -it taxi_db psql -U taxi_app -d taxi_predictions`
- **DBeaver / pgAdmin:** host `localhost`, puerto `5432`, base `taxi_predictions`, usuario y clave los de `database/.env`.

## 7. Comandos útiles

| Acción | Comando (desde `database/`) |
|---|---|
| Detener la base (los datos se conservan) | `docker compose down` |
| Ver logs del contenedor | `docker compose logs -f db` |
| **Reiniciar desde cero** (borra los datos y vuelve a ejecutar `init/`) | `docker compose down -v` y luego `docker compose up -d` |

- Los scripts de `init/` solo se ejecutan cuando el volumen está vacío. Si cambias un `.sql`, reinicia desde cero.
- Si el puerto 5432 ya está ocupado (porque tienes otro PostgreSQL instalado), cambia `POSTGRES_PORT=5433` en `.env`.
