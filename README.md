# Paws & Walks — Plataforma de Cuidado de Mascotas

Plataforma web para reserva de servicios de cuidado de mascotas (paseos y guarderías). Dueños buscan cuidadores disponibles, realizan reservas y califican el servicio. Cuidadores configuran disponibilidad y gestionan solicitudes entrantes.

Proyecto académico de Arquitectura de Software — Entrega 2. Implementa arquitectura híbrida con patrón Strangler, API Gateway (Nginx), Message Queue (Redis/Celery), Adapter Pattern para APIs externas e internacionalización completa con gettext.

**Stack:** Django 5 + DRF + Flask (x2) + PostgreSQL + Redis + Celery + Nginx + Docker Compose

---

## Características

- Autenticación multi-rol (Dueño/Cuidador) con signup, login y logout
- Gestión de perfiles de usuarios y mascotas
- Búsqueda de cuidadores disponibles (motor Flask, fallback Django)
- Sistema de reservas (paseos y guarderías) con máquina de estados
- Chat entre dueño y cuidador
- Calificaciones y reseñas de servicios
- Notificaciones internas
- API REST con documentación automática (Swagger/OpenAPI)
- 2 microservicios Flask (patrón Strangler)
- Orquestación Docker Compose con Nginx como API Gateway
- Soporte bilingüe Español/Inglés con gettext (sin textos quemados)
- Tareas asíncronas con Celery + Redis
- Adapter Pattern para OpenWeather (clima) y equipo aliado
- Integración con equipo aliado expuesta en vista web y endpoint API

---

## Arquitectura

### Contenedores

```
         Internet
             |
    Elastic IP (AWS EC2)
             |
     ┌───────┴────────┐
     │  Nginx :80     │
     │  API Gateway   │
     └──┬──────┬──┬───┘
        |      |  |
        v      v  v
  Django  Flask   Flask
  :8000  Disp.   Ratings
         :5001   :5000
        |      |  |
        └──────┴──┘
               |
        ┌──────┴──────┐
        | PostgreSQL  |
        | Redis :6379 |
        | CeleryWorker|
        └─────────────┘
```

### Componentes

| Servicio | Tecnologia | Puerto | Rol |
|---|---|---|---|
| django_web | Django 5 + DRF | 8000 | Monolito principal, vistas, API, modelos |
| disponibilidad | Flask + SQLAlchemy | 5001 | Busqueda de cuidadores (Strangler) |
| flask_ratings | Flask + SQLAlchemy | 5000 | Calificaciones CRUD (Strangler) |
| db | PostgreSQL 15 | 5432 | Persistencia |
| redis | Redis 7 | 6379 | Broker Celery + cache |
| celery_worker | Celery 5 | — | Notificaciones async |
| nginx | Nginx | 80 | API Gateway / reverse proxy |

### Patrones

- **Strangler Pattern**: 2 microservicios Flask extraen funcionalidades del monolito
- **API Gateway**: Nginx enruta trafico entre servicios
- **Adapter + DIP**: `ClimaPort` (OpenWeather), `AliadoPort` (equipo aliado) — intercambiables via Factory
- **Factory Pattern**: `NotificadorFactory`, `ClimaAdapterFactory`, `AliadoAdapterFactory`
- **Builder Pattern**: `SolicitudServicioBuilder` para entidades complejas
- **Service Layer**: Presentacion → Service → Domain → Infrastructure
- **Message Queue**: Redis/Celery para 6 tareas async

---

## Estructura del Proyecto

