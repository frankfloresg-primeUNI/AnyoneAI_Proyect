# Guía de instalación y ejecución local — NYC Taxi Prediction

Esta guía permite a cualquier integrante del equipo levantar **PostgreSQL + FastAPI + React** en un equipo con **Windows, WSL2 (Ubuntu) y Docker Desktop**. Es el entorno que se ha probado; no implica que la solución esté desplegada en producción.

## 1. Requisitos previos

- Git y acceso a los repositorios del equipo.
- WSL2 con Ubuntu y Python 3.12 (entorno usado en las pruebas locales).
- Docker Desktop con integración WSL2 habilitada y motor en ejecución.
- Node.js y npm instalados en Windows (para React; el README del frontend requiere Node.js 18 o superior).
- Conexión a Internet para instalar dependencias y consultar las rutas de OSRM.

**Repositorios:**

- Backend: https://github.com/frankfloresg-primeUNI/AnyoneAI_Proyect — rama `feature/fastapi-backend`.
- Frontend: https://github.com/CAMIANAIS/nyc-trip-estimator — rama `main`.

> Antes de la instalación, confirmar con el equipo si estas siguen siendo las ramas que se utilizarán para la demostración.

## 2. Descargar los repositorios

En una terminal de WSL (Ubuntu), para el backend:

```bash
git clone https://github.com/frankfloresg-primeUNI/AnyoneAI_Proyect.git
cd AnyoneAI_Proyect
git switch feature/fastapi-backend
```

En PowerShell, en la carpeta donde se desee guardar el frontend:

```powershell
git clone https://github.com/CAMIANAIS/nyc-trip-estimator.git
cd nyc-trip-estimator
git switch main
```

Si ya están clonados, usar `git fetch origin` y actualizar la rama correspondiente **solo después de revisar los cambios locales** con `git status`.

## 3. Configurar e iniciar PostgreSQL

Desde la **raíz del backend**, en WSL:

```bash
cp database/.env.example database/.env
```

Editar `database/.env` y asignar una contraseña propia a `POSTGRES_PASSWORD`. Los valores de ejemplo son:

```dotenv
POSTGRES_DB=taxi_predictions
POSTGRES_USER=taxi_app
POSTGRES_PASSWORD=REEMPLAZAR_POR_UNA_CLAVE_LOCAL
POSTGRES_PORT=5432
DB_HOST=localhost
```

**No compartir ni subir archivos `.env` ni contraseñas.** El archivo de ejemplo sí puede permanecer en Git.

Abrir Docker Desktop y esperar a que el motor esté listo. Luego, desde la raíz del backend:

```bash
docker compose -f database/docker-compose.yml up -d
docker ps
```

Comprobar que el contenedor `taxi_db` figure como **healthy**. El puerto PostgreSQL se publica únicamente en `127.0.0.1:5432`.

**Atención:** si el volumen de PostgreSQL ya se inicializó anteriormente, cambiar `POSTGRES_PASSWORD` en `.env` **no cambia automáticamente** la contraseña del usuario existente. No borrar volúmenes para solucionar este problema sin revisar antes los datos almacenados.

## 4. Instalar y ejecutar FastAPI

Desde la raíz del backend, en WSL:

```bash
python3 -m venv .venv-linux
.venv-linux/bin/python -m pip install --upgrade pip
.venv-linux/bin/python -m pip install -r requirements.txt
```

La rama indicada incluye los archivos de los modelos en `models/`:

- `xgboost_fare_v2.json`
- `xgboost_duration_v3.json`
- `config_fare_v2.json`
- `duration_v3_metadata.json`

También incluye `config/taxi_charges.json`. **No es necesario volver a entrenar los modelos.**

**Iniciar FastAPI solo después de que PostgreSQL esté healthy**, para evitar que el pool de conexiones quede cerrado si la base no está disponible al arrancar:

