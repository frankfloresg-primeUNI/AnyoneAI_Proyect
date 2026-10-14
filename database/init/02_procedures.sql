-- =====================================================================
-- NYC Yellow Taxi — Base de logs de predicción
-- 02_procedures.sql: stored procedures
--
-- En PostgreSQL, los stored procedures que devuelven datos se escriben
-- como FUNCTION y se invocan con SELECT:
--     SELECT * FROM sp_log_prediction(...);
--
-- Tipos de los parámetros: INTEGER, DOUBLE PRECISION, BOOLEAN y TEXT, para que
-- acepten directamente int, float, bool y str de Python.
-- =====================================================================

SET client_min_messages = warning;

-- ---------------------------------------------------------------------
-- ESCRITURA
-- ---------------------------------------------------------------------

-- Registra una predicción. Devuelve (prediction_id, request_id).
CREATE OR REPLACE FUNCTION sp_log_prediction(
    p_pickup_datetime         TIMESTAMP,
    p_pu_location_id          INTEGER,
    p_do_location_id          INTEGER,
    p_trip_distance           DOUBLE PRECISION,
    p_latency_ms              DOUBLE PRECISION,
    p_predicted_fare_usd      DOUBLE PRECISION DEFAULT NULL,
    p_predicted_duration_min  DOUBLE PRECISION DEFAULT NULL,
    p_pickup_hour             INTEGER          DEFAULT NULL,
    p_pickup_dow              INTEGER          DEFAULT NULL,
    p_is_airport_trip         BOOLEAN          DEFAULT NULL,
    p_morning_rush            BOOLEAN          DEFAULT NULL,
    p_night_rush              BOOLEAN          DEFAULT NULL,
    p_weekend_rush            BOOLEAN          DEFAULT NULL,
    p_fare_latency_ms         DOUBLE PRECISION DEFAULT NULL,
    p_duration_latency_ms     DOUBLE PRECISION DEFAULT NULL,
    p_fare_model_version      TEXT             DEFAULT NULL,
    p_duration_model_version  TEXT             DEFAULT NULL,
    p_request_payload         JSONB            DEFAULT NULL,
    p_request_id              UUID             DEFAULT NULL,
    p_client_source           TEXT             DEFAULT NULL,
    OUT prediction_id         BIGINT,
    OUT request_id            UUID
)
LANGUAGE sql
AS $$
    INSERT INTO prediction_logs (
        request_id, pickup_datetime, pu_location_id, do_location_id, trip_distance,
        pickup_hour, pickup_dow, is_airport_trip, morning_rush, night_rush, weekend_rush,
        request_payload, predicted_fare_usd, predicted_duration_min,
        fare_model_version, duration_model_version,
        latency_ms, fare_latency_ms, duration_latency_ms, client_source
    )
    VALUES (
        COALESCE(p_request_id, gen_random_uuid()), p_pickup_datetime,
        p_pu_location_id, p_do_location_id, p_trip_distance,
        p_pickup_hour, p_pickup_dow, p_is_airport_trip, p_morning_rush, p_night_rush, p_weekend_rush,
        p_request_payload, p_predicted_fare_usd, p_predicted_duration_min,
        p_fare_model_version, p_duration_model_version,
        p_latency_ms, p_fare_latency_ms, p_duration_latency_ms, p_client_source
    )
    RETURNING prediction_id, request_id;
$$;

COMMENT ON FUNCTION sp_log_prediction IS
    'Registra inputs, predicciones y latencia de un request. Devuelve (prediction_id, request_id).';


