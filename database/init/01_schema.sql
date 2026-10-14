-- =====================================================================
-- NYC Yellow Taxi — Base de logs de predicción
-- 01_schema.sql: tablas e índices
-- Se ejecuta automáticamente la primera vez que se levanta el contenedor.
-- =====================================================================

SET client_min_messages = warning;

-- ---------------------------------------------------------------------
-- 1. Log de predicciones: inputs + predicción de tarifa y duración + latencia
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prediction_logs (
    prediction_id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id              UUID          NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),

    -- Inputs enviados por el usuario
    pickup_datetime         TIMESTAMP     NOT NULL,
    pu_location_id          SMALLINT      NOT NULL CHECK (pu_location_id BETWEEN 1 AND 265),
    do_location_id          SMALLINT      NOT NULL CHECK (do_location_id BETWEEN 1 AND 265),
    trip_distance           NUMERIC(7,2)  NOT NULL CHECK (trip_distance >= 0),

    -- Features derivadas que la API le pasa a los modelos
    pickup_hour             SMALLINT      CHECK (pickup_hour BETWEEN 0 AND 23),
    pickup_dow              SMALLINT      CHECK (pickup_dow BETWEEN 0 AND 6),
    is_airport_trip         BOOLEAN,
    morning_rush            BOOLEAN,
    night_rush              BOOLEAN,
    weekend_rush            BOOLEAN,

    -- Body completo del request, tal como llegó a la API
    request_payload         JSONB,

    -- Predicciones
    predicted_fare_usd      NUMERIC(10,2),
    predicted_duration_min  NUMERIC(10,2),
    fare_model_version      VARCHAR(50),
    duration_model_version  VARCHAR(50),

    -- Latencia en milisegundos
    latency_ms              NUMERIC(12,3) NOT NULL CHECK (latency_ms >= 0),
    fare_latency_ms         NUMERIC(12,3) CHECK (fare_latency_ms >= 0),
    duration_latency_ms     NUMERIC(12,3) CHECK (duration_latency_ms >= 0),

    client_source           VARCHAR(50),

    CONSTRAINT chk_prediction_logs_al_menos_una_prediccion
        CHECK (predicted_fare_usd IS NOT NULL OR predicted_duration_min IS NOT NULL)
);

COMMENT ON TABLE  prediction_logs                 IS 'Un registro por request de predicción: inputs, predicciones y latencia.';
COMMENT ON COLUMN prediction_logs.request_id      IS 'UUID del request. Lo genera la API para correlacionar con error_logs.';
COMMENT ON COLUMN prediction_logs.pickup_datetime IS 'Fecha/hora de recojo en hora local de NYC (sin zona horaria).';
COMMENT ON COLUMN prediction_logs.pickup_dow      IS '0 = lunes ... 6 = domingo (igual que pandas dayofweek).';
COMMENT ON COLUMN prediction_logs.request_payload IS 'Body JSON original del request.';
COMMENT ON COLUMN prediction_logs.latency_ms      IS 'Tiempo total de predicción en ms.';
COMMENT ON COLUMN prediction_logs.client_source   IS 'Origen del request: frontend, swagger, test, etc.';

CREATE INDEX IF NOT EXISTS idx_prediction_logs_created_at
    ON prediction_logs (created_at DESC);


-- ---------------------------------------------------------------------
-- 2. Log de errores
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS error_logs (
    error_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    request_id       UUID,
    severity         VARCHAR(10)   NOT NULL DEFAULT 'ERROR'
                     CHECK (severity IN ('WARNING', 'ERROR', 'CRITICAL')),
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

COMMENT ON TABLE  error_logs            IS 'Errores de la API, de los modelos o de validación.';
COMMENT ON COLUMN error_logs.request_id IS 'Mismo request_id que prediction_logs, si el request llegó a tener uno.';
COMMENT ON COLUMN error_logs.component  IS 'Dónde ocurrió: api, fare_model, duration_model, database, frontend...';
COMMENT ON COLUMN error_logs.error_type IS 'Nombre de la excepción o categoría: ValidationError, ModelError, etc.';

CREATE INDEX IF NOT EXISTS idx_error_logs_created_at
    ON error_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_error_logs_request_id
    ON error_logs (request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_error_logs_error_type
    ON error_logs (error_type);