```bash
.venv-linux/bin/python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Dejar abierta esa terminal. Comprobar en el navegador:

- http://localhost:8000/health → `{"status":"ok"}`
- http://localhost:8000/docs → documentación interactiva de la API.

La API utiliza **OSRM** para obtener rutas cuando se necesitan; **no requiere clave de Google Maps**. Aunque el código conserva una referencia a `GOOGLE_MAPS_API_KEY`, no se necesita para el flujo local probado.

## 5. Configurar y ejecutar React

En **PowerShell**, dentro de `nyc-trip-estimator`:

```powershell
Copy-Item .env.example .env
```

Verificar que `.env` contenga:

```dotenv
VITE_API_URL=http://localhost:8000
VITE_USE_MOCK=false
```

`VITE_MAP_TILE_URL` es opcional. No se necesita configurar una clave de Google Maps.

Instalar dependencias y levantar el frontend:

```powershell
npm install
npm run dev
```

Abrir **http://localhost:8080/** (puerto usado en la configuración local probada). Si Vite muestra otro puerto, comprobar también que la configuración CORS del backend permita ese origen; actualmente la API se configuró para `http://localhost:8080`.

> Si PowerShell no reconoce `npm`, comprobar la instalación de Node.js y la variable `PATH`. En algunos entornos Windows se utiliza `npm.cmd` en lugar de `npm`.

## 6. Verificar la integración

1. Confirmar que `taxi_db` está **healthy**.
2. Confirmar que `http://localhost:8000/health` responde correctamente.
3. Abrir `http://localhost:8080/` y verificar el indicador **API online**.
4. Elegir un viaje con origen y destino dentro del área admitida: **Manhattan, JFK o LaGuardia**. Por ejemplo, Manhattan → JFK.
5. Pulsar **Request** y comprobar tarifa, duración y desglose de recargos. Para Manhattan ↔ JFK se aplica la regla de tarifa fija base de **USD 70**, más los recargos que correspondan.
6. Confirmar que la consulta se registró en PostgreSQL.

Para consultar registros desde WSL:

```bash
docker exec taxi_db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT COUNT(*) FROM prediction_logs;"'
```

**Alternativa visual:** usar DBeaver con host `localhost`, puerto `5432` y las credenciales de `database/.env`; abrir `taxi_predictions → Esquemas → public → Tablas → prediction_logs → Datos`.

Un viaje fuera del área admitida debe recibir una respuesta HTTP **422**. La presentación del mensaje al usuario depende de la versión del frontend descargada.

## 7. Problemas frecuentes

| Síntoma | Qué revisar |
|---|---|
| `Connection refused` al iniciar FastAPI | Docker/PostgreSQL aún no está listo; esperar a que `taxi_db` esté `healthy` y reiniciar FastAPI. |
| `psycopg_pool.PoolClosed` al registrar una predicción | El pool pudo quedar cerrado al arrancar sin PostgreSQL; reiniciar FastAPI con la base ya activa. |
| React muestra API offline | Comprobar `/health`, `VITE_API_URL`, `VITE_USE_MOCK=false` y el puerto 8000. |
| Error CORS | Confirmar que React use `http://localhost:8080`, origen permitido por la configuración local actual. |
| Error HTTP 422 al predecir | Verificar que ambos puntos estén en Manhattan, JFK o LaGuardia. |
| `Import "xgboost" could not be resolved` en VS Code | Revisar el intérprete Python seleccionado: puede apuntar a otro entorno virtual aunque WSL sí tenga la librería instalada. |
| No aparecen nuevos registros en DBeaver | Actualizar la vista y revisar los mensajes del backend; comprobar que el pool de PostgreSQL esté abierto. |
| El puerto 5432 u 8000 está ocupado | Revisar si ya hay un contenedor o servidor ejecutándose antes de iniciar otro. |

## 8. Alcance y coordinación

- Esta guía documenta una **integración local comprobada**; no documenta despliegue público ni producción.
- La API utiliza dos modelos XGBoost para predicciones y reglas tarifarias adicionales. El viaje Manhattan ↔ JFK usa tarifa base fija según la regla implementada.
- El área actualmente admitida es Manhattan, JFK y LaGuardia, para **origen y destino**.
- El registro de predicciones se realiza en PostgreSQL.
- Los recargos de congestión quedaron pendientes y no deben presentarse como implementados.
- Cualquier cambio de ramas, arquitectura o despliegue debe confirmarse con Claus y el equipo.

---

**Orden recomendado para una demostración:** Docker/PostgreSQL → FastAPI → React → predicción de prueba → verificación en `prediction_logs`.
