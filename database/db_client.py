"""
Cliente de la base de logs (PostgreSQL) para la API de predicción.

Uso típico en FastAPI:

    import db_client

    db_client.open_pool()                      # al iniciar la API
    db_client.log_prediction(...)              # después de predecir
    db_client.log_exception(exc, endpoint=...) # en el manejador de errores
    db_client.close_pool()                     # al apagar la API

Las funciones de escritura NO lanzan excepciones por defecto: si la base falla,
registran el problema con `logging` y devuelven None. Así la API sigue respondiendo.
Usa raise_errors=True en pruebas para ver el error.
"""
from __future__ import annotations

import logging
import os
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

# Lee database/.env. Las variables de entorno que ya existan tienen prioridad.
load_dotenv(Path(__file__).with_name(".env"))

logger = logging.getLogger(__name__)
_pool: ConnectionPool | None = None


# ---------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------
def _conninfo() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return make_conninfo(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "taxi_predictions"),
        user=os.getenv("POSTGRES_USER", "taxi_app"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
        connect_timeout=5,
    )


def open_pool(min_size: int = 1, max_size: int = 5, timeout: float = 10) -> ConnectionPool:
    """Abre el pool de conexiones. Llamar una vez al iniciar la API."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(_conninfo(), min_size=min_size, max_size=max_size, open=True)
        _pool.wait(timeout=timeout)
    return _pool


def close_pool() -> None:
    """Cierra el pool. Llamar al apagar la API."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_pool() -> ConnectionPool:
    return _pool if _pool is not None else open_pool()


def ping() -> bool:
    """True si la base responde (útil para un endpoint /health)."""
    try:
        with get_pool().connection() as conn:
            return conn.execute("SELECT 1").fetchone()[0] == 1
    except Exception:
        logger.exception("La base de datos no responde")
        return False


# ---------------------------------------------------------------------
# Conversión de tipos (numpy / pandas -> tipos nativos de Python)
# ---------------------------------------------------------------------
def _float(v: Any) -> float | None:
    return None if v is None else float(v)


def _int(v: Any) -> int | None:
    return None if v is None else int(v)


def _bool(v: Any) -> bool | None:
    return None if v is None else bool(v)


def _datetime(v: Any) -> Any:
    # La columna guarda hora local de NYC sin zona horaria.
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.replace(tzinfo=None)
    return v


def _jsonb(v: Any) -> Jsonb | None:
    return None if v is None else Jsonb(v)


def _call(function: str, params: dict, fetch: str = "one", raise_errors: bool = False):
    """Ejecuta SELECT ... FROM function(p => valor, ...) solo con los parámetros no nulos."""
    params = {k: v for k, v in params.items() if v is not None}
    args = ", ".join(f"{k} => %({k})s" for k in params)
    sql = f"SELECT * FROM {function}({args})"
    try:
        with get_pool().connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            cur.execute(sql, params)
            return cur.fetchone() if fetch == "one" else cur.fetchall()
    except Exception:
        if raise_errors:
            raise
        logger.exception("Error al ejecutar %s", function)
        return None


