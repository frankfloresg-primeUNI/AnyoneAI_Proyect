"""
Demo para la exposición: llena la base con viajes de EJEMPLO y la muestra como tablas.
Usa las mismas funciones que va a usar la API (db_client.log_prediction / log_error).

Ejecutar desde la raíz del proyecto, con la base levantada:

    python database/demo_presentacion.py            # inserta los ejemplos y muestra las tablas
    python database/demo_presentacion.py --ver      # solo muestra lo que hay
    python database/demo_presentacion.py --borrar   # borra los ejemplos de la demo

Las tarifas y duraciones son valores de ejemplo (fórmula simple), no salen del modelo.
"""
import math
import random
import sys
import uuid
from datetime import datetime

import pandas as pd

import db_client

SOURCE = "demo"

# LocationID: (nombre, latitud, longitud) del centro de la zona
ZONAS = {
    1: ("Newark Airport", 40.6918, -74.1740),
    74: ("East Harlem North", 40.8012, -73.9373),
    79: ("East Village", 40.7276, -73.9859),
    132: ("JFK Airport", 40.6470, -73.7865),
    138: ("LaGuardia Airport", 40.7744, -73.8736),
    142: ("Lincoln Square East", 40.7736, -73.9815),
    161: ("Midtown Center", 40.7580, -73.9777),
    186: ("Penn Station/Madison Sq West", 40.7485, -73.9924),
    230: ("Times Sq/Theatre District", 40.7598, -73.9842),
    236: ("Upper East Side North", 40.7804, -73.9570),
    237: ("Upper East Side South", 40.7686, -73.9656),
    249: ("West Village", 40.7346, -74.0029),
}
AEROPUERTOS = {1, 132, 138}

VIAJES = [  # (origen, destino, fecha y hora de recojo)
    (161, 132, "2022-05-10 18:30"),   # martes, hora punta de la tarde, al aeropuerto
    (237, 236, "2022-05-11 08:15"),   # miércoles, hora punta de la mañana
    (230, 79, "2022-05-14 13:40"),    # sábado
    (138, 161, "2022-05-16 07:50"),   # lunes, desde LaGuardia
    (142, 186, "2022-05-19 23:10"),   # jueves de noche
    (249, 230, "2022-05-21 19:05"),   # sábado
    (1, 161, "2022-05-25 11:20"),     # desde Newark
    (236, 74, "2022-05-28 16:30"),    # sábado
]


def build_features(pu: int, do: int, fecha: datetime) -> dict:
    """Misma lógica que build_features() de la API: los 8 campos del modelo."""
    hora, dia = fecha.hour, fecha.weekday()
    laborable = dia < 5
    return {
        "PULocationID": pu,
        "DOLocationID": do,
        "pickup_hour": hora,
        "pickup_dow": dia,
        "is_airport_trip": int(pu in AEROPUERTOS or do in AEROPUERTOS),
        "morning_rush": int(laborable and hora in range(7, 10)),
        "night_rush": int(laborable and hora in range(17, 20)),
        "weekend_rush": int(not laborable and hora in range(10, 20)),
    }


def distancia_millas(pu: int, do: int) -> float:
    _, lat1, lon1 = ZONAS[pu]
    _, lat2, lon2 = ZONAS[do]
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    recta = 3958.8 * 2 * math.asin(math.sqrt(a))
    return round(max(recta * 1.3, 0.6), 2)   # 1.3 = las calles no van en línea recta


def prediccion_ejemplo(f: dict, millas: float) -> tuple[float, float, float]:
    """Valores de EJEMPLO para la demo (el modelo real los reemplaza)."""
    velocidad = 11 if millas < 3 else 18 if millas < 10 else 24      # mph: viajes largos usan autopista
    if f["morning_rush"] or f["night_rush"]:
        velocidad *= 0.75                                           # hora punta: más tráfico
    elif f["pickup_hour"] < 6:
        velocidad *= 1.4                                            # madrugada: calles libres
    duracion = round(millas / velocidad * 60 + 2, 1)
    zonas = {f["PULocationID"], f["DOLocationID"]}
    if 132 in zonas and not (zonas - {132}) & AEROPUERTOS:
        tarifa = 52.0                                   # tarifa plana JFK - Manhattan (2022)
    else:
        tarifa = round(2.5 + 2.5 * millas + 0.25 * duracion, 2)
    cargos = 0.5 + 0.3 + 2.5 + (1.25 if f["PULocationID"] in (132, 138) else 0)
    return tarifa, duracion, round(tarifa + cargos, 2)


