"""
EJEMPLO PROBADO de integración con la base de logs.

Es el api/main.py de la rama feature/fastapi-backend (Yusmary) con las llamadas a db_client.
Las líneas nuevas están marcadas con  # [BD].
Supone que build_features() ya no recibe la distancia y devuelve los 8 campos del modelo.

Se probó con: request válido, OSRM ok, coordenadas fuera de NYC (422), OSRM caído (503),
body inválido (422), error inesperado (500) y con la base de datos apagada.
"""
import time                                                       # [BD]
import uuid                                                       # [BD]
from contextlib import asynccontextmanager                        # [BD]

from fastapi import FastAPI, HTTPException, Request               # [BD] se agrega Request
from fastapi.concurrency import run_in_threadpool                 # [BD]
from fastapi.exception_handlers import request_validation_exception_handler  # [BD]
from fastapi.exceptions import RequestValidationError             # [BD]
from fastapi.responses import JSONResponse                        # [BD]
from pydantic import BaseModel, Field
from datetime import datetime
import os
from dotenv import load_dotenv
#from api.google_maps import get_route
from api.osrm import get_route
from api.zones import ZoneLocator, InvalidCoordinatesError, OutOfServiceAreaError
from api.features import build_features
from database import db_client                                    # [BD]

MODEL_VERSION = "mock"                                            # [BD]


@asynccontextmanager                                              # [BD]
async def lifespan(app: FastAPI):                                 # [BD]
    db_client.open_pool()                                         # [BD]
    yield                                                         # [BD]
    db_client.close_pool()                                        # [BD]


app = FastAPI(lifespan=lifespan)                                  # [BD] antes: FastAPI()
zone_locator = ZoneLocator("data/reference/taxi_zones.geojson")
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

class TripRequest(BaseModel):
    pickup: Coordinates
    dropoff: Coordinates
    pickup_datetime: datetime
    passenger_count: int = Field(ge=1, le=6)
    trip_distance_miles: float | None = Field(default=None, gt=0)

@app.get("/")
def home():
    return {"message": "NYC Taxi Prediction API"}

@app.post("/predict")
def predict(trip: TripRequest, request: Request):                 # [BD] se agrega request
    t_inicio = time.perf_counter()                                # [BD]
    request_id = uuid.uuid4()                                     # [BD]
    request.state.request_id = request_id                         # [BD]
    payload = trip.model_dump(mode="json")                        # [BD]

    try:
        pickup_zone = zone_locator.coords_to_zone(trip.pickup.lat, trip.pickup.lon)
        dropoff_zone = zone_locator.coords_to_zone(trip.dropoff.lat, trip.dropoff.lon)
    except (InvalidCoordinatesError, OutOfServiceAreaError) as error:
        db_client.log_error(                                      # [BD] fuera de alcance -> INFO
            error_type=type(error).__name__, error_message=str(error), severity="INFO",
            request_id=request_id, component="zones", endpoint="/predict", http_method="POST",
            status_code=422, request_payload=payload,
        )
        raise HTTPException(status_code=422, detail=str(error)) from error

    # Distancia estimada: solo para mostrar en el front, ya no entra al modelo
    if trip.trip_distance_miles is not None:
        distance_miles = trip.trip_distance_miles
    else:
        try:
            route = get_route(
                origin_lat=trip.pickup.lat,
                origin_lng=trip.pickup.lon,
                destination_lat=trip.dropoff.lat,
                destination_lng=trip.dropoff.lon
            )
        except HTTPException as error:                            # [BD] falla de OSRM -> ERROR
            db_client.log_error(
                error_type="OSRMError", error_message=str(error.detail),
                severity="ERROR" if error.status_code >= 500 else "WARNING",
                request_id=request_id, component="osrm", endpoint="/predict", http_method="POST",
                status_code=error.status_code, request_payload=payload,
            )
            raise
        distance_miles = route["distance_meters"] / 1609.344

    features = build_features(
        pickup_zone=pickup_zone.location_id,
        dropoff_zone=dropoff_zone.location_id,
        pickup_datetime=trip.pickup_datetime
    )

    t_modelos = time.perf_counter()                               # [BD]
    fare_amount = 52.00             # fare_model.predict(...)
    t_fare = time.perf_counter()                                  # [BD]
    trip_duration_min = 41.3        # duration_model.predict(...)
    t_fin_modelos = time.perf_counter()                           # [BD]
    total_amount = 59.50            # tarifa + cargos

    db_client.log_prediction(                                     # [BD]
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

    return {
        "request_id": str(request_id),                            # [BD] opcional
        "trip_distance_miles": round(distance_miles, 2),
        "pickup_zone": {"location_id": pickup_zone.location_id,"name": pickup_zone.zone,"borough": pickup_zone.borough},
        "dropoff_zone": {"location_id": dropoff_zone.location_id,"name": dropoff_zone.zone,"borough": dropoff_zone.borough},
        "fare_amount": fare_amount,
        "trip_duration_min": trip_duration_min,
        "total_amount": total_amount,
        "model_version": MODEL_VERSION
    }


@app.exception_handler(RequestValidationError)                    # [BD] body inválido (422) -> INFO
async def validation_error(request: Request, exc: RequestValidationError):
    await run_in_threadpool(
        db_client.log_error,
        error_type="RequestValidationError", error_message=str(exc.errors()), severity="INFO",
        component="api", endpoint=request.url.path, http_method=request.method, status_code=422,
        request_payload=exc.body if isinstance(exc.body, dict) else None,
    )
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(Exception)                                 # [BD] error inesperado (500) -> ERROR
async def unhandled_error(request: Request, exc: Exception):
    await run_in_threadpool(
        db_client.log_exception, exc,
        request_id=getattr(request.state, "request_id", None),
        component="api", endpoint=request.url.path, http_method=request.method, status_code=500,
    )
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})
