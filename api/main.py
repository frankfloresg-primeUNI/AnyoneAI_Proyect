from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from datetime import datetime
import os
from dotenv import load_dotenv
#from api.google_maps import get_route
from api.osrm import get_route
from api.zones import ZoneLocator, InvalidCoordinatesError, OutOfServiceAreaError
from api.features import build_features
import xgboost as xgb
from pathlib import Path
from api.model_features import prepare_model_features
from contextlib import asynccontextmanager
from database import db_client
import time
import uuid
from fastapi import Request
from api.charges import (load_charges_config, calculate_jfk_manhattan_flat_fare, calculate_total_charges,)

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_client.open_pool()
    yield
    db_client.close_pool()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=False,
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

zone_locator = ZoneLocator("data/reference/taxi_zones.geojson")
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

BASE_DIR = Path(__file__).resolve().parent.parent

fare_model = xgb.Booster()
fare_model.load_model(str(BASE_DIR / "models/xgboost_fare_v2.json"))

duration_model = xgb.Booster()
duration_model.load_model(str(BASE_DIR / "models/xgboost_duration_v3.json"))

charges_config = load_charges_config()

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

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/predict")
def predict(trip: TripRequest, request: Request):

    t_inicio = time.perf_counter()
    request_id = uuid.uuid4()
    request.state.request_id = request_id
    payload = trip.model_dump(mode="json")

    try:
        pickup_zone = zone_locator.coords_to_zone(trip.pickup.lat, trip.pickup.lon)
        dropoff_zone = zone_locator.coords_to_zone(trip.dropoff.lat, trip.dropoff.lon)
    except (InvalidCoordinatesError, OutOfServiceAreaError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    allowed_airport_zones = {132, 138}  # JFK y LaGuardia

    def is_allowed_zone(zone):
        return (
            zone.borough == "Manhattan"
            or zone.location_id in allowed_airport_zones
        )

    if not is_allowed_zone(pickup_zone) or not is_allowed_zone(dropoff_zone):
        raise HTTPException(
            status_code=422,
            detail="Service available only for trips within Manhattan, JFK and LaGuardia airports."
        )

    if trip.trip_distance_miles is not None:
        distance_miles = trip.trip_distance_miles
    else:
        route = get_route(
            origin_lat=trip.pickup.lat,
            origin_lng=trip.pickup.lon,
            destination_lat=trip.dropoff.lat,
            destination_lng=trip.dropoff.lon
        )
        distance_miles = route["distance_meters"] / 1609.344

    features = build_features(
        pickup_zone=pickup_zone.location_id,
        dropoff_zone=dropoff_zone.location_id,
        distance_miles=distance_miles,
        pickup_datetime=trip.pickup_datetime
    )

    flat_fare = calculate_jfk_manhattan_flat_fare(
    pickup_zone_id=pickup_zone.location_id,
    dropoff_zone_id=dropoff_zone.location_id,
    pickup_borough=pickup_zone.borough,
    dropoff_borough=dropoff_zone.borough,
    charges_config=charges_config,
)

    duration_df = prepare_model_features(features, "duration")
    duration_input = xgb.DMatrix(duration_df, enable_categorical=True)

    t_modelos = time.perf_counter()

    if flat_fare is not None:
        fare_amount = float(flat_fare)
    else:
        fare_df = prepare_model_features(features, "fare")
        fare_input = xgb.DMatrix(fare_df, enable_categorical=True)
        fare_amount = float(fare_model.predict(fare_input)[0])

    t_fare = time.perf_counter()

    trip_duration_min = float(duration_model.predict(duration_input)[0])

    t_fin_modelos = time.perf_counter()

    charges, total_charges = calculate_total_charges(
        pickup_datetime=trip.pickup_datetime,
        pickup_zone_id=pickup_zone.location_id,
        dropoff_zone_id=dropoff_zone.location_id,
        pickup_borough=pickup_zone.borough,
        dropoff_borough=dropoff_zone.borough,
        charges_config=charges_config,
    )

    total_amount = round(fare_amount + total_charges, 2)

    charge_labels = {
        "fixed_surcharges": "Recargos fijos",
        "night_surcharge": "Recargo nocturno",
        "rush_hour_surcharge": "Hora pico",
        "airport_access_fee": "Acceso aeroportuario",
        "laguardia_surcharge": "Recargo LaGuardia",
    }

    charges_response = [
        {"label": charge_labels[key], "amount": amount}
        for key, amount in charges.items()
        if amount > 0
    ]

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
        model_version="fare_v2_duration_v3",
        request_payload=payload,
        client_source="frontend",
    )

    return {

        "trip_distance_miles": round(distance_miles, 2),
        "pickup_zone": {"location_id": pickup_zone.location_id,"name": pickup_zone.zone,"borough": pickup_zone.borough},
        "dropoff_zone": {"location_id": dropoff_zone.location_id,"name": dropoff_zone.zone,"borough": dropoff_zone.borough},
        "fare_amount": round(fare_amount, 2),
        "trip_duration_min": round(trip_duration_min, 2),
        "charges": charges_response,
        "total_charges": total_charges,
        "total_amount": total_amount,
        "model_version": "fare_v2_duration_v3"
    }