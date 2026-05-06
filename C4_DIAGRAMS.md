# Diagramas C4 - Arquitectura Paws & Walks (Entrega 2)

## 1. DIAGRAMA DE CONTEXTO (C1)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SISTEMAS EXTERNOS                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────┐ │
│   │ OpenWeather  │    │   Equipo     │    │  Dueños y    │    │  Equipo │ │
│   │    API       │    │   Aliado     │    │  Cuidadores  │    │ Externo │ │
│   │  (Clima)     │    │  (REST API)  │    │  (Web/App)   │    │ Aliado  │ │
│   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └────┬────┘ │
│          │                   │                   │                  │      │
│   GET /weather   ◄── consume ──┐    HTTP/HTTPS   │       consume   │      │
│   (vía Adapter)              │ │                 │      /api/v1/   │      │
│                              │ │                 │      sistema/   │      │
│          │   AliadoPort      │ │                 │      estado/    │      │
│          │   (Adapter)       │ │                 │                  │      │
│          └──────────────────┐│ │                 │                  │      │
│                             ▼▼ ▼                 ▼                  │      │
│                    ┌─────────────────────────────────────┐          │      │
│                    │      PAWS & WALKS PLATFORM          │          │      │
│                    │       (SaaS — AWS EC2)              │          │      │
│                    │                                     │          │      │
│                    │  • Django 5  • Flask Disponibilidad │          │      │
│                    │  • DRF       • Flask Ratings        │          │      │
│                    │  • Celery    • Redis (Broker)       │          │      │
│                    │  • PostgreSQL                        │          │      │
│                    │  • Nginx (API Gateway)              │          │      │
│                    └─────────────┬───────────────────────┘          │      │
│                                  │                                   │      │
│                                  └─── /api/v1/sistema/estado/ ──────┘      │
│                                       /api/v1/cuidadores/listado/           │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

Flujos clave:
  • Usuarios → Nginx → Django/Flask
  • Django → OpenWeather (vía OpenWeatherAdapter implementa ClimaPort)
  • Django → Equipo Aliado (vía AliadoHttpAdapter implementa AliadoPort)
  • Equipo Externo → Django /api/v1/sistema/estado/ (endpoint expuesto JSON)