def insertar() -> None:
    random.seed(7)
    for pu, do, texto in VIAJES:
        fecha = datetime.strptime(texto, "%Y-%m-%d %H:%M")
        f = build_features(pu, do, fecha)
        millas = distancia_millas(pu, do)
        tarifa, duracion, total = prediccion_ejemplo(f, millas)
        ms_tarifa, ms_duracion = random.uniform(2, 5), random.uniform(2, 5)
        db_client.log_prediction(
            features=f,
            pickup_datetime=fecha,
            predicted_fare_usd=tarifa,
            predicted_duration_min=duracion,
            predicted_total_amount_usd=total,
            model_latency_ms=ms_tarifa + ms_duracion,
            fare_latency_ms=ms_tarifa,
            duration_latency_ms=ms_duracion,
            total_latency_ms=ms_tarifa + ms_duracion + random.uniform(120, 320),
            estimated_distance_miles=millas,
            model_version="demo",
            request_payload={"origen": ZONAS[pu][0], "destino": ZONAS[do][0], "pickup_datetime": texto, "passenger_count": 1},
            client_source=SOURCE,
            raise_errors=True,
        )

    db_client.log_error(
        error_type="OutOfServiceAreaError", error_message="(41.5, -74.0) is outside the NYC taxi service area",
        severity="INFO", request_id=uuid.uuid4(), component="zones", endpoint="/predict",
        http_method="POST", status_code=422, client_source=SOURCE, raise_errors=True,
    )
    db_client.log_error(
        error_type="OSRMError", error_message="No fue posible conectar con OSRM",
        severity="ERROR", request_id=uuid.uuid4(), component="osrm", endpoint="/predict",
        http_method="POST", status_code=503, client_source=SOURCE, raise_errors=True,
    )
    db_client.log_error(
        error_type="RequestValidationError", error_message="passenger_count: Input should be less than or equal to 6",
        severity="INFO", component="api", endpoint="/predict",
        http_method="POST", status_code=422, client_source=SOURCE, raise_errors=True,
    )
    print(f"✅ Se insertaron {len(VIAJES)} predicciones y 3 eventos de ejemplo.\n")


def mostrar() -> None:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)

    pred = pd.DataFrame(db_client.get_recent_predictions(50))
    print("══════ prediction_logs  (una fila por predicción) ══════")
    if pred.empty:
        print("(vacía)")
    else:
        pred = pred.sort_values("prediction_id")
        tabla = pd.DataFrame({
            "id": pred["prediction_id"],
            "ticket": pred["request_id"].astype(str).str[:8],
            "recojo": pd.to_datetime(pred["pickup_datetime"]).dt.strftime("%d-%m %H:%M"),
            "origen": pred["pu_location_id"],
            "destino": pred["do_location_id"],
            "hora": pred["pickup_hour"],
            "dia": pred["pickup_dow"],
            "aerop": pred["is_airport_trip"].map({True: "sí", False: "-"}),
            "punta_am": pred["morning_rush"].map({True: "sí", False: "-"}),
            "punta_pm": pred["night_rush"].map({True: "sí", False: "-"}),
            "finde": pred["weekend_rush"].map({True: "sí", False: "-"}),
            "tarifa_$": pred["predicted_fare_usd"],
            "min": pred["predicted_duration_min"],
            "total_$": pred["predicted_total_amount_usd"],
            "ms_modelos": pred["model_latency_ms"].astype(float).round(1),
            "ms_total": pred["total_latency_ms"].astype(float).round(0),
        })
        print(tabla.to_string(index=False))

    err = pd.DataFrame(db_client.get_recent_errors(50))
    print("\n══════ error_logs  (errores y eventos) ══════")
    if err.empty:
        print("(vacía)")
    else:
        err = err.sort_values("error_id")
        print(pd.DataFrame({
            "id": err["error_id"],
            "severidad": err["severity"],
            "dónde": err["component"],
            "código": err["status_code"],
            "tipo": err["error_type"],
            "mensaje": err["error_message"].str[:55],
        }).to_string(index=False))

    stats = pd.DataFrame(db_client.latency_stats(datetime(2000, 1, 1)))
    print("\n══════ sp_latency_stats()  (cuánto tarda, en milisegundos) ══════")
    print("(sin datos)" if stats.empty else stats.to_string(index=False))


def borrar() -> None:
    with db_client.get_pool().connection() as conn:
        p = conn.execute("DELETE FROM prediction_logs WHERE client_source = %s", (SOURCE,)).rowcount
        e = conn.execute("DELETE FROM error_logs WHERE client_source = %s", (SOURCE,)).rowcount
    print(f"🧹 Se borraron {p} predicciones y {e} eventos de la demo.")


if __name__ == "__main__":
    db_client.open_pool()
    try:
        if "--borrar" in sys.argv:
            borrar()
        else:
            if "--ver" not in sys.argv:
                insertar()
            mostrar()
    finally:
        db_client.close_pool()
