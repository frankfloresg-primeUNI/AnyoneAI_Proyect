import httpx
from fastapi import HTTPException

OSRM_API_URL = "https://router.project-osrm.org/route/v1/driving"

def get_route(origin_lat, origin_lng, destination_lat, destination_lng):
    coordinates = (
        f"{origin_lng},{origin_lat};"
        f"{destination_lng},{destination_lat}"
    )

    url = f"{OSRM_API_URL}/{coordinates}"

    params = {
        "overview": "full",
        "geometries": "geojson"
    }

    try:
        response = httpx.get(
            url,
            params=params,
            timeout=15.0
    )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="OSRM no respondió dentro del tiempo esperado"
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="No fue posible conectar con OSRM"
        )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        raise HTTPException(
            status_code=503,
            detail="OSRM rechazó la solicitud de ruta"
        )

    data = response.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise HTTPException(
            status_code=400,
            detail="OSRM no encontró una ruta entre los puntos"
        )

    route = data["routes"][0]

    return {
        "distance_meters": route["distance"],
        "duration_seconds": route["duration"],
        "geometry": route["geometry"]
    }