```

---

## 2. DIAGRAMA DE CONTENEDOR (C2)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                          PAWS & WALKS — DESPLIEGUE AWS EC2                           │
│                                                                                       │
│   Internet ──► Elastic IP ──► Security Group (80/443/22)                             │
│                                          │                                            │
│                                          ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────────────┐    │
│  │  NGINX :80  (API Gateway / Reverse Proxy)                                   │    │
│  │  ─────────────────────────────────────────────                              │    │
│  │  • / → django_web:8000                                                      │    │
│  │  • /api/v2/calificaciones → flask_ratings:5000                              │    │
│  │  • /microservicios/disponibilidad → flask_disponibilidad:5001               │    │
│  └────┬───────────────────┬─────────────────────┬─────────────────────────────┘    │
│       │                   │                     │                                    │
│       ▼                   ▼                     ▼                                    │
│  ┌──────────┐    ┌─────────────────┐   ┌────────────────┐   ┌────────────────┐    │
│  │  Django  │    │ Flask           │   │  Flask         │   │  Redis :6379   │    │
│  │  :8000   │    │ Disponibilidad  │   │  Ratings       │   │  ────────────  │    │
│  │  ──────  │    │ :5001           │   │  :5000         │   │  • Broker      │    │
│  │  DRF     │    │ ──────────────  │   │  ────────────  │   │    Celery      │    │
│  │  i18n    │    │ • SQLAlchemy    │   │  • CRUD        │   │  • Result      │    │
│  │  Adapter │    │ • Query motor   │   │    ratings     │   │    backend     │    │
│  │  (clima, │    │ • Strangler:    │   │                │   └────────────────┘    │
│  │  aliado) │    │   búsqueda de   │   │                │                          │
│  │          │    │   cuidadores    │   │                │   ┌────────────────┐    │
│  │  Views   │    │                 │   │                │   │  Celery Worker │    │
│  │  Models  │    │                 │   │                │   │  ────────────  │    │
│  │          │    │                 │   │                │   │  Tareas async: │    │
│  │  Calls:  │    │                 │   │                │   │  • notif       │    │
│  │  Adapter │    │                 │   │                │   │  • emails      │    │
│  │  →OpenW. │    │                 │   │                │   │  • reportes    │    │
│  │  →Aliado │    │                 │   │                │   └────────────────┘    │
│  └────┬─────┘    └────────┬────────┘   └────────┬───────┘                          │
│       │                   │                     │                                    │
│       │  POST /disponibilidad                   │                                    │
│       ├──────────────────►│                     │                                    │
│       │                   │                     │                                    │
│       │  HTTP REST                              │                                    │
│       └───────────────────┼─────────────────────┘                                    │
│                           ▼                                                          │
│                  ┌─────────────────────┐                                            │
│                  │  PostgreSQL :5432    │                                            │
│                  │  ──────────────────  │                                            │
│                  │  Volumen: pgdata     │                                            │
│                  │                      │                                            │
│                  │  Tablas:             │                                            │
│                  │  • Usuarios          │                                            │
│                  │  • Mascotas          │                                            │
│                  │  • SolicitudServicio │                                            │
│                  │  • Calificacion      │                                            │
│                  │  • Notificacion      │                                            │
│                  │  • PerfilCuidador    │                                            │
│                  │  • Evento, Slot...   │                                            │
│                  └──────────────────────┘                                            │
│                                                                                       │
│  Orquestación: Docker Compose (7 contenedores + 1 volumen)                          │
│  Servicios:                                                                          │
│    db, redis, django_web, celery_worker, disponibilidad, flask_ratings, nginx        │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. DIAGRAMA DE COMPONENTES (C3) - Django Service Layer

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                    PAWS & WALKS - SERVICE LAYER ARCHITECTURE                     │
│                                                                                   │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  API Views (DRF APIView) + Web Views (View)                                │ │
│  │  ─────────────────────────────────────────────                             │ │
│  │  Web (sesión):                                                             │ │
│  │  • DashboardDueñoView, DashboardCuidadorView                               │ │
│  │  • DueñoNuevaReservaView, AliadoEstadoView ◄── NUEVO consume aliado       │ │
│  │                                                                            │ │
│  │  API REST v1 (token):                                                      │ │
│  │  • SolicitudServicioCreateAPIView, DisponibilidadCuidadoresAPIView         │ │
│  │  • ClimaAPIView, AliadoAPIView ◄── NUEVO endpoint consumo aliado          │ │
│  │                                                                            │ │
│  │  API REST v1 PÚBLICOS (consumo externo):                                   │ │
│  │  • SistemaEstadoAPIView    /api/v1/sistema/estado/                         │ │
│  │  • CuidadoresListadoAPIView /api/v1/cuidadores/listado/                    │ │
│  └──────────────────────────────────┬─────────────────────────────────────────┘ │
│                                     │                                            │
│                                     ▼                                            │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  ServiciosApiGatewayService (Single Entry Point)                           │ │
│  │  ─────────────────────────────────────────────                             │ │
│  │  • buscar_disponibilidad() ── HTTP ──► Flask :5001 (con fallback interno)  │ │
│  │  • crear_solicitud(), obtener_solicitud(), cancelar_solicitud()            │ │
│  │  • obtener_clima_ciudad()  ◄── ClimaPort (Adapter Pattern)                 │ │
│  │  • obtener_estado_aliado() ◄── AliadoPort (Adapter Pattern) ◄── NUEVO     │ │
│  └─────┬───────────────────────┬───────────────────────────────────┬──────────┘ │
│        │                       │                                   │            │
│        ▼                       ▼                                   ▼            │
│  ┌──────────────┐     ┌──────────────────┐              ┌────────────────────┐ │
│  │ Service      │     │ Domain Layer     │              │ Infra/Adapters     │ │
│  │ Layer        │     │ ─────────────    │              │ ────────────────   │ │
│  │ ────────     │     │ • Builder        │              │ ports.py:          │ │
│  │ • disponibi. │     │ • Excepciones    │              │   ClimaPort (ABC)  │ │
│  │ • reservas   │     │ • SolicitudBldr  │              │   AliadoPort (ABC) │ │
│  │ • clima      │     │                  │              │                    │ │
│  │ • aliado ◄NEW│     │                  │              │ implementaciones:  │ │
│  │ • api_validad│     │                  │              │  • OpenWeatherAdpt │ │
│  │              │     │                  │              │  • AliadoHttpAdpt  │ │
│  │              │     │                  │              │  • AliadoMockAdpt  │ │
│  │              │     │                  │              │                    │ │
│  │              │     │                  │              │ factory.py:        │ │
│  │              │     │                  │              │  • Notificador F.  │ │
│  │              │     │                  │              │  • ClimaAdapter F. │ │
│  │              │     │                  │              │  • AliadoAdapter F.│ │
│  └──────┬───────┘     └────────┬─────────┘              └─────────┬──────────┘ │
│         │                      │                                   │            │
│         └──────────┬───────────┴───────────────────────────────────┘            │
│                    ▼                                                             │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  PostgreSQL Database (vía Django ORM)                                      │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                   │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  Celery Tasks (Redis Broker) — Comunicación Asíncrona                      │ │
│  │  ──────────────────────────────────────────────────                        │ │
│  │  • task_nueva_solicitud         (notifica al cuidador)                     │ │
│  │  • task_solicitud_aceptada      (notifica al dueño)                        │ │
│  │  • task_solicitud_rechazada     (notifica al dueño)                        │ │
│  │  • task_servicio_completado     (notifica + dispara reseña)                │ │
│  │  • task_reserva_cancelada       (notifica a la contraparte)                │ │
│  │  • task_mensaje_chat            (notifica chat asíncrono)                  │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. DIAGRAMA DE COMUNICACIÓN (C4) - Microservicios

```
┌──────────────────────────────────────────────────────────────────────────┐
│                   COMUNICACIÓN ENTRE MICROSERVICIOS                       │
│                                                                           │
│   NGINX Gateway                                                          │
│   (:80)                                                                  │
│    ▲                                                                    │
│    │                                                                    │
│    ├─────────────┬──────────────────┬──────────────────────┐          │
│    │             │                  │                     │          │
│    ▼             ▼                  ▼                     ▼          │
│  Django       Flask                Flask              Redis          │
│  (:8000)      Disponibilidad      Ratings             (:6379)       │
│               (:5001)             (:5000)                            │
│    │             ▲                  │                                │
│    │             │                  │                                │
│    ├─────────────┘                  │                                │
│    │  POST /disponibilidad          │                                │
│    │  (Búsqueda cuidadores)         │                                │
│    │                                │                                │
│    ├────────────────────────────────┘                                │
│    │  POST /api/v2/calificaciones                                   │
│    │  GET  /api/v2/calificaciones/<user_id>                         │
│    │  (Ratings CRUD)                │                                │
│    │                                │                                │
│    └────────────────────────────────────────────────────────────────┤
│       Celery Worker                                                   │
│       Consume tasks desde Redis                                       │
│       (Async notifications)                                           │
│                                                                        │
│   Patrones:                                                           │
│   • Strangler: Flask extrae funcionalidades                          │
│   • API Gateway: Nginx como punto de entrada único                   │
│   • Message Queue: Redis/Celery para async tasks                     │
│   • Fallback: Django usa servicio interno si Flask no responde       │
│                                                                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. DEPLOYMENT DIAGRAM (Infraestructura AWS Academy)

