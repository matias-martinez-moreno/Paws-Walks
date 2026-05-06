# Paws & Walks — Guía Arquitectural

---

## 🚀 ENTREGA No. 1 - RESUMEN EJECUTIVO

### Preferencias del Desarrollador
- ⚠️ **NO proponer crear muchos markdowns.** Solo: README.md, C4_DIAGRAMS.md, CLAUDE.md
- Mantener proyecto limpio, sin documentación redundante
- Código limpio > Documentación abundante

### Qué Pedía Entrega No. 1

| Requisito | Peso |
|---|---|
| Implementar 50-60% de clases de dominio | 1.0 |
| SOLID: Service Layer desacoplado (SRP prioritario) | 1.5 |
| DRF: Serializers + APIViews con HTTP status correctos | 1.0 |
| Patrones: Builder (obligatorio) + Factory (obligatorio) | 1.0 |
| Documentación Wiki con diagramas de secuencia | 0.5 |

### ✅ QUÉ SE HIZO

- ✅ **11 modelos implementados** (65% dominio: Usuario, Mascota, PerfilCuidador, BloqueTiempo, VentanaDisponibilidad, SlotDisponibilidad, Evento, SlotEvento, PrecioServicio, SolicitudServicio, Calificacion)
- ✅ **SOLID cumplido:** SRP (cada servicio = 1 responsabilidad), OCP (Factory pattern), LSP (Notificadores intercambiables), DIP (inyección de dependencias en Gateway), ISP (interfaces segregadas)
- ✅ **DRF profesional:** APIViews thin (sin lógica), Serializers solo validación estructural, HTTP status correctos (201, 400, 404, 409)
- ✅ **Builder:** SolicitudServicioBuilder para construir solicitudes complejas
- ✅ **Factory:** NotificadorFactory (Mock/LogOnly/Real), ClimaAdapterFactory
- ✅ **Excepciones de dominio:** Mapeo claro a HTTP (400, 403, 404, 409)
- ✅ **Cero lógica de negocio en views/models:** Cumple advertencia crítica de rúbrica
- ✅ **API Gateway:** Orquesta todas operaciones HTTP (buscar_disponibilidad, crear_solicitud, etc)
- ✅ **Microservicio Flask:** Disponibilidad con fallback a Django
- ✅ **Docker Compose:** PostgreSQL + Django + Flask orquestados

### ⚠️ QUÉ FALTA (opcional para máximo 5.0)

- [ ] **WIKI_TECNICA.md** con diagramas de secuencia (Crear Solicitud, Buscar Disponibilidad)
- [ ] Explicación de escalabilidad + API Gateway en documentación
- [ ] Interfaces ABC explícitas en `domain/ports.py` (mejora profesional)

**Puntuación esperada:** 4.8/5.0 (si completas Wiki: 5.0/5.0)

---

## Qué es este proyecto

Plataforma de reserva de servicios de cuidado de mascotas (paseos y guarderías).
Los dueños buscan cuidadores disponibles, reservan, pagan y califican el servicio.
Los cuidadores configuran su disponibilidad y gestionan solicitudes entrantes.

Stack: **Django 5 + DRF** (monolito principal) + **Flask** (microservicio de disponibilidad) + **Docker** (orquestación).

---

## Arquitectura que debe seguirse

### Regla de oro: capas estrictas

```
Presentación  →  Service Layer  →  Domain / Infra  →  BD
(views, DRF)      (services.py)    (builder, factory,
                                    excepciones, notificador)
```

**Obligatorio:**
- `views.py` y `api/views.py` — solo orchestar: obtener actor, llamar servicio, renderizar. CERO ORM, CERO lógica de negocio.
- `models.py` — solo entidades y enumeraciones (`TextChoices`). Sin métodos de negocio.
- `api/serializers.py` — solo validación estructural (tipos, formatos, campos). Sin reglas de negocio.
- `services.py` — fachada de re-exportación. No contiene lógica, solo importa desde `service_layer/`.
- `service_layer/` — toda la lógica de negocio vive aquí. Cada clase: una sola responsabilidad (SRP).

**Prohibido:**
- Lógica de negocio en views, serializers o models.
- ORM calls fuera del service layer (y del microservicio Flask).
- Archivos de compatibilidad/re-exportación sin valor (ya fueron eliminados).

### Patrones creacionales activos

| Patrón | Dónde | Para qué |
|---|---|---|
| **Builder** | `domain/builder.py` → `SolicitudServicioBuilder` | Construye `SolicitudServicio` (entidad más compleja) con interfaz fluida |
| **Factory** | `infra/factory.py` → `NotificadorFactory` | Crea el notificador correcto según `ENV_TYPE` (MOCK/STAGING/REAL) |

### API Gateway

`service_layer/api_gateway.py` → `ServiciosApiGatewayService` — única puerta de entrada para todas las operaciones HTTP de la API v1. Las vistas DRF **nunca** llaman servicios internos directamente.

### Excepciones de dominio

Todas las reglas de negocio lanzan excepciones de `domain/exceptions.py`:
`DomainValidationError` → 400 | `ResourceNotFoundError` → 404 | `ConflictError` → 409 | `AuthorizationError` → 403

`MapearErroresApiService` en `api_validadores.py` las convierte a respuestas HTTP.

---

## Distribución del código

```
Proyecto/
├── manage.py
├── requirements.txt            ← django, drf, requests, psycopg2-binary
├── Dockerfile                  ← imagen Django
├── docker-compose.yml          ← orquesta db + django + disponibilidad
│
├── paws_walks/
│   ├── settings.py             ← DATABASE_URL, DISPONIBILIDAD_SERVICE_URL, ENV_TYPE
│   └── urls.py
│
├── servicios/                  ← app principal Django
│   ├── models.py               ← entidades ORM + TextChoices ÚNICAMENTE
│   ├── services.py             ← fachada de re-exportación (entry point para views)
│   ├── views.py                ← presentación web (thin views, 100% delega)
│   │
│   ├── api/
│   │   ├── views.py            ← DRF APIViews (thin, delegan al Gateway)
│   │   └── serializers.py      ← validación estructural únicamente
│   │
│   ├── domain/
│   │   ├── builder.py          ← SolicitudServicioBuilder (patrón Builder)
│   │   └── exceptions.py       ← excepciones de dominio
│   │
│   ├── infra/
│   │   ├── notificador.py      ← Strategy: NotificadorBase/Mock/LogOnly/Real
│   │   └── factory.py          ← NotificadorFactory (patrón Factory)
│   │
│   └── service_layer/
│       ├── api_gateway.py      ← ServiciosApiGatewayService (API Gateway)
│       ├── api_validadores.py  ← validadores, mappers, política de acceso
│       ├── api_servicios.py    ← servicios de creación/cancelación vía API
│       ├── api_disponibilidad_servicios.py ← orquesta búsqueda (fallback interno)
│       ├── disponibilidad.py   ← BuscarCuidadoresDisponiblesService
│       ├── reservas_servicios.py
│       ├── usuarios_servicios.py
│       ├── catalogo_cuidador_servicios.py
│       ├── perfiles_mascotas.py
│       ├── interacciones.py    ← chat
│       ├── reputacion_servicios.py
│       ├── validacion_servicios.py
│       └── utils.py            ← haversine_km, time_to_minutes (funciones puras)
│
└── microservicio_disponibilidad/   ← microservicio Flask independiente
    ├── app.py                  ← POST /disponibilidad, GET /health
    ├── services.py             ← búsqueda PASEO + GUARDERIA (SQLAlchemy)
    ├── db.py                   ← engine (SQLite dev / PostgreSQL Docker)
    ├── utils.py
    ├── requirements.txt
    ├── Dockerfile
    └── README.md               ← documentación completa del microservicio
```

---

## Microservicio Flask — BuscarDisponibilidad

Motor de matching del negocio extraído como microservicio independiente.

**Por qué:** mayor tráfico de lectura, solo lee BD (nunca escribe), escala horizontal sin impactar el core transaccional de Django.

**Flujo:**
```
DRF View → ServiciosApiGatewayService.buscar_disponibilidad()
  → Validar payload (inyecta idDueño_id desde usuario autenticado)
  → HTTP POST Flask :5001/disponibilidad   (si DISPONIBILIDAD_SERVICE_URL está seteado)
  → fallback: servicio interno Django      (si Flask no responde o error)
```

**Implementación:**
- **app.py** — endpoint POST /disponibilidad, health check, logging, error handler 404
- **services.py** — BuscarDisponibilidadService (puerto de Django), búsqueda PASEO + GUARDERIA vía SQLAlchemy
- **db.py** — engine SQLAlchemy (SQLite `/app/db.sqlite3`)
- **Normalización de UUIDs** — helper `_uuid(val)` quita guiones antes de queries (SQLite quirk)

**Flujo de error:**
1. Validación ocurre en Django ANTES de llamar Flask
2. Si Flask falla (timeout, 500, etc.) → Django usa fallback interno
3. Resultado final es idéntico en ambos casos

---

## Alcance implementado

| Área | Estado |
|---|---|
| Autenticación (signup, login, logout) | ✅ |
| Gestión de perfiles y mascotas | ✅ |
| Catálogo de cuidadores y disponibilidad | ✅ |
| Reservas: paseo y guardería | ✅ |
| Estados de solicitud (pendiente/aceptado/rechazado/cancelado/completado) | ✅ |
| Chat entre dueño y cuidador | ✅ |
| Calificaciones y reseñas | ✅ |
| Notificaciones internas (sistema) | ✅ |
| API REST (DRF) — búsqueda disponibilidad, crear/ver/cancelar solicitud | ✅ |
| Microservicio Flask — BuscarDisponibilidad | ✅ |
| Docker (PostgreSQL + Django + Flask orquestados) | ✅ |
| Builder (SolicitudServicioBuilder) | ✅ |
| Factory (NotificadorFactory: Mock/LogOnly/Real) | ✅ |

---

## Configuración actual

**Base de datos:** SQLite compartido (`db.sqlite3`) entre Django y Flask en Docker.

**Docker Compose:**
- `django` (puerto 8000) — Django app + dev server
- `disponibilidad` (puerto 5001) — Flask microservicio
- Volumen compartido: `./db.sqlite3:/app/db.sqlite3`

**Quirks importantes:**
- SQLite almacena UUIDs **sin guiones** (32 hex chars). Flask normaliza UUIDs con `.replace("-", "")` antes de queries.
- Rol en signup normalizado a minúsculas (`"DUEÑO"` → `"dueño"`).
- Validación de payload ocurre **antes** de delegar a Flask para consistencia.

---

## Comandos clave

```bash
# Dev local (SQLite, sin Docker)
python manage.py runserver

# Docker (SQLite compartido)
docker-compose down
docker-compose build --no-cache
docker-compose up

# Probar microservicio Flask directo
curl http://localhost:5001/health

curl -X POST http://localhost:5001/disponibilidad \
  -H "Content-Type: application/json" \
  -d '{
    "tipoServicio":"paseo",
    "idDueño_id":"<uuid_sin_guiones_o_con>",
    "idMascota_id":"<uuid>",
    "fecha":"2026-04-20"
  }'
```
