# Paws & Walks — Plataforma de Cuidado de Mascotas

> Plataforma web para la reserva de servicios de cuidado de mascotas (paseos y guarderías). Conecta dueños con cuidadores verificados, gestiona reservas con una máquina de estados robusta y calificaciones del servicio.

**Asignatura:** Arquitectura de Software — EAFIT 2026-I  
**Entrega:** 2 — Arquitectura Híbrida con Patrón Strangler

---

## Tabla de Contenidos

- [Características](#características)
- [Stack Tecnológico](#stack-tecnológico)
- [Arquitectura](#arquitectura)
  - [Contenedores](#contenedores)
  - [Servicios](#servicios)
  - [Patrones Implementados](#patrones-implementados)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Quick Start](#quick-start)
  - [Docker Compose (recomendado)](#docker-compose-recomendado)
  - [Desarrollo Local (sin Docker)](#desarrollo-local-sin-docker)
- [API REST](#api-rest)
- [Integraciones Externas](#integraciones-externas)
- [Internacionalización (i18n)](#internacionalización-i18n)
- [Tareas Asíncronas (Celery)](#tareas-asíncronas-celery)
- [Despliegue en AWS EC2](#despliegue-en-aws-ec2)
- [Troubleshooting](#troubleshooting)
- [Dependencias Principales](#dependencias-principales)
- [Integrantes](#integrantes)

---

## Características

| Módulo | Descripción |
|---|---|
| **Autenticación multi-rol** | Signup, login y logout para Dueños y Cuidadores |
| **Gestión de perfiles** | Usuarios y mascotas con imágenes |
| **Búsqueda de cuidadores** | Motor Flask con fallback automático a Django |
| **Reservas** | Sistema de paseos y guarderías con máquina de estados |
| **Chat** | Mensajería directa entre dueño y cuidador |
| **Calificaciones** | Reseñas y puntuaciones de servicios completados |
| **Notificaciones** | Sistema interno con tareas asíncronas vía Celery |
| **API REST** | Documentación automática con Swagger/OpenAPI |
| **Microservicios** | 2 servicios Flask independientes (patrón Strangler) |
| **Orquestación** | Docker Compose con Nginx como API Gateway |
| **i18n** | Soporte bilingüe Español/Inglés con `gettext` (sin textos quemados) |
| **Adaptadores externos** | OpenWeather (clima) y equipo aliado vía Adapter Pattern |

---

## Stack Tecnológico

```
Django 5 + DRF  ·  Flask (×2)  ·  PostgreSQL 15  ·  Redis 7
Celery 5  ·  Nginx  ·  Docker Compose
```

---

## Arquitectura

### Contenedores

```
              Internet
                  │
       Elastic IP (AWS EC2)
                  │
        ┌─────────┴──────────┐
        │     Nginx :80      │
        │    API Gateway     │
        └──┬──────────┬──┬───┘
           │          │  │
           ▼          ▼  ▼
       Django     Flask   Flask
       :8000      Disp.   Ratings
                  :5001   :5000
           │          │  │
           └──────────┴──┘
                    │
         ┌──────────┴──────────┐
         │   PostgreSQL  :5432 │
         │   Redis       :6379 │
         │   Celery Worker     │
         └─────────────────────┘
```

### Servicios

| Servicio | Tecnología | Puerto | Rol |
|---|---|---|---|
| `django_web` | Django 5 + DRF | `8000` | Monolito principal — vistas, API, modelos |
| `disponibilidad` | Flask + SQLAlchemy | `5001` | Búsqueda de cuidadores (Strangler) |
| `flask_ratings` | Flask + SQLAlchemy | `5000` | Calificaciones CRUD (Strangler) |
| `db` | PostgreSQL 15 | `5432` | Persistencia relacional |
| `redis` | Redis 7 | `6379` | Broker Celery + caché |
| `celery_worker` | Celery 5 | — | Notificaciones asíncronas |
| `nginx` | Nginx | `80` | API Gateway / reverse proxy |

### Patrones Implementados

| Patrón | Componente | Descripción |
|---|---|---|
| **Strangler** | `disponibilidad`, `flask_ratings` | 2 microservicios Flask extraen funcionalidades del monolito |
| **API Gateway** | `nginx.conf` | Nginx enruta tráfico entre servicios |
| **Adapter + DIP** | `weather_adapter.py`, `aliado_adapter.py` | `ClimaPort` y `AliadoPort` intercambiables vía Factory |
| **Factory** | `factory.py` | `NotificadorFactory`, `ClimaAdapterFactory`, `AliadoAdapterFactory` |
| **Builder** | `builder.py` | `SolicitudServicioBuilder` para construcción de entidades complejas |
| **Service Layer** | `service_layer/` | Presentación → Service → Domain → Infrastructure |
| **Message Queue** | Redis + Celery | 6 tareas asíncronas desacopladas del ciclo request/response |

---

## Estructura del Proyecto

```
paws_walks/
├── manage.py
├── requirements.txt                  # Desarrollo (SQLite, sin psycopg2)
├── requirements-prod.txt             # Producción (con psycopg2-binary)
├── Dockerfile                        # Imagen Django
├── docker-compose.yml                # 7 servicios orquestados
├── nginx.conf                        # Config API Gateway
├── C4_DIAGRAMS.md                    # Diagramas C1–C4 + deployment
│
├── scripts/
│   └── fill_translations.py          # Helper: rellena msgstr en locale/en
│
├── paws_walks/
│   ├── settings.py                   # BD, caché, Celery, APIs externas
│   ├── urls.py                       # Rutas principales
│   └── celery.py                     # Configuración Celery
│
├── servicios/                        # App principal Django
│   ├── models.py                     # Entidades ORM
│   ├── services.py                   # Fachada de re-exportación
│   ├── views.py                      # Vistas web (thin controllers)
│   ├── tasks.py                      # 6 tareas Celery asíncronas
│   │
│   ├── api/
│   │   ├── views.py                  # DRF APIViews (thin, delegan al Gateway)
│   │   ├── serializers.py            # Validación estructural
│   │   └── urls.py                   # Rutas /api/v1/
│   │
│   ├── domain/
│   │   ├── ports.py                  # ClimaPort, AliadoPort (interfaces ABC)
│   │   ├── builder.py                # SolicitudServicioBuilder
│   │   └── exceptions.py             # Excepciones de dominio
│   │
│   ├── infra/
│   │   ├── notificador.py            # Mock / LogOnly / Real / Async
│   │   ├── factory.py                # Factories de adaptadores y notificadores
│   │   ├── weather_adapter.py        # OpenWeatherAdapter implementa ClimaPort
│   │   └── aliado_adapter.py         # AliadoHttpAdapter + AliadoMockAdapter
│   │
│   └── service_layer/
│       ├── api_gateway.py            # ServiciosApiGatewayService (punto de entrada)
│       ├── aliado_servicios.py       # AliadoService (depende de AliadoPort)
│       └── clima_servicios.py        # ClimaService (depende de ClimaPort)
│
├── microservicio_disponibilidad/     # Flask: búsqueda de cuidadores
│   ├── app.py                        # POST /disponibilidad, GET /health
│   ├── services.py                   # Queries SQLAlchemy
│   ├── requirements.txt
│   └── Dockerfile
│
├── flask_ratings_service/            # Flask: calificaciones CRUD
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
│
└── locale/                           # i18n gettext
    ├── es/LC_MESSAGES/django.po      # Fuente español
    └── en/LC_MESSAGES/django.po      # 585 strings traducidos al inglés
```

---

## Quick Start

### Docker Compose (recomendado)

```bash
# 1. Clonar el repositorio
git clone <repo-url>
cd paws_walks

# 2. Variables de entorno (el proyecto funciona sin ellas en desarrollo)
cp .env.example .env

# 3. Levantar todos los servicios
docker-compose up --build

# 4. Migraciones (solo primera vez)
docker-compose exec django_web python manage.py migrate

# 5. Crear superusuario
docker-compose exec django_web python manage.py createsuperuser
```

**URLs de acceso:**

| Recurso | URL |
|---|---|
| Aplicación web | `http://localhost/login/` |
| Panel de administración | `http://localhost/admin/` |
| Documentación API (Swagger) | `http://localhost/api/docs/` |

```bash
# Detener servicios
docker-compose down

# Limpiar todo (incluye volumen de BD)
docker-compose down -v
```

### Desarrollo Local (sin Docker)

> Requiere Redis corriendo localmente para las tareas Celery.

```bash
# Instalar dependencias (SQLite, sin psycopg2)
pip install -r requirements.txt

# Migraciones y servidor de desarrollo
python manage.py migrate
python manage.py runserver

# Celery worker (terminal separada)
celery -A paws_walks worker -l info
```

---

## API REST

**Base URL:**  
- Docker: `http://localhost/api/`  
- Local: `http://localhost:8000/api/`  
- Documentación interactiva: `GET /api/docs/`

### Endpoints Públicos (sin autenticación)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/sistema/estado/` | Estado general del sistema |
| `GET` | `/api/v1/cuidadores/listado/` | Cuidadores verificados |
| `GET` | `/api/v1/aliado/estado/` | Estado del equipo aliado vía `AliadoPort` |

### Endpoints Autenticados

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/solicitudes/` | Crear solicitud de servicio |
| `GET` | `/api/v1/solicitudes/<uuid>/` | Detalle de solicitud |
| `POST` | `/api/v1/solicitudes/<uuid>/cancelar/` | Cancelar solicitud |
| `POST` | `/api/v1/disponibilidad/` | Buscar cuidadores disponibles |
| `GET` | `/api/v1/clima/?ciudad=<ciudad>` | Clima vía OpenWeatherAdapter |

### Endpoints Flask (enrutados por Nginx)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v2/calificaciones/` | Crear calificación |
| `GET` | `/api/v2/calificaciones/<user_id>/` | Calificaciones de un usuario |
| `GET` | `/health` | Health check Flask Ratings |

### Ejemplo — Respuesta del equipo aliado

```bash
curl http://localhost/api/v1/aliado/estado/
```

```json
{
  "fuente": "Equipo aliado (mock)",
  "disponible": true,
  "datos": {
    "sistema": "Servicio aliado de demostración",
    "estado": "operativo",
    "metricas": {
      "usuarios_activos": 142,
      "transacciones_dia": 38
    }
  },
  "consultado_en": "2026-05-06T23:51:22Z"
}
```

---

## Integraciones Externas

### OpenWeather (Adapter Pattern)

Configura `OPENWEATHER_API_KEY` en las variables de entorno.  
Sin clave, el sistema usa `ClimaAdapterMock` automáticamente.

### Equipo Aliado

Configura `ALIADO_API_URL` para activar `AliadoHttpAdapter`.  
Sin URL, usa `AliadoMockAdapter`.  
La vista `/integraciones/aliado/` expone el estado del aliado en la interfaz web.

---

## Internacionalización (i18n)

Soporte bilingüe completo (Español / Inglés) con `gettext`. Sin textos quemados en código ni templates.

```bash
# Extraer strings traducibles de templates y código Python
python manage.py makemessages -l es -l en   # requiere GNU gettext instalado

# Compilar archivos .po tras edición
python manage.py compilemessages

# Helper: rellena traducciones inglesas faltantes automáticamente
python scripts/fill_translations.py
```

El selector de idioma está disponible en el menú del header del dashboard.

---

## Tareas Asíncronas (Celery)

Las siguientes tareas son disparadas automáticamente por el `Notificador` cuando `ENV_TYPE=ASYNC`:

| Tarea | Descripción |
|---|---|
| `task_nueva_solicitud(solicitud_id)` | Notifica al cuidador de una nueva solicitud |
| `task_solicitud_aceptada(solicitud_id)` | Notifica al dueño cuando el cuidador acepta |
| `task_solicitud_rechazada(solicitud_id)` | Notifica al dueño cuando el cuidador rechaza |
| `task_servicio_completado(solicitud_id)` | Notifica + dispara solicitud de reseña pendiente |
| `task_reserva_cancelada(...)` | Notifica a la contraparte de la cancelación |
| `task_mensaje_chat(...)` | Notifica un nuevo mensaje de chat |

---

## Despliegue en AWS EC2

```bash
# 1. Conectar a la instancia
ssh -i paws-key.pem ubuntu@<elastic-ip>

# 2. Instalar Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu

# 3. Clonar y configurar
git clone <repo-url> && cd paws_walks
cp .env.example .env
# Editar .env: DATABASE_URL, OPENWEATHER_API_KEY, ALIADO_API_URL

# 4. Levantar y migrar
docker-compose up -d --build
docker-compose exec django_web python manage.py migrate

# 5. Verificar servicios
curl http://localhost/health
curl http://localhost/api/v1/sistema/estado/
```

**Puertos requeridos en Security Group:** `80` (HTTP), `22` (SSH).

---

## Troubleshooting

```bash
# Logs por servicio
docker-compose logs -f django_web
docker-compose logs -f celery_worker
docker-compose logs -f disponibilidad
docker-compose logs -f flask_ratings

# Verificar Redis
docker-compose exec redis redis-cli ping        # Esperado: PONG

# Verificar microservicio de disponibilidad
curl http://localhost:5001/health

# Reconstrucción limpia
docker-compose down -v
docker-compose build --no-cache
docker-compose up
```

---

## Dependencias Principales

| Librería | Versión | Uso |
|---|---|---|
| `Django` | 5.2.11 | Framework principal |
| `djangorestframework` | 3.16.1 | API REST |
| `drf-spectacular` | 0.27.0 | OpenAPI / Swagger |
| `celery` | 5.4.0 | Task queue asíncrono |
| `redis` | 5.2.1 | Broker + caché |
| `requests` | 2.32.3 | HTTP a microservicios y APIs externas |
| `Pillow` | 11.2.1 | Imágenes de perfil |
| `polib` | 1.2.0 | Compilación `.po` (helper i18n) |
| `psycopg2-binary` | 2.9.9 | Driver PostgreSQL (solo `requirements-prod.txt`) |

---

## Integrantes

| Nombre | Rol |
|---|---|
| Cristobal Gutierrez Castro | Desarrollo |
| Laura Sofia Aceros Monsalve | Desarrollo |
| Matias Martinez Moreno | Desarrollo |

---

*Universidad EAFIT · Arquitectura de Software · 2026-I*