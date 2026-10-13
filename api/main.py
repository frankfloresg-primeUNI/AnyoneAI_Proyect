from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
import os
from dotenv import load_dotenv
#from api.google_maps import get_route
from api.osrm import get_route
from api.zones import ZoneLocator, InvalidCoordinatesError, OutOfServiceAreaError
from api.features import build_features

app = FastAPI()
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
def predict(trip: TripRequest):
    try:
        pickup_zone = zone_locator.coords_to_zone(trip.pickup.lat, trip.pickup.lon)
        dropoff_zone = zone_locator.coords_to_zone(trip.dropoff.lat, trip.dropoff.lon)
    except (InvalidCoordinatesError, OutOfServiceAreaError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

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

    return {

        "trip_distance_miles": round(distance_miles, 2),
        "pickup_zone": {"location_id": pickup_zone.location_id,"name": pickup_zone.zone,"borough": pickup_zone.borough},
        "dropoff_zone": {"location_id": dropoff_zone.location_id,"name": dropoff_zone.zone,"borough": dropoff_zone.borough},
        "fare_amount": 52.00,
        "trip_duration_min": 41.3,
        "total_amount": 59.50,
        "model_version": "mock"
    }