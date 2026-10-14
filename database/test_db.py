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


def main() -> None:
    db_client.open_pool()
    try:
        print("1. Conexión")
        assert db_client.ping(), "La base no responde"
        ok("la base responde")

        print("2. Registrar predicción completa")
        rid = uuid.uuid4()
        payload = {"pickup_datetime": "2022-05-10 08:30:00", "PULocationID": 161, "DOLocationID": 132, "trip_distance": 17.4}
        res = db_client.log_prediction(
            pickup_datetime=datetime(2022, 5, 10, 8, 30),
            pu_location_id=161,
            do_location_id=132,
            trip_distance=17.4,
            latency_ms=12.345,
            predicted_fare_usd=52.0,
            predicted_duration_min=38.6,
            features={"pickup_hour": 8, "pickup_dow": 1, "is_airport_trip": 1,
                      "morning_rush": 1, "night_rush": 0, "weekend_rush": 0},
            fare_latency_ms=5.1,
            duration_latency_ms=6.2,
            fare_model_version="fare_v1",
            duration_model_version="duration_v1",
            request_payload=payload,
            request_id=rid,
            client_source=SOURCE,
            raise_errors=True,
        )
        assert res is not None and res[1] == rid
        fila = db_client.get_prediction(rid)
        assert float(fila["predicted_fare_usd"]) == 52.0 and fila["is_airport_trip"] is True
        assert fila["request_payload"] == payload
        ok(f"prediction_id={res[0]}, request_id={res[1]}")

        print("3. Solo tarifa, sin request_id (la base genera uno) y tipos numpy")
        try:
            import numpy as np
            fare, dist, zone = np.float32(9.75), np.float64(1.8), np.int64(237)
        except ImportError:
            fare, dist, zone = 9.75, 1.8, 237
        res2 = db_client.log_prediction(
            pickup_datetime=datetime(2022, 5, 14, 13, 5, tzinfo=timezone.utc),
            pu_location_id=zone, do_location_id=236, trip_distance=dist,
            latency_ms=3, predicted_fare_usd=fare, client_source=SOURCE, raise_errors=True,
        )
        assert res2 is not None and isinstance(res2[1], uuid.UUID)
        ok(f"request_id generado: {res2[1]}")

        print("4. La base rechaza datos inválidos sin tumbar la API")
        logging.getLogger(db_client.__name__).setLevel(logging.CRITICAL)
        malo = db_client.log_prediction(
            pickup_datetime="2022-05-10 08:30", pu_location_id=999, do_location_id=1,
            trip_distance=1, latency_ms=1, predicted_fare_usd=5, client_source=SOURCE,
        )
        sin_pred = db_client.log_prediction(
            pickup_datetime="2022-05-10 08:30", pu_location_id=1, do_location_id=1,
            trip_distance=1, latency_ms=1, client_source=SOURCE,
        )
        logging.getLogger(db_client.__name__).setLevel(logging.NOTSET)
        assert malo is None and sin_pred is None
        ok("zona 999 y request sin predicciones rechazados (devuelve None)")

        print("5. Registrar errores")
        eid = db_client.log_error(
            error_type="ValidationError", error_message="PULocationID fuera de rango",
            severity="warning", request_id=rid, component="api", endpoint="/predict",
            http_method="post", status_code=422, request_payload={"PULocationID": 999},
            client_source=SOURCE, raise_errors=True,
        )
        try:
            1 / 0
        except ZeroDivisionError as exc:
            eid2 = db_client.log_exception(exc, component="fare_model", endpoint="/predict",
                                           status_code=500, client_source=SOURCE, raise_errors=True)
        errores = db_client.get_recent_errors(5)
        assert {eid, eid2} <= {e["error_id"] for e in errores}
        assert next(e for e in errores if e["error_id"] == eid)["severity"] == "WARNING"
        assert "ZeroDivisionError" in next(e for e in errores if e["error_id"] == eid2)["stack_trace"]
        ok(f"error_ids={eid}, {eid2}")

        print("6. Consultas de monitoreo")
        stats = db_client.latency_stats(datetime.now(timezone.utc) - timedelta(minutes=5))
        assert stats["total_requests"] >= 2
        ok(f"latencia: {stats}")
        resumen = db_client.error_summary()
        assert any(r["error_type"] == "ZeroDivisionError" for r in resumen)
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