```
┌──────────────────────────────────────────────────────────────┐
│              AWS Academy (EC2 Instance)                       │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Docker Compose (Orquestación)                         │ │
│  │                                                        │ │
│  │  Containers:                                          │ │
│  │  • paws-walks-django:latest                           │ │
│  │  • paws-walks-disponibilidad:latest                   │ │
│  │  • paws-walks-ratings:latest                          │ │
│  │  • postgres:15                                        │ │
│  │  • redis:7-alpine                                     │ │
│  │  • nginx:latest                                       │ │
│  │                                                        │ │
│  │  Volumes:                                             │ │
│  │  • pgdata (PostgreSQL data)                           │ │
│  │  • ./db.sqlite3 (shared entre servicios)              │ │
│  │                                                        │ │
│  └────────────────────────────────────────────────────────┘ │
│           ▲                                                  │
│           │ HTTP/HTTPS                                      │
│           │                                                  │
│  ┌────────┴────────────────────────────────────────┐       │
│  │  Security Group (Firewall)                       │       │
│  │  • Allow 80 (HTTP)                               │       │
│  │  • Allow 443 (HTTPS - futuro)                    │       │
│  │  • Allow 22 (SSH - admin)                        │       │
│  └────────────────────────────────────────────────┘       │
│           ▲                                                  │
│           │                                                  │
│    Elastic IP (Fixed Public IP)                             │
│           │                                                  │
└───────────┼──────────────────────────────────────────────────┘
            │
         Internet
```

---

## Notas Arquitecturales

### Principios Aplicados:
- **Strangler Pattern**: 2 microservicios Flask extraen funcionalidades del monolito
  - `flask_disponibilidad` (matching) y `flask_ratings` (calificaciones)
- **API Gateway**: Nginx centraliza el ruteo (único punto de entrada público)
- **Adapter Pattern + DIP**: Consumo de APIs externas vía interfaces
  - `ClimaPort` → `OpenWeatherAdapter` (terceros) / `ClimaAdapterMock`
  - `AliadoPort` → `AliadoHttpAdapter` (equipo aliado) / `AliadoMockAdapter`
- **Factory Pattern**: Selección de implementación según entorno
  - `NotificadorFactory` (Mock/LogOnly/Real/Async)
  - `ClimaAdapterFactory` (Real/Mock según `OPENWEATHER_API_KEY`)
  - `AliadoAdapterFactory` (Real/Mock según `ALIADO_API_URL`)
- **Builder Pattern**: `SolicitudServicioBuilder` para entidades complejas
- **Message Queue**: Redis/Celery — 6 tareas async (notif, chat, eventos)
- **Layered Architecture**: Presentación → Service Layer → Domain → Infrastructure
- **i18n (gettext)**: extracción `makemessages`, compilación `compilemessages`,
  archivos `.po`/`.mo` para `es` y `en`. Cero textos quemados.

### Escalabilidad:
- Django: horizontalmente escalable (stateless)
- Flask servicios: independientes, escalables por separado
- Redis: bottleneck potencial (cache/queue) → considerar cluster para producción
- PostgreSQL: necesita réplica+failover para HA

### Seguridad:
- Nginx como WAF proxy
- CSRF protection en Django
- Token auth en API (futuro)
- Secrets via variables de entorno (no en código)
