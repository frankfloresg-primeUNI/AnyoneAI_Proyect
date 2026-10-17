import json
from pathlib import Path

def load_charges_config():
    base_dir = Path(__file__).resolve().parent.parent
    config_path = base_dir / "config" / "taxi_charges.json"

    with open(config_path, "r", encoding="utf-8") as file:
        return json.load(file)

def calculate_night_surcharge(pickup_datetime, charges_config):
    hour = pickup_datetime.hour

    if hour >= 20 or hour < 6:
        return charges_config["night_surcharge"]

    return 0.0

def calculate_rush_hour_surcharge(
    pickup_datetime,
    charges_config,
    pickup_zone_id,
    dropoff_zone_id,
    pickup_borough,
    dropoff_borough,
):
    weekday = pickup_datetime.weekday()
    hour = pickup_datetime.hour
    date_str = pickup_datetime.date().isoformat()

    is_holiday = date_str in charges_config["rush_hour_holidays"]

    if weekday >= 5 or not (16 <= hour < 20) or is_holiday:
        return 0.0

    flat_fare = calculate_jfk_manhattan_flat_fare(
        pickup_zone_id,
        dropoff_zone_id,
        pickup_borough,
        dropoff_borough,
        charges_config,
    )

    if flat_fare is not None:
        return charges_config["jfk_rush_hour_surcharge"]

    return charges_config["rush_hour_surcharge"]

def calculate_fixed_surcharges(charges_config):
    return (
        charges_config["mta_state_surcharge"]
        + charges_config["improvement_surcharge"]
    )

def calculate_airport_access_fee(pickup_zone_id, charges_config):
    if pickup_zone_id in (132, 138):
        return charges_config["airport_access_fee"]

    return 0.0

def calculate_laguardia_surcharge(pickup_zone_id, dropoff_zone_id, charges_config):
    if pickup_zone_id == 138 or dropoff_zone_id == 138:
        return charges_config["laguardia_surcharge"]

    return 0.0

def calculate_congestion_surcharges(
    pickup_zone_id,
    dropoff_zone_id,
    charges_config,
    congestion_zone_ids,
):
    if (
        pickup_zone_id in congestion_zone_ids
        or dropoff_zone_id in congestion_zone_ids
    ):
        return (
            charges_config["congestion_surcharge"]
            + charges_config["congestion_pricing"]
        )

    return 0.0

def calculate_jfk_manhattan_flat_fare(
    pickup_zone_id,
    dropoff_zone_id,
    pickup_borough,
    dropoff_borough,
    charges_config,
):
    JFK_ZONE_ID = 132

    is_jfk_to_manhattan = (
        pickup_zone_id == JFK_ZONE_ID
        and dropoff_borough == "Manhattan"
    )

    is_manhattan_to_jfk = (
        pickup_borough == "Manhattan"
        and dropoff_zone_id == JFK_ZONE_ID
    )

    if is_jfk_to_manhattan or is_manhattan_to_jfk:
        return charges_config["jfk_manhattan_flat_fare"]

    return None

def calculate_total_charges(
    pickup_datetime,
    pickup_zone_id,
    dropoff_zone_id,
    pickup_borough,
    dropoff_borough,
    charges_config,
):
    charges = {
        "fixed_surcharges": calculate_fixed_surcharges(charges_config),
        "night_surcharge": calculate_night_surcharge(
            pickup_datetime, charges_config
        ),
        "rush_hour_surcharge": calculate_rush_hour_surcharge(
            pickup_datetime, charges_config, pickup_zone_id, dropoff_zone_id, pickup_borough, dropoff_borough
        ),
        "airport_access_fee": calculate_airport_access_fee(
            pickup_zone_id, charges_config
        ),
        "laguardia_surcharge": calculate_laguardia_surcharge(
            pickup_zone_id, dropoff_zone_id, charges_config
        ),
    }

    total_charges = round(sum(charges.values()), 2)

    return charges, total_charges