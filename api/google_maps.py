import httpx
from fastapi import HTTPException

ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def get_route(origin_lat, origin_lng, destination_lat, destination_lng, api_key):
    payload = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": origin_lat,
                    "longitude": origin_lng
                }
            }
        },
        "destination": {
            "location": {
                "latLng": {
                    "latitude": destination_lat,
                    "longitude": destination_lng
                }
            }
        },
        "travelMode": "DRIVE"
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.distanceMeters,routes.polyline.encodedPolyline"
    }

    try:
        response = httpx.post(
        ROUTES_API_URL,
        json=payload,
        headers=headers,
        timeout=15.0
    )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Google Maps no respondió dentro del tiempo esperado"
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="No fue posible conectar con Google Maps"
        )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        raise HTTPException(
            status_code=502,
            detail="Google Maps rechazó la solicitud de ruta"
        )

    data = response.json()

    if not data.get("routes"):
        raise HTTPException(
            status_code=502,
            detail="Google Maps no encontró una ruta entre los puntos"
        )

    return data