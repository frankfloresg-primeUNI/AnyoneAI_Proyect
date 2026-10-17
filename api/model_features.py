
import pandas as pd


MODEL_FEATURES = [
    "PULocationID",
    "DOLocationID",
    "pickup_hour",
    "pickup_dow",
    "is_airport_trip",
    "morning_rush",
    "night_rush",
    "weekend_rush",
]

CATEGORICAL_FEATURES = [
    "PULocationID",
    "DOLocationID",
]

NUMERIC_FEATURES = [
    "pickup_hour",
    "pickup_dow",
    "is_airport_trip",
    "morning_rush",
    "night_rush",
    "weekend_rush",
]


def prepare_model_features(features: dict, model_type: str) -> pd.DataFrame:
    """
    Prepara las características para los modelos XGBoost.

    model_type:
        "fare" -> modelo de tarifa
        "duration" -> modelo de duración
    """

    if model_type not in ("fare", "duration"):
        raise ValueError(f"Tipo de modelo no válido: {model_type}")

    # Seleccionar únicamente las ocho características,
    # respetando el orden utilizado durante el entrenamiento.
    model_data = {name: features[name] for name in MODEL_FEATURES}

    df = pd.DataFrame([model_data], columns=MODEL_FEATURES)

    # Las zonas TLC son variables categóricas.
    for column in CATEGORICAL_FEATURES:
        df[column] = df[column].astype("category")

    # Los modelos tienen tipos numéricos diferentes.
    numeric_type = "int32" if model_type == "fare" else "float32"

    for column in NUMERIC_FEATURES:
        df[column] = df[column].astype(numeric_type)

    return df
