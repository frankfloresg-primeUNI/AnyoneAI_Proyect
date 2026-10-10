def build_features(pickup_zone, dropoff_zone, distance_miles, pickup_datetime):
    zonas_aeropuerto = [1, 132, 138]

    is_airport_trip = int(
        pickup_zone in zonas_aeropuerto
        or dropoff_zone in zonas_aeropuerto
    )

    pickup_hour = pickup_datetime.hour
    pickup_dow = pickup_datetime.weekday()

    laborable = pickup_dow < 5

    morning_rush = int(laborable and pickup_hour in range(7, 10))
    night_rush = int(laborable and pickup_hour in range(16, 20))
    weekend_rush = int(not laborable and pickup_hour in range(10, 20))

    return {
        "trip_distance": distance_miles,
        "PULocationID": pickup_zone,
        "DOLocationID": dropoff_zone,
        "pickup_hour": pickup_hour,
        "pickup_dow": pickup_dow,
        "is_airport_trip": is_airport_trip,
        "morning_rush": morning_rush,
        "night_rush": night_rush,
        "weekend_rush": weekend_rush
    }