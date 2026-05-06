# Paws & Walks — Plataforma de Cuidado de Mascotas

Plataforma web para reserva de servicios de cuidado de mascotas (paseos y guarderías). Los dueños buscan cuidadores disponibles, realizan reservas, pagan y califican el servicio. Los cuidadores configuran su disponibilidad y gestionan solicitudes entrantes.

Proyecto académico de Arquitectura de Software que implementa una arquitectura de microservicios con patrón Strangler, API Gateway, Message Queue, e internacionalización completa.

**Stack:** Django 5 + DRF + Flask Microservicios + PostgreSQL + Redis + Docker + Nginx

---

## 🎯 Características Principales

- ✅ Autenticación multi-rol (Dueño/Cuidador) con signup/login/logout
- ✅ Gestión de perfiles de usuarios y mascotas
- ✅ Catálogo de cuidadores con búsqueda de disponibilidad
- ✅ Sistema de reservas (paseos y guarderías) con máquina de estados
- ✅ Chat en tiempo real entre dueño y cuidador
- ✅ Calificaciones y reseñas de servicios
- ✅ Notificaciones internas (sistema)
- ✅ API REST con documentación automática (Swagger/OpenAPI)
- ✅ Microservicios con Flask (patrón Strangler)
- ✅ Orquestación Docker Compose
- ✅ Soporte multiidioma (Español/Inglés)
- ✅ Caché con Redis y tareas async con Celery
- ✅ Adapter Pattern para APIs externas (OpenWeather)

---

## 🏗️ Arquitectura

### Diagrama de Contenedores

```
                    ┌─────────────────┐
                    │  NGINX Gateway  │
                    │   (Puerto 80)   │
                    └────────┬────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
                ▼            ▼            ▼
            Django       Flask         Flask
          (:8000)   Disponibilidad  Ratings
                      (:5001)       (:5000)
                │            │            │
                └────────────┼────────────┘
                             │
                    ┌────────┴────────┐
                    │    PostgreSQL   │
                    │   Redis Cache   │
                    │  Celery Worker  │
                    └─────────────────┘
```

### Componentes

| Componente | Tecnología | Puerto | Función |
|---|---|---|---|
| **Web Principal** | Django 5 + DRF | 8000 | Monolito con vistas, API, modelos |
| **Microservicio 1** | Flask + SQLAlchemy | 5001 | Búsqueda de disponibilidad (Strangler) |
| **Microservicio 2** | Flask + SQLAlchemy | 5000 | Calificaciones (Strangler) |
| **Base de Datos** | PostgreSQL | 5432 | Persistencia de datos |
| **Cache/Queue** | Redis | 6379 | Celery broker, sesiones, caché |
| **Task Queue** | Celery + Redis | - | Notificaciones async, emails, reportes |
| **API Gateway** | Nginx | 80 | Reverse proxy, ruteo, load balancing |

### Patrones Arquitectónicos

- **Strangler Pattern**: Microservicios Flask extraen funcionalidades del monolito Django
- **API Gateway**: Nginx centraliza el ruteo (único punto de entrada)
- **Service Layer**: Presentación → Service → Domain → Infrastructure
- **Adapter Pattern**: Consumo de APIs externas via adapters intercambiables
- **Factory Pattern**: Notificadores intercambiables (Mock/LogOnly/Real)
- **Builder Pattern**: Construcción fluida de entidades complejas

---

## 📁 Estructura del Proyecto

