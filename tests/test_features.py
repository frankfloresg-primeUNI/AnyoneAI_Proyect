from datetime import datetime
from api.features import build_features


def test_weekend_rush():
    features = build_features(
        pickup_zone=230,
        dropoff_zone=161,
        distance_miles=1.31,
        pickup_datetime=datetime(2026, 10, 10, 15, 30)
    )

    assert features["weekend_rush"] == 1

def test_morning_rush():
    features = build_features(
        pickup_zone=230,
        dropoff_zone=161,
        distance_miles=1.31,
        pickup_datetime=datetime(2026, 10, 9, 8, 30)
    )

    assert features["morning_rush"] == 1

def test_night_rush():
    features = build_features(
        pickup_zone=230,
        dropoff_zone=161,
        distance_miles=1.31,
        pickup_datetime=datetime(2026, 10, 9, 17, 30)
    )

    assert features["night_rush"] == 1


def test_airport_trip():
    features = build_features(
        pickup_zone=132,  # JFK
        dropoff_zone=230,
        distance_miles=18.21,
        pickup_datetime=datetime(2026, 10, 9, 14, 30)
    )

    assert features["is_airport_trip"] == 1


def test_no_airport_trip():
    features = build_features(
        pickup_zone=230,
        dropoff_zone=161,
        distance_miles=1.31,
        pickup_datetime=datetime(2026, 10, 9, 14, 30)
    )

    assert features["is_airport_trip"] == 0