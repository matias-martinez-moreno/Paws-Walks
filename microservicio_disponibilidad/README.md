# Microservicio de Disponibilidad — Flask

## Por qué este servicio

**BuscarDisponibilidad es el motor de matching del negocio**: toda reserva en Paws & Walks comienza con una búsqueda de cuidadores disponibles. Es la operación de mayor tráfico de lectura y la más costosa computacionalmente (filtros geo, conteo de cupos, joins de múltiples tablas).

Separarlo como microservicio Flask tiene justificación arquitectural y económica:

| Razón | Detalle |
|---|---|
| **Solo lectura** | Nunca escribe en BD — escala horizontal sin afectar el core transaccional de Django |
| **Alta carga** | Toda sesión de usuario hace al menos una búsqueda antes de reservar |
| **Escalabilidad independiente** | En producción se puede replicar, cachear o agregar índices geo sin tocar Django |
| **Contrato HTTP limpio** | Input: JSON con parámetros. Output: JSON con cuidadores disponibles |
| **Extensible** | Puede crecer con ML de recomendación, Redis cache, índices espaciales (PostGIS) sin impactar el monolito |

## Arquitectura

```
[Cliente] ──► Django :8000 ──HTTP POST──► Flask :5001
                  │                            │
                  └──────────────────────────►[PostgreSQL / SQLite]
                  (fallback si Flask no responde)
```

El Gateway de Django (`ServiciosApiGatewayService`) intenta llamar Flask primero. Si falla, cae automáticamente al servicio interno — **cero downtime**.

## Estructura

```
microservicio_disponibilidad/
├── app.py          ← Flask app: POST /disponibilidad, GET /health
├── services.py     ← Lógica de búsqueda PASEO + GUARDERIA (SQLAlchemy raw SQL)
├── db.py           ← Engine SQLAlchemy (SQLite dev / PostgreSQL Docker)
├── utils.py        ← Funciones puras: haversine_km, time_to_minutes
├── requirements.txt
└── Dockerfile
```

## Cómo probarlo

### Local (sin Docker)

```bash
# 1. Instalar dependencias Flask
cd microservicio_disponibilidad
pip install -r requirements.txt

# 2. Levantar Flask (apuntando a la misma SQLite de Django)
DATABASE_URL="sqlite:///../db.sqlite3" python -m flask --app app run --port 5001

# 3. Probar health
curl http://localhost:5001/health
# {"status": "ok", "servicio": "disponibilidad"}

# 4. Buscar disponibilidad directamente en Flask
curl -X POST http://localhost:5001/disponibilidad \
  -H "Content-Type: application/json" \
  -d '{
    "tipoServicio": "paseo",
    "idDueño_id": "<uuid-del-dueño>",
    "idMascota_id": "<uuid-de-la-mascota>",
    "fecha": "2026-04-20",
    "duracionMinutos": 60,
    "ciudadPaseo": "Medellín"
  }'
```

### Con Docker (todo junto)

```bash
# Levantar los 3 servicios: PostgreSQL + Django + Flask
docker-compose up --build

# Django en: http://localhost:8000
# Flask en:  http://localhost:5001

# Probar via Django (con auth)
curl -X POST http://localhost:8000/api/disponibilidad/ \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{"tipoServicio":"paseo","fecha":"2026-04-20","duracionMinutos":60,"ciudadPaseo":"Medellín"}'

# Probar Flask directo (sin auth)
curl -X POST http://localhost:5001/disponibilidad \
  -H "Content-Type: application/json" \
  -d '{"tipoServicio":"paseo","idDueño_id":"<uuid>","idMascota_id":"<uuid>","fecha":"2026-04-20","duracionMinutos":60,"ciudadPaseo":"Medellín"}'
```

### Forzar fallback de Django al servicio interno

```bash
# Sin DISPONIBILIDAD_SERVICE_URL, Django usa su propio servicio
DISPONIBILIDAD_SERVICE_URL="" python manage.py runserver
```

## Snippets importantes

### 1. Gateway con HTTP call + fallback (Django)
```python
# servicios/service_layer/api_gateway.py
def buscar_disponibilidad(self, payload: dict) -> list[dict]:
    flask_url = getattr(settings, "DISPONIBILIDAD_SERVICE_URL", "")
    if flask_url:
        try:
            json_payload = json.loads(json.dumps(payload, cls=DjangoJSONEncoder))
            resp = http_requests.post(f"{flask_url}/disponibilidad", json=json_payload, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            _logger.warning("Microservicio disponibilidad no disponible, usando fallback: %s", exc)

    # Fallback: servicio interno Django
    data = self._validar_disponibilidad_service.validar(payload)
    resultados = self._buscar_disponibilidad_service.buscar(data)
    return self._resultado_mapper.mapear(resultados, data["tipoServicio"], data)
```

### 2. Endpoint Flask
```python
# microservicio_disponibilidad/app.py
@app.post("/disponibilidad")
def buscar_disponibilidad():
    data = request.get_json(force=True, silent=True)
    resultado = _service.buscar(data)
    if isinstance(resultado, dict) and "error" in resultado:
        return jsonify({"detail": resultado["error"]}), resultado.pop("status", 400)
    return jsonify(resultado), 200
```

### 3. Query principal PASEO (SQLAlchemy raw SQL)
```python
# microservicio_disponibilidad/services.py
rows = conn.execute(text(
    'SELECT e."idEvento", e."horaInicio", e."horaFin", e."capacidadMaxima", e."precioCOP", '
    '       u."idUsuario" as cuidador_id, u.nombre, u.apellido, '
    '       p."ciudadServicio", p."latitudServicio", p."longitudServicio", p."radioKmServicio" '
    'FROM servicios_evento e '
    'JOIN servicios_perfilcuidador p ON p."idCuidador_id" = e."idCuidador_id" '
    'JOIN servicios_usuario u ON u."idUsuario" = p."idCuidador_id" '
    'WHERE e."tipoServicio" = \'paseo\' AND e."diaSemana" = :dia '
    '  AND e."duracionSlotMinutos" IS NULL AND e.disponible AND u.verificado '
    'ORDER BY e."horaInicio"'
), {"dia": dia_semana}).fetchall()
```

### 4. Docker Compose — 3 servicios orquestados
```yaml
# docker-compose.yml
services:
  db:
    image: postgres:15-alpine
    # Base de datos compartida entre Django y Flask

  django:
    build: .                          # Dockerfile raíz
    environment:
      DISPONIBILIDAD_SERVICE_URL: http://disponibilidad:5001

  disponibilidad:
    build: ./microservicio_disponibilidad
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/pawswalks
```

## Respuesta esperada

```json
[
  {
    "cuidadorId": "uuid",
    "cuidadorNombre": "Carlos",
    "cuidadorApellido": "Ruiz",
    "tipoServicio": "paseo",
    "eventoId": "uuid",
    "fecha": "2026-04-20",
    "horaInicio": "09:00:00",
    "horaFin": "10:00:00",
    "tarifaHora": 25000,
    "tarifaTotal": 25000,
    "cupoMaximo": 4,
    "cuposDisponibles": 3,
    "distanciaKm": 1.2,
    "calificacionPromedio": 4.5,
    "calificacionCount": 10,
    "descripcionServicio": "Paseo profesional zona norte"
  }
]
```