```
paws_walks/
├── README.md                          ← Este archivo
├── .env.example                       ← Variables de entorno plantilla
├── requirements.txt                   ← Dependencias Python
├── manage.py                          ← Script Django
├── Dockerfile                         ← Imagen Django
├── docker-compose.yml                 ← Orquestación servicios
│
├── paws_walks/                        ← Proyecto Django
│   ├── settings.py                    ← Configuración (BD, cache, Celery, APIs)
│   ├── urls.py                        ← Enrutamiento principal
│   ├── wsgi.py                        ← WSGI app
│   └── celery.py                      ← Configuración Celery
│
├── servicios/                         ← App principal
│   ├── models.py                      ← Entidades ORM (usuario, mascota, solicitud, etc.)
│   ├── services.py                    ← Fachada servicios (re-exportación)
│   ├── views.py                       ← Vistas web (thin, delegan)
│   ├── tasks.py                       ← Tareas Celery async
│   │
│   ├── api/
│   │   ├── views.py                   ← APIViews DRF (thin, delegan al Gateway)
│   │   ├── serializers.py             ← Validadores estructurales
│   │   └── urls.py                    ← Rutas API REST
│   │
│   ├── domain/
│   │   ├── builder.py                 ← SolicitudServicioBuilder (patrón Builder)
│   │   └── exceptions.py              ← Excepciones de dominio
│   │
│   ├── infra/
│   │   ├── notificador.py             ← Strategy: Mock/LogOnly/Real
│   │   ├── factory.py                 ← NotificadorFactory
│   │   ├── weather_adapter.py         ← Adapter para OpenWeather
│   │   └── __init__.py
│   │
│   ├── service_layer/
│   │   ├── api_gateway.py             ← ServiciosApiGatewayService (punto entrada)
│   │   ├── api_validadores.py         ← Validadores, mappers, política de acceso
│   │   ├── api_servicios.py           ← Servicios creación/cancelación
│   │   ├── api_disponibilidad_servicios.py ← Orquesta búsqueda
│   │   ├── disponibilidad.py          ← BuscarCuidadoresDisponiblesService
│   │   ├── reservas_servicios.py      ← Gestión reservas
│   │   ├── usuarios_servicios.py      ← Gestión usuarios
│   │   ├── catalogo_cuidador_servicios.py
│   │   ├── perfiles_mascotas.py
│   │   ├── interacciones.py           ← Chat
│   │   ├── reputacion_servicios.py    ← Reseñas/calificaciones
│   │   ├── validacion_servicios.py
│   │   └── utils.py                   ← Funciones puras (haversine, etc.)
│   │
│   └── templates/servicios/           ← Templates HTML (traducibles)
│       ├── login.html
│       ├── signup.html
│       ├── dashboard_dueño.html
│       ├── dashboard_cuidador.html
│       └── ... (16 templates más)
│
├── microservicio_disponibilidad/      ← Microservicio Flask
│   ├── app.py                         ← Endpoint POST /disponibilidad
│   ├── services.py                    ← BuscarDisponibilidadService (SQLAlchemy)
│   ├── db.py                          ← Engine SQLAlchemy
│   ├── utils.py                       ← Helpers
│   ├── requirements.txt               ← Flask, SQLAlchemy
│   ├── Dockerfile
│   └── README.md                      ← Documentación completa
│
├── microservicio_ratings/             ← Microservicio Flask (futuro)
│   ├── app.py
│   ├── services.py
│   ├── db.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── locale/                            ← Archivos i18n
│   ├── es/LC_MESSAGES/
│   │   ├── django.po                  ← Traducciones español
│   │   └── django.mo                  ← Compiladas (binario)
│   └── en/LC_MESSAGES/
│       ├── django.po                  ← Traducciones inglés
│       └── django.mo
│
└── C4_DIAGRAMS.md                     ← Diagramas arquitectónicos C4
```

---

## 🚀 Quick Start

### Requisitos

- **Docker & Docker Compose** (recomendado)
- **Python 3.11+** (desarrollo local sin Docker)
- **PostgreSQL 15+** (si no usa Docker)
- **Redis 7+** (si no usa Docker)

### Opción 1: Docker Compose (Recomendado)

```bash
# 1. Clonar/descargar el proyecto
cd paws_walks

# 2. Configurar variables de entorno
cp .env.example .env
# Editar .env según sea necesario (opcional para dev local)

# 3. Levantar todos los servicios
docker-compose up --build

# 4. En otra terminal, ejecutar migraciones
docker-compose exec django python manage.py migrate

# 5. Crear superusuario (admin)
docker-compose exec django python manage.py createsuperuser

# 6. Acceder a la plataforma
# Web: http://localhost:8000/login/
# Admin: http://localhost:8000/admin/
# API Docs (Swagger): http://localhost:8000/api/docs/
```

**Detener servicios:**
```bash
docker-compose down
```

### Opción 2: Desarrollo Local (Sin Docker)

```bash
# 1. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
# Editar settings.py o crear .env (usar python-decouple si es necesario)

# 4. Asegurar PostgreSQL/Redis ejecutándose en tu máquina

# 5. Migraciones
python manage.py migrate

# 6. Crear superusuario
python manage.py createsuperuser

# 7. Ejecutar servidor dev
python manage.py runserver

# En otra terminal: ejecutar Celery worker (para tareas async)
celery -A paws_walks worker -l info

# 8. Acceder
# Web: http://localhost:8000/login/
# Admin: http://localhost:8000/admin/
```

---

## 📡 API REST Endpoints

**Base URL:** `http://localhost:8000/api/` (en Docker: `http://localhost/api/`)

### Documentación Interactiva

- **Swagger UI:** http://localhost:8000/api/docs/
- **Schema OpenAPI:** http://localhost:8000/api/schema/

### Endpoints Públicos (sin autenticación)

#### 1. Estado del Sistema
```
GET /api/v1/sistema/estado/
```

**Respuesta:**
```json
{
  "total_usuarios": 45,
  "total_dueños": 25,
  "total_cuidadores": 20,
  "total_solicitudes": 150,
  "solicitudes_completadas": 120,
  "solicitudes_pendientes": 15,
  "solicitudes_mes": 30,
  "total_resenas": 85,
  "timestamp": "2026-05-06T10:30:00Z"
}
```

**Uso:**
```bash
curl -X GET http://localhost:8000/api/v1/sistema/estado/
```

#### 2. Listado de Cuidadores Verificados
```
GET /api/v1/cuidadores/listado/
```

**Respuesta:**
```json
{
  "count": 20,
  "resultados": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "nombre": "María García",
      "ciudad": "Medellín",
      "foto": "/media/fotos/maria.jpg",
      "verificado": true,
      "total_reseñas": 42,
      "rating_promedio": 4.8
    },
    ...
  ],
  "timestamp": "2026-05-06T10:35:00Z"
}
```

**Uso:**
```bash
curl -X GET http://localhost:8000/api/v1/cuidadores/listado/
```

### Endpoints Autenticados (requieren login)

#### 3. Crear Solicitud de Servicio
```
POST /api/v1/solicitudes/
Content-Type: application/json
```

**Payload:**
```json
{
  "idDueño_id": "dueño-uuid",
  "idMascota_id": "mascota-uuid",
  "tipoServicio": "paseo",
  "fecha": "2026-05-10",
  "duracionMinutos": 60,
  "ubicacionParcela": "Cra 5 #3-45, Medellín"
}
```

**Respuesta:**
```json
{
  "id": "solicitud-uuid",
  "estado": "pendiente",
  "tipoServicio": "paseo",
  "fecha": "2026-05-10",
  ...
}
```

#### 4. Ver Detalles de Solicitud
```
GET /api/v1/solicitudes/<uuid>/
```

#### 5. Cancelar Solicitud
```
POST /api/v1/solicitudes/<uuid>/cancelar/
```

#### 6. Buscar Disponibilidad de Cuidadores
```
POST /api/v1/disponibilidad/
Content-Type: application/json
```

**Payload:**
```json
{
  "tipoServicio": "paseo",
  "fecha": "2026-05-10",
  "duracionMinutos": 60
}
```

**Respuesta:**
```json
{
  "disponibles": [
    {
      "id": "cuidador-uuid",
      "nombre": "Carlos López",
      "ciudad": "Medellín",
      "rating": 4.7,
      "precio_por_hora": 25000
    },
    ...
  ]
}
```

#### 7. Obtener Clima de Ciudad
```
GET /api/v1/clima/?ciudad=Medellín
```

**Respuesta:**
```json
{
  "ciudad": "Medellín",
  "temperatura": 22,
  "descripcion": "Parcialmente nublado",
  "humedad": 65,
  "viento": 8
}
```

---

## 🔧 Desarrollo

### Ejecutar Tests

```bash
# Todos los tests
python manage.py test

# Tests de un módulo específico
python manage.py test servicios

# Con cobertura
pip install coverage
coverage run --source='.' manage.py test
coverage report
```

### Makemigrations y Migrar

```bash
# Detectar cambios en modelos
python manage.py makemigrations

# Aplicar migraciones
python manage.py migrate

# Ver estado de migraciones
python manage.py showmigrations
```

### Gestionar Traducciones (i18n)

```bash
# Marcar strings traducibles en código
# En templates: {% trans "Texto" %} o {% blocktrans %}...{% endblocktrans %}
# En Python: from django.utils.translation import gettext as _; _("Texto")

# Extraer mensajes de código
python manage.py makemessages -l es -l en

# Después de traducir en .po files, compilar
python manage.py compilemessages
```

### Celery Tasks (Async Jobs)

Ejecutar Celery worker en desarrollo:

```bash
celery -A paws_walks worker -l info
```

**Tasks disponibles** (`servicios/tasks.py`):
- `task_nueva_solicitud` — Notificación cuando se crea solicitud
- `task_solicitud_aceptada` — Notificación cuando se acepta solicitud
- `task_solicitud_rechazada` — Notificación cuando se rechaza solicitud
- `task_servicio_completado` — Notificación cuando se completa servicio
- `task_reserva_cancelada` — Notificación cuando se cancela reserva
- `task_mensaje_chat` — Notificación de mensaje chat

### Logs

```bash
# Logs de Django
docker-compose logs -f django

# Logs de Celery worker
docker-compose logs -f celery_worker

# Logs de disponibilidad (Flask)
docker-compose logs -f disponibilidad

# Todos los servicios
docker-compose logs -f
```

---

## 🏭 Microservicios

### Microservicio Disponibilidad (Flask)

Servicio independiente que busca cuidadores disponibles. Motor de matching del negocio.

**Por qué microservicio:**
- Mayor tráfico de lectura → escala horizontal sin afectar core transaccional
- Solo lee BD (nunca escribe) → sin sincronización complicada
- Input/output bien definidos → contrato HTTP limpio

**Endpoint:**
```
POST /disponibilidad
```

**Documentación completa:** `microservicio_disponibilidad/README.md`

---

## 🌍 Internacionalización (i18n)

La plataforma soporta Español e Inglés.

**Cambiar idioma:**
- URL: `/i18n/setlang/?next=/&language=en` (Inglés)
- URL: `/i18n/setlang/?next=/&language=es` (Español)

**Archivos de traducción:**
```
locale/
├── es/LC_MESSAGES/
│   ├── django.po        (fuente: 543 strings)
│   └── django.mo        (compilado)
└── en/LC_MESSAGES/
    ├── django.po
    └── django.mo
```

---

## 🔐 Seguridad

- ✅ CSRF protection habilitada (middleware + tokens en formularios)
- ✅ Password validation (longitud mínima, complejidad)
- ✅ Session authentication + Token auth (futuro)
- ✅ XFrameOptionsMiddleware (protege contra clickjacking)
- ✅ Secrets via variables de entorno (no en código)
- ✅ Nginx como WAF proxy en Docker

**Antes de producción:**
1. Cambiar `SECRET_KEY` en settings.py
2. Establecer `DEBUG = False`
3. Configurar `ALLOWED_HOSTS` con dominios reales
4. Usar base de datos PostgreSQL remota (no SQLite)
5. Configurar HTTPS/SSL en Nginx
6. Validar OPENWEATHER_API_KEY y otras APIs externas

---

## 📦 Dependencias Principales

| Librería | Versión | Función |
|---|---|---|
| **Django** | 5.2.11 | Framework web principal |
| **djangorestframework** | 3.16.1 | API REST toolkit |
| **drf-spectacular** | 0.27.0 | OpenAPI schema + Swagger UI |
| **requests** | 2.32.3 | Cliente HTTP (llamadas a microservicios) |
| **psycopg2-binary** | 2.9.9 | Driver PostgreSQL |
| **celery** | 5.4.0 | Task queue async |
| **redis** | 5.2.1 | Cache + Celery broker |
| **Pillow** | 11.2.1 | Procesamiento imágenes |
| **polib** | 1.2.0 | Gestión archivos .po (traducciones) |

Instalar todas:
```bash
pip install -r requirements.txt
```

---

## 🚢 Deployment

### AWS Academy EC2 (Placeholder)

```bash
# 1. SSH en instancia
ssh -i paws-key.pem ubuntu@<instance-ip>

# 2. Instalar Docker + Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu

# 3. Clonar repositorio
git clone <repo-url>
cd paws_walks

# 4. Configurar .env
nano .env
# Establecer DATABASE_URL con RDS endpoint, etc.

# 5. Levantar servicios
docker-compose -f docker-compose.yml up -d

# 6. Ejecutar migraciones
docker-compose exec django python manage.py migrate

# 7. Ver logs
docker-compose logs -f
```

**Configuración Nginx en producción:**
- Certificados SSL/TLS (Let's Encrypt)
- Proxy reverso configurado
- Rate limiting para APIs
- Gzip compression
- Cache headers

---

## 🐛 Troubleshooting

### Docker no se levanta
```bash
# Limpiar volúmenes y levantar nuevamente
docker-compose down -v
docker-compose build --no-cache
docker-compose up
```

### Migraciones fallidas
```bash
# Revisar logs
docker-compose logs django

# Rollback última migración
docker-compose exec django python manage.py migrate servicios <numero-anterior>
```

### Celery no procesa tareas
```bash
# Verificar Redis conectado
docker-compose exec redis redis-cli ping
# Debe responder: PONG

# Ver tareas en cola
docker-compose exec redis redis-cli KEYS "*"

# Reiniciar Celery worker
docker-compose restart celery_worker
```

### Microservicio Flask no responde
```bash
# Verificar endpoint
curl -X GET http://localhost:5001/health

# Revisar logs
docker-compose logs disponibilidad

# Ejecutar fallback interno Django
# (automático si DISPONIBILIDAD_SERVICE_URL está vacío)
```

---

## 👥 Integrantes

- Cristóbal Gutiérrez Castro
- Laura Sofía Aceros Monsalve  
- Matías Martínez Moreno

---

## 📝 Licencia

Este proyecto es parte de la asignatura "Arquitectura de Software" de la EAFIT.

---

## 📚 Referencias

- [Django 5 Documentation](https://docs.djangoproject.com/en/5.2/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Docker Documentation](https://docs.docker.com/)
- [Celery Documentation](https://docs.celeryproject.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Flask Documentation](https://flask.palletsprojects.com/)

---

## 🔗 Documentación Adicional

- **Arquitectura Detallada:** `C4_DIAGRAMS.md`
- **Microservicio Disponibilidad:** `microservicio_disponibilidad/README.md`
- **Configuración Ambiente:** `.env.example`