-- Registra un error. Devuelve error_id.
CREATE OR REPLACE FUNCTION sp_log_error(
    p_error_type       TEXT,
    p_error_message    TEXT,
    p_severity         TEXT    DEFAULT 'ERROR',
    p_request_id       UUID    DEFAULT NULL,
    p_component        TEXT    DEFAULT NULL,
    p_endpoint         TEXT    DEFAULT NULL,
    p_http_method      TEXT    DEFAULT NULL,
    p_status_code      INTEGER DEFAULT NULL,
    p_stack_trace      TEXT    DEFAULT NULL,
    p_request_payload  JSONB   DEFAULT NULL,
    p_client_source    TEXT    DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE sql
AS $$
    INSERT INTO error_logs (
        request_id, severity, component, endpoint, http_method, status_code,
        error_type, error_message, stack_trace, request_payload, client_source
    )
    VALUES (
        p_request_id, UPPER(COALESCE(p_severity, 'ERROR')), p_component, p_endpoint,
        UPPER(p_http_method), p_status_code,
        COALESCE(NULLIF(p_error_type, ''), 'UnknownError'),
        COALESCE(NULLIF(p_error_message, ''), '(sin mensaje)'),
        p_stack_trace, p_request_payload, p_client_source
    )
    RETURNING error_id;
$$;

COMMENT ON FUNCTION sp_log_error IS
    'Registra un error de la API o de los modelos. Severidad: WARNING, ERROR o CRITICAL. Devuelve error_id.';


-- ---------------------------------------------------------------------
-- LECTURA / MONITOREO
-- ---------------------------------------------------------------------

-- Últimas N predicciones (máx. 1000).
CREATE OR REPLACE FUNCTION sp_get_recent_predictions(p_limit INTEGER DEFAULT 50)
RETURNS SETOF prediction_logs
LANGUAGE sql STABLE
AS $$
    SELECT *
    FROM prediction_logs
    ORDER BY created_at DESC, prediction_id DESC
    LIMIT LEAST(GREATEST(COALESCE(p_limit, 50), 1), 1000);
$$;


-- Una predicción por su request_id.
CREATE OR REPLACE FUNCTION sp_get_prediction(p_request_id UUID)
RETURNS SETOF prediction_logs
LANGUAGE sql STABLE
AS $$
    SELECT * FROM prediction_logs WHERE request_id = p_request_id;
$$;


-- Estadísticas de latencia en un rango de tiempo (por defecto, últimas 24 h).
CREATE OR REPLACE FUNCTION sp_latency_stats(
    p_from TIMESTAMPTZ DEFAULT now() - INTERVAL '24 hours',
    p_to   TIMESTAMPTZ DEFAULT now()
)
RETURNS TABLE (
    total_requests   BIGINT,
    avg_ms           NUMERIC,
    p50_ms           NUMERIC,
    p95_ms           NUMERIC,
    p99_ms           NUMERIC,
    max_ms           NUMERIC,
    avg_fare_ms      NUMERIC,
    avg_duration_ms  NUMERIC
)
LANGUAGE sql STABLE
AS $$
    SELECT
        COUNT(*),
        ROUND(AVG(latency_ms), 3),
        ROUND((percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms))::NUMERIC, 3),
        ROUND((percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms))::NUMERIC, 3),
        ROUND((percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms))::NUMERIC, 3),
        MAX(latency_ms),
        ROUND(AVG(fare_latency_ms), 3),
        ROUND(AVG(duration_latency_ms), 3)
    FROM prediction_logs
    WHERE created_at BETWEEN p_from AND p_to;
$$;


-- Últimos N errores (máx. 1000).
CREATE OR REPLACE FUNCTION sp_get_recent_errors(p_limit INTEGER DEFAULT 50)
RETURNS SETOF error_logs
LANGUAGE sql STABLE
AS $$
    SELECT *
    FROM error_logs
    ORDER BY created_at DESC, error_id DESC
    LIMIT LEAST(GREATEST(COALESCE(p_limit, 50), 1), 1000);
$$;


-- Errores agrupados por tipo y severidad en un rango de tiempo.
CREATE OR REPLACE FUNCTION sp_error_summary(
    p_from TIMESTAMPTZ DEFAULT now() - INTERVAL '24 hours',
    p_to   TIMESTAMPTZ DEFAULT now()
)
RETURNS TABLE (
    error_type  VARCHAR,
    severity    VARCHAR,
    total       BIGINT,
    last_seen   TIMESTAMPTZ
)
LANGUAGE sql STABLE
AS $$
    SELECT e.error_type, e.severity, COUNT(*), MAX(e.created_at)
    FROM error_logs e
    WHERE e.created_at BETWEEN p_from AND p_to
    GROUP BY e.error_type, e.severity
    ORDER BY COUNT(*) DESC, MAX(e.created_at) DESC;
$$;
