"""
Prueba de humo de la base de logs.

Requisitos: contenedor levantado (docker compose up -d) y database/.env creado.
Ejecutar desde la raíz del proyecto:

    python database/test_db.py

Inserta registros de prueba (client_source='smoke_test'), verifica todo y luego los borra.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

import db_client

SOURCE = "smoke_test"
ok = lambda msg: print(f"  ✅ {msg}")

# Mismo formato que devuelve build_features() de la API (flags como 0/1)
FEATURES = {
    "PULocationID": 161, "DOLocationID": 132, "pickup_hour": 8, "pickup_dow": 1,
    "is_airport_trip": 1, "morning_rush": 1, "night_rush": 0, "weekend_rush": 0,
}


def main() -> None:
    db_client.open_pool()
    try:
        print("1. Conexión")
        assert db_client.ping(), "La base no responde"
        ok("la base responde")

        print("2. Registrar predicción completa")
        rid = uuid.uuid4()
        payload = {"pickup": {"lat": 40.758, "lon": -73.985}, "dropoff": {"lat": 40.641, "lon": -73.778},
                   "pickup_datetime": "2022-05-10T08:30:00", "passenger_count": 1}
        res = db_client.log_prediction(
            features=FEATURES,
            pickup_datetime=datetime(2022, 5, 10, 8, 30),
            predicted_fare_usd=52.0,
            predicted_duration_min=38.6,
            predicted_total_amount_usd=59.5,
            model_latency_ms=11.3,
            fare_latency_ms=5.1,
            duration_latency_ms=6.2,
            total_latency_ms=245.8,
            estimated_distance_miles=17.4,
            model_version="v1",
            request_payload=payload,
            request_id=rid,
            client_source=SOURCE,
            raise_errors=True,
        )
        assert res is not None and res[1] == rid
        fila = db_client.get_prediction(rid)
        assert fila["is_airport_trip"] is True and fila["night_rush"] is False
        assert float(fila["predicted_total_amount_usd"]) == 59.5 and fila["request_payload"] == payload
        ok(f"prediction_id={res[0]}, request_id={res[1]}")

        print("3. Mínimo obligatorio, sin distancia, tipos numpy, la base genera el request_id")
        try:
            import numpy as np
            fare, zone = np.float32(9.75), np.int64(237)
        except ImportError:
            fare, zone = 9.75, 237
        res2 = db_client.log_prediction(
            features={**FEATURES, "PULocationID": zone, "is_airport_trip": 0, "trip_distance": 99},
            pickup_datetime=datetime(2022, 5, 14, 13, 5, tzinfo=timezone.utc),
            predicted_fare_usd=fare, model_latency_ms=3, total_latency_ms=4,
            client_source=SOURCE, raise_errors=True,
        )
        assert res2 is not None and isinstance(res2[1], uuid.UUID)
        assert db_client.get_prediction(res2[1])["estimated_distance_miles"] is None
        ok(f"request_id generado: {res2[1]}")

        print("4. Datos inválidos: se rechazan sin tumbar la API")
        logging.getLogger(db_client.__name__).setLevel(logging.CRITICAL)
        sin_campo = db_client.log_prediction(
            features={k: v for k, v in FEATURES.items() if k != "night_rush"},
            pickup_datetime="2022-05-10 08:30", predicted_fare_usd=5,
            model_latency_ms=1, total_latency_ms=1, client_source=SOURCE,
        )
        zona_mala = db_client.log_prediction(
            features={**FEATURES, "PULocationID": 999}, pickup_datetime="2022-05-10 08:30",
            predicted_fare_usd=5, model_latency_ms=1, total_latency_ms=1, client_source=SOURCE,
        )
        sin_pred = db_client.log_prediction(
            features=FEATURES, pickup_datetime="2022-05-10 08:30",
            model_latency_ms=1, total_latency_ms=1, client_source=SOURCE,
        )
        logging.getLogger(db_client.__name__).setLevel(logging.NOTSET)
        assert sin_campo is None and zona_mala is None and sin_pred is None
        ok("falta un campo / zona 999 / sin predicciones → devuelve None")

        print("5. Registrar errores y eventos")
        eid_info = db_client.log_error(
            error_type="OutOfServiceAreaError", error_message="(41.5, -74.0) is outside the NYC taxi service area",
            severity="info", request_id=rid, component="zones", endpoint="/predict",
            http_method="post", status_code=422, request_payload={"pickup": {"lat": 41.5, "lon": -74.0}},
            client_source=SOURCE, raise_errors=True,
        )
        eid_osrm = db_client.log_error(
            error_type="OSRMError", error_message="No fue posible conectar con OSRM",
            request_id=rid, component="osrm", endpoint="/predict", http_method="POST",
            status_code=503, client_source=SOURCE, raise_errors=True,
        )
        try:
            1 / 0
        except ZeroDivisionError as exc:
            eid_exc = db_client.log_exception(exc, component="fare_model", endpoint="/predict",
                                              status_code=500, client_source=SOURCE, raise_errors=True)
        errores = {e["error_id"]: e for e in db_client.get_recent_errors(10)}
        assert errores[eid_info]["severity"] == "INFO"
        assert errores[eid_osrm]["severity"] == "ERROR"
        assert "ZeroDivisionError" in errores[eid_exc]["stack_trace"]
        ok(f"error_ids={eid_info} (INFO), {eid_osrm} (ERROR), {eid_exc} (ERROR con traceback)")

        print("6. Consultas de monitoreo")
        stats = {s["metric"]: s for s in db_client.latency_stats(datetime.now(timezone.utc) - timedelta(minutes=5))}
        assert stats["total_request"]["requests"] >= 2 and stats["models"]["requests"] >= 2
        for s in stats.values():
            ok(f"latencia {s['metric']:<15} n={s['requests']}  avg={s['avg_ms']} ms  p95={s['p95_ms']} ms")
        resumen = db_client.error_summary()
        assert any(r["severity"] == "INFO" for r in resumen)
        ok(f"resumen de errores: {[(r['error_type'], r['severity'], r['total']) for r in resumen]}")
        assert len(db_client.get_recent_predictions(10)) >= 2
        ok("historial de predicciones")

        print("\nTodo OK ✅")
    finally:
        with db_client.get_pool().connection() as conn:
            conn.execute("DELETE FROM prediction_logs WHERE client_source = %s", (SOURCE,))
            conn.execute("DELETE FROM error_logs WHERE client_source = %s", (SOURCE,))
        db_client.close_pool()


if __name__ == "__main__":
    main()
