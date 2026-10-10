from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
import os
from dotenv import load_dotenv
from api.google_maps import get_route
from api.zones import coords_to_zone, InvalidCoordinatesError, OutOfServiceAreaError
from api.features import build_features

app = FastAPI()
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

class TripRequest(BaseModel):
    pickup_latitude: float = Field(ge=-90, le=90)
    pickup_longitude: float = Field(ge=-180, le=180)
    dropoff_latitude: float = Field(ge=-90, le=90)
    dropoff_longitude: float = Field(ge=-180, le=180)
    pickup_datetime: datetime

@app.get("/")
def home():
    return {"message": "NYC Taxi Prediction API"}

@app.post("/predict")
def predict(trip: TripRequest):
    try:
        pickup_zone = coords_to_zone(trip.pickup_latitude, trip.pickup_longitude)
        dropoff_zone = coords_to_zone(trip.dropoff_latitude, trip.dropoff_longitude)
    except (InvalidCoordinatesError, OutOfServiceAreaError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    route = get_route(
        origin_lat=trip.pickup_latitude,
        origin_lng=trip.pickup_longitude,
        destination_lat=trip.dropoff_latitude,
        destination_lng=trip.dropoff_longitude,
        api_key=GOOGLE_MAPS_API_KEY
    )

    distance_meters = route["routes"][0]["distanceMeters"]
    distance_miles = distance_meters / 1609.344

    features = build_features(
    pickup_zone=pickup_zone,
    dropoff_zone=dropoff_zone,
    distance_miles=distance_miles,
    pickup_datetime=trip.pickup_datetime
    )

    return {
        "message": "Ruta calculada correctamente",
        "trip_distance_miles": round(distance_miles, 2),
        "encoded_polyline": route["routes"][0]["polyline"]["encodedPolyline"],
        "pickup_hour": features["pickup_hour"],
        "pickup_dow": features["pickup_dow"],
        "is_airport_trip": features["is_airport_trip"],
        "PULocationID": features["PULocationID"],
        "DOLocationID": features["DOLocationID"],
        "morning_rush": features["morning_rush"],
        "night_rush": features["night_rush"],
        "weekend_rush": features["weekend_rush"]
    }