```
paws_walks/
├── manage.py
├── requirements.txt            # dev (SQLite, sin psycopg2)
├── requirements-prod.txt       # produccion (con psycopg2-binary)
├── Dockerfile                  # imagen Django (usa requirements-prod.txt)
├── docker-compose.yml          # 7 servicios
├── nginx.conf                  # API Gateway config
├── C4_DIAGRAMS.md              # diagramas C1-C4 + deployment
├── scripts/
│   └── fill_translations.py   # rellena msgstr en locale/en (helper dev)
│
├── paws_walks/
│   ├── settings.py             # BD, cache, Celery, APIs externas
│   ├── urls.py                 # rutas principales
│   └── celery.py               # configuracion Celery
│
├── servicios/                  # app principal Django
│   ├── models.py               # entidades ORM
│   ├── services.py             # fachada re-exportacion
│   ├── views.py                # vistas web (thin)
│   ├── tasks.py                # 6 tareas Celery async
│   │
│   ├── api/
│   │   ├── views.py            # DRF APIViews (thin, delegan al Gateway)
│   │   ├── serializers.py      # validacion estructural
│   │   └── urls.py             # rutas /api/v1/
│   │
│   ├── domain/
│   │   ├── ports.py            # ClimaPort, AliadoPort (interfaces ABC)
│   │   ├── builder.py          # SolicitudServicioBuilder
│   │   └── exceptions.py       # excepciones de dominio
│   │
│   ├── infra/
│   │   ├── notificador.py      # Mock / LogOnly / Real / Async
│   │   ├── factory.py          # NotificadorFactory, ClimaAdapterFactory, AliadoAdapterFactory
│   │   ├── weather_adapter.py  # OpenWeatherAdapter implementa ClimaPort
│   │   └── aliado_adapter.py   # AliadoHttpAdapter + AliadoMockAdapter implementan AliadoPort
│   │
│   └── service_layer/
│       ├── api_gateway.py      # ServiciosApiGatewayService (punto de entrada)
│       ├── aliado_servicios.py # AliadoService (depende de AliadoPort)
│       ├── clima_servicios.py  # ClimaService (depende de ClimaPort)
│       └── ...
│
├── microservicio_disponibilidad/  # Flask: busqueda de cuidadores
│   ├── app.py                     # POST /disponibilidad, GET /health
│   ├── services.py                # SQLAlchemy query
│   ├── requirements.txt
│   └── Dockerfile
│
├── flask_ratings_service/         # Flask: calificaciones CRUD
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
│
└── locale/                        # i18n gettext
    ├── es/LC_MESSAGES/django.po   # fuente espanol
    └── en/LC_MESSAGES/django.po   # 585 strings traducidos al ingles
```

---

## Quick Start

### Docker Compose (recomendado)

```bash
# 1. Clonar y entrar al proyecto
git clone <repo-url>
cd paws_walks

# 2. Variables de entorno opcionales (dev funciona sin ellas)
cp .env.example .env

# 3. Levantar todo
docker-compose up --build

# 4. Migraciones (primera vez)
docker-compose exec django_web python manage.py migrate

# 5. Crear superusuario
docker-compose exec django_web python manage.py createsuperuser

# Acceso
# Web:    http://localhost/login/
# Admin:  http://localhost/admin/
# Docs:   http://localhost/api/docs/
```

```bash
# Detener
docker-compose down

# Limpiar todo (incluye volumen BD)
docker-compose down -v
```

### Desarrollo local (sin Docker)

```bash
# Instalar dependencias (SQLite, sin psycopg2)
pip install -r requirements.txt

# Migraciones y servidor
python manage.py migrate
python manage.py runserver

# Celery worker (otra terminal, requiere Redis)
celery -A paws_walks worker -l info
```

---

## API REST

**Base URL:** `http://localhost/api/` (Docker) o `http://localhost:8000/api/` (local)

Documentacion interactiva: `GET /api/docs/`

### Endpoints publicos (sin autenticacion)

```
GET  /api/v1/sistema/estado/        Estado general del sistema (para consumo externo)
GET  /api/v1/cuidadores/listado/    Listado de cuidadores verificados
GET  /api/v1/aliado/estado/         Consume el endpoint del equipo aliado via AliadoPort
```

### Endpoints autenticados

```
POST /api/v1/solicitudes/                       Crear solicitud de servicio
GET  /api/v1/solicitudes/<uuid>/                Ver detalle
POST /api/v1/solicitudes/<uuid>/cancelar/       Cancelar solicitud
POST /api/v1/disponibilidad/                    Buscar cuidadores disponibles
GET  /api/v1/clima/?ciudad=<ciudad>             Clima via OpenWeatherAdapter
```

### Endpoints Nginx (Flask directo)

```
POST /api/v2/calificaciones/                    Crear calificacion (Flask Ratings)
GET  /api/v2/calificaciones/<user_id>/          Ver calificaciones de usuario
GET  /health                                    Health check Flask Ratings
```

