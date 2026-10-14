-- =====================================================================
-- NYC Yellow Taxi — Base de logs de predicción
-- 01_schema.sql: tablas e índices
-- Se ejecuta automáticamente la primera vez que se levanta el contenedor.
-- =====================================================================

SET client_min_messages = warning;

-- ---------------------------------------------------------------------
-- 1. Log de predicciones: los 8 inputs del modelo + predicciones + latencia
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prediction_logs (
    prediction_id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id                  UUID          NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    pickup_datetime             TIMESTAMP     NOT NULL,

    -- Los 8 campos que recibe el modelo
    pu_location_id              SMALLINT      NOT NULL CHECK (pu_location_id BETWEEN 1 AND 265),
    do_location_id              SMALLINT      NOT NULL CHECK (do_location_id BETWEEN 1 AND 265),
    pickup_hour                 SMALLINT      NOT NULL CHECK (pickup_hour BETWEEN 0 AND 23),
    pickup_dow                  SMALLINT      NOT NULL CHECK (pickup_dow BETWEEN 0 AND 6),
    is_airport_trip             BOOLEAN       NOT NULL,
    morning_rush                BOOLEAN       NOT NULL,
    night_rush                  BOOLEAN       NOT NULL,
    weekend_rush                BOOLEAN       NOT NULL,

    -- Información adicional (NO entra al modelo)
    estimated_distance_miles    NUMERIC(7,2)  CHECK (estimated_distance_miles >= 0),
    request_payload             JSONB,

    -- Predicciones
    predicted_fare_usd          NUMERIC(10,2),
    predicted_duration_min      NUMERIC(10,2),
    predicted_total_amount_usd  NUMERIC(10,2),
    model_version               VARCHAR(50),

    -- Latencia en milisegundos
    model_latency_ms            NUMERIC(12,3) NOT NULL CHECK (model_latency_ms >= 0),
    total_latency_ms            NUMERIC(12,3) NOT NULL CHECK (total_latency_ms >= 0),
    fare_latency_ms             NUMERIC(12,3) CHECK (fare_latency_ms >= 0),
    duration_latency_ms         NUMERIC(12,3) CHECK (duration_latency_ms >= 0),

    client_source               VARCHAR(50),

    CONSTRAINT chk_prediction_logs_al_menos_una_prediccion
        CHECK (predicted_fare_usd IS NOT NULL OR predicted_duration_min IS NOT NULL)
);

COMMENT ON TABLE  prediction_logs                            IS 'Un registro por request de predicción: inputs del modelo, predicciones y latencia.';
COMMENT ON COLUMN prediction_logs.request_id                 IS 'UUID del request. Lo genera la API para relacionarlo con error_logs.';
COMMENT ON COLUMN prediction_logs.pickup_datetime            IS 'Fecha/hora de recojo en hora local de NYC (sin zona horaria).';
COMMENT ON COLUMN prediction_logs.pickup_dow                 IS '0 = lunes ... 6 = domingo (igual que datetime.weekday()).';
COMMENT ON COLUMN prediction_logs.estimated_distance_miles   IS 'Distancia estimada que se muestra en el front. No es input del modelo (data leakage).';
COMMENT ON COLUMN prediction_logs.request_payload            IS 'Body JSON original: coordenadas, passenger_count, etc.';
COMMENT ON COLUMN prediction_logs.predicted_total_amount_usd IS 'Tarifa predicha + cargos.';
COMMENT ON COLUMN prediction_logs.model_latency_ms           IS 'Tiempo de inferencia de los modelos (tarifa + duración).';
COMMENT ON COLUMN prediction_logs.total_latency_ms           IS 'Tiempo total de /predict, incluye zonas y OSRM.';
COMMENT ON COLUMN prediction_logs.client_source              IS 'Origen del request: frontend, swagger, test, etc.';

CREATE INDEX IF NOT EXISTS idx_prediction_logs_created_at
    ON prediction_logs (created_at DESC);


-- ---------------------------------------------------------------------
-- 2. Log de errores y eventos para trazabilidad
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS error_logs (
    error_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    request_id       UUID,
    severity         VARCHAR(10)   NOT NULL DEFAULT 'ERROR'
                     CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    component        VARCHAR(50),
    endpoint         VARCHAR(200),
    http_method      VARCHAR(10),
    status_code      SMALLINT      CHECK (status_code BETWEEN 100 AND 599),
    error_type       VARCHAR(100)  NOT NULL,
    error_message    TEXT          NOT NULL,
    stack_trace      TEXT,
    request_payload  JSONB,
    client_source    VARCHAR(50)
);

COMMENT ON TABLE  error_logs            IS 'Errores y eventos rechazados. INFO = fuera de alcance (no es error), ERROR = falla real.';
COMMENT ON COLUMN error_logs.request_id IS 'Mismo request_id que prediction_logs, si el request llegó a tener uno.';
COMMENT ON COLUMN error_logs.severity   IS 'INFO: fuera de alcance (422) | WARNING: anomalía | ERROR: falla (OSRM, modelo) | CRITICAL: sistema caído.';
COMMENT ON COLUMN error_logs.component  IS 'Dónde ocurrió: api, zones, osrm, fare_model, duration_model, database...';
COMMENT ON COLUMN error_logs.error_type IS 'Nombre de la excepción o categoría: OutOfServiceAreaError, OSRMError, etc.';

CREATE INDEX IF NOT EXISTS idx_error_logs_created_at
    ON error_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_error_logs_request_id
    ON error_logs (request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_error_logs_error_type
    ON error_logs (error_type);