# ---------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------
def log_prediction(
    *,
    pickup_datetime: datetime | str,
    pu_location_id: int,
    do_location_id: int,
    trip_distance: float,
    latency_ms: float,
    predicted_fare_usd: float | None = None,
    predicted_duration_min: float | None = None,
    features: dict | None = None,
    fare_latency_ms: float | None = None,
    duration_latency_ms: float | None = None,
    fare_model_version: str | None = None,
    duration_model_version: str | None = None,
    request_payload: dict | None = None,
    request_id: uuid.UUID | str | None = None,
    client_source: str | None = None,
    raise_errors: bool = False,
) -> tuple[int, uuid.UUID] | None:
    """
    Registra una predicción. Devuelve (prediction_id, request_id) o None si falló.

    features: dict con pickup_hour, pickup_dow, is_airport_trip, morning_rush,
              night_rush, weekend_rush (los mismos que recibe el modelo).
    """
    f = features or {}
    row = _call(
        "sp_log_prediction",
        {
            "p_pickup_datetime": _datetime(pickup_datetime),
            "p_pu_location_id": _int(pu_location_id),
            "p_do_location_id": _int(do_location_id),
            "p_trip_distance": _float(trip_distance),
            "p_latency_ms": _float(latency_ms),
            "p_predicted_fare_usd": _float(predicted_fare_usd),
            "p_predicted_duration_min": _float(predicted_duration_min),
            "p_pickup_hour": _int(f.get("pickup_hour")),
            "p_pickup_dow": _int(f.get("pickup_dow")),
            "p_is_airport_trip": _bool(f.get("is_airport_trip")),
            "p_morning_rush": _bool(f.get("morning_rush")),
            "p_night_rush": _bool(f.get("night_rush")),
            "p_weekend_rush": _bool(f.get("weekend_rush")),
            "p_fare_latency_ms": _float(fare_latency_ms),
            "p_duration_latency_ms": _float(duration_latency_ms),
            "p_fare_model_version": fare_model_version,
            "p_duration_model_version": duration_model_version,
            "p_request_payload": _jsonb(request_payload),
            "p_request_id": request_id,
            "p_client_source": client_source,
        },
        raise_errors=raise_errors,
    )
    return None if row is None else (row["prediction_id"], row["request_id"])


def log_error(
    *,
    error_type: str,
    error_message: str,
    severity: str = "ERROR",
    request_id: uuid.UUID | str | None = None,
    component: str | None = None,
    endpoint: str | None = None,
    http_method: str | None = None,
    status_code: int | None = None,
    stack_trace: str | None = None,
    request_payload: dict | None = None,
    client_source: str | None = None,
    raise_errors: bool = False,
) -> int | None:
    """Registra un error. severity: WARNING, ERROR o CRITICAL. Devuelve error_id o None."""
    row = _call(
        "sp_log_error",
        {
            "p_error_type": error_type,
            "p_error_message": error_message,
            "p_severity": severity,
            "p_request_id": request_id,
            "p_component": component,
            "p_endpoint": endpoint,
            "p_http_method": http_method,
            "p_status_code": _int(status_code),
            "p_stack_trace": stack_trace,
            "p_request_payload": _jsonb(request_payload),
            "p_client_source": client_source,
        },
        raise_errors=raise_errors,
    )
    return None if row is None else row["sp_log_error"]


def log_exception(exc: BaseException, **kwargs) -> int | None:
    """Atajo para registrar una excepción con su tipo, mensaje y traceback."""
    return log_error(
        error_type=type(exc).__name__,
        error_message=str(exc) or repr(exc),
        stack_trace="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        **kwargs,
    )


# ---------------------------------------------------------------------
# Lectura / monitoreo (devuelven listas de dicts)
# ---------------------------------------------------------------------
def get_recent_predictions(limit: int = 50) -> list[dict]:
    return _call("sp_get_recent_predictions", {"p_limit": limit}, fetch="all", raise_errors=True)


def get_prediction(request_id: uuid.UUID | str) -> dict | None:
    return _call("sp_get_prediction", {"p_request_id": request_id}, raise_errors=True)


def latency_stats(date_from: datetime | None = None, date_to: datetime | None = None) -> dict:
    return _call("sp_latency_stats", {"p_from": date_from, "p_to": date_to}, raise_errors=True)


def get_recent_errors(limit: int = 50) -> list[dict]:
    return _call("sp_get_recent_errors", {"p_limit": limit}, fetch="all", raise_errors=True)


def error_summary(date_from: datetime | None = None, date_to: datetime | None = None) -> list[dict]:
    return _call("sp_error_summary", {"p_from": date_from, "p_to": date_to}, fetch="all", raise_errors=True)