### Ejemplo consumo aliado

```bash
# Consume el endpoint del equipo aliado (mock sin ALIADO_API_URL configurada)
curl http://localhost/api/v1/aliado/estado/
```

```json
{
  "fuente": "Equipo aliado (mock)",
  "disponible": true,
  "datos": {
    "sistema": "Servicio aliado de demostracion",
    "estado": "operativo",
    "metricas": {"usuarios_activos": 142, "transacciones_dia": 38}
  },
  "consultado_en": "2026-05-06T23:51:22Z"
}
```

Para conectar con el aliado real: setear `ALIADO_API_URL=http://<ip-aliado>/` en docker-compose.yml o `.env`.

---

## Integraciones externas

### OpenWeather (API de terceros — Adapter Pattern)

Setear `OPENWEATHER_API_KEY` en variables de entorno. Sin clave usa `ClimaAdapterMock`.

### Equipo aliado

Setear `ALIADO_API_URL` para activar `AliadoHttpAdapter`. Sin URL usa `AliadoMockAdapter`.
La vista web en `/integraciones/aliado/` muestra el estado del aliado en la aplicacion.

---

## Internacionalizacion (i18n)

Soporte bilingue completo (Espanol/Ingles) via gettext. Sin textos quemados en codigo.

```bash
# Extraer strings traducibles de templates y Python
python manage.py makemessages -l es -l en   # requiere GNU gettext

# Despues de editar los .po
python manage.py compilemessages

# Helper: rellena traducciones inglesas faltantes
python scripts/fill_translations.py
```

Cambiar idioma en la UI: menu desplegable en el header del dashboard.

---

## Tareas Asincronas (Celery)

```python
# Disparadas automaticamente por el Notificador segun ENV_TYPE=ASYNC
task_nueva_solicitud(solicitud_id)       # notifica al cuidador
task_solicitud_aceptada(solicitud_id)    # notifica al dueno
task_solicitud_rechazada(solicitud_id)   # notifica al dueno
task_servicio_completado(solicitud_id)   # notifica + dispara resena pendiente
task_reserva_cancelada(...)              # notifica a la contraparte
task_mensaje_chat(...)                   # notifica mensaje de chat
```

---

## Despliegue AWS Academy (EC2)

```bash
# 1. SSH a la instancia
ssh -i paws-key.pem ubuntu@<elastic-ip>

# 2. Instalar Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu

# 3. Clonar y configurar
git clone <repo-url> && cd paws_walks
cp .env.example .env
# editar .env: DATABASE_URL, OPENWEATHER_API_KEY, ALIADO_API_URL

# 4. Levantar
docker-compose up -d --build
docker-compose exec django_web python manage.py migrate

# 5. Verificar
curl http://localhost/health
curl http://localhost/api/v1/sistema/estado/
```

Puertos abiertos en Security Group: 80 (HTTP), 22 (SSH).

---

## Troubleshooting

```bash
# Logs por servicio
docker-compose logs -f django_web
docker-compose logs -f celery_worker
docker-compose logs -f disponibilidad
docker-compose logs -f flask_ratings

# Redis OK?
docker-compose exec redis redis-cli ping   # debe responder PONG

# Flask disponibilidad OK?
curl http://localhost:5001/health

# Limpiar y reconstruir
docker-compose down -v
docker-compose build --no-cache
docker-compose up
```

---

## Dependencias principales

| Libreria | Version | Uso |
|---|---|---|
| Django | 5.2.11 | Framework principal |
| djangorestframework | 3.16.1 | API REST |
| drf-spectacular | 0.27.0 | OpenAPI / Swagger |
| celery | 5.4.0 | Task queue async |
| redis | 5.2.1 | Broker + cache |
| requests | 2.32.3 | HTTP a microservicios y APIs externas |
| Pillow | 11.2.1 | Imagenes de perfil |
| polib | 1.2.0 | Compilacion .po (i18n helper) |
| psycopg2-binary | 2.9.9 | Driver PostgreSQL (solo requirements-prod.txt) |

---

## Integrantes

- Cristobal Gutierrez Castro
- Laura Sofia Aceros Monsalve
- Matias Martinez Moreno

**Asignatura:** Arquitectura de Software — EAFIT 2026-I
