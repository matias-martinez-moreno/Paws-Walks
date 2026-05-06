# Diagramas C4 - Arquitectura Paws & Walks

## 1. DIAGRAMA DE CONTEXTO (C1)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           SISTEMAS EXTERNOS                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌──────────────┐        ┌──────────────┐        ┌──────────────┐    │
│   │ OpenWeather  │        │  Equipo      │        │  Usuarios    │    │
│   │    API       │        │   Aliado     │        │  (Web/App)   │    │
│   │ (clima)      │        │    (API)     │        │              │    │
│   └──────┬───────┘        └──────┬───────┘        └──────┬───────┘    │
│          │                       │                      │              │
│          │ GET /weather          │ GET /datos           │ HTTP/HTTPS   │
│          │                       │                      │              │
│          └───────────────────────┼──────────────────────┘              │
│                                  │                                      │
│                    ┌─────────────▼─────────────┐                        │
│                    │   PAWS & WALKS PLATFORM   │                        │
│                    │    (Paws & Walks SaaS)    │                        │
│                    │                           │                        │
│                    │  • Django 5.0             │                        │
│                    │  • Microservicios Flask   │                        │
│                    │  • Redis + Celery         │                        │
│                    │  • PostgreSQL             │                        │
│                    │                           │                        │
│                    └─────────────────────────────┘                        │
│                                  ▲                                       │
│                                  │                                       │
│                    ┌─────────────▼─────────────┐                        │
│                    │   Equipo Externo (Aliado) │                        │
│                    │  (Consumidor de API)      │                        │
│                    └───────────────────────────┘                        │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. DIAGRAMA DE CONTENEDOR (C2)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              PAWS & WALKS DEPLOYMENT                             │
│                                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  NGINX Gateway (Reverse Proxy)                                          │    │
│  │  • Enruta /api/nuestro/* → Django                                       │    │
│  │  • Enruta /microservicios/* → Flask services                            │    │
│  │  • Load balancing (ready para producción)                               │    │
│  └─────┬───────────────┬──────────────┬──────────────────────────────────┘    │
│        │               │              │                                         │
│        ▼               ▼              ▼                                         │
│  ┌──────────┐  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐             │
│  │  Django  │  │  Flask      │ │   Flask      │ │   Redis      │             │
│  │  :8000   │  │  Disponibl. │ │   Ratings    │ │   :6379      │             │
│  │          │  │  :5001      │ │   :5000      │ │              │             │
│  │ • DRF    │  │             │ │              │ │ • Broker     │             │
│  │ • Celery │  │ • SQLAlch   │ │ • SQLAlch    │ │   para tasks │             │
│  │   Worker │  │ • Query     │ │ • Dict cache │ │              │             │
│  │ • Views  │  │ • Search    │ │ • Ratings    │ │              │             │
│  │ • Models │  │              │ │  (CRUD)      │ │              │             │
│  └────┬─────┘  └─────────────┘ └──────────────┘ └──────────────┘             │
│       │                                                                         │
│       └─────────────────┬────────────────────────────────────────┐             │
│                         ▼                                        │             │
│                  ┌──────────────────┐                            │             │
│                  │   PostgreSQL     │                            │             │
│                  │   :5432          │                            │             │
│                  │                  │                            │             │
│                  │ • Usuarios       │◄───────────────────────────┘             │
│                  │ • Mascotas       │                                         │
│                  │ • Solicitudes    │                                         │
│                  │ • Reseñas        │                                         │
│                  │ • Notificaciones │                                         │
│                  │ • Chat           │                                         │
│                  └──────────────────┘                                          │
│                                                                                 │
│  Orquestación: Docker Compose (5 servicios + volúmenes)                      │
│  Comunicación: HTTP/REST, Redis Queue para async tasks                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. DIAGRAMA DE COMPONENTES (C3) - Django Service Layer

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PAWS & WALKS - SERVICE LAYER ARCHITECTURE                │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  API Views (Presentación) - DRF APIView                              │  │
│  │  • SolicitudServicioCreateAPIView                                    │  │
│  │  • DisponibilidadCuidadoresAPIView                                   │  │
│  │  • SistemaEstadoAPIView (PÚBLICO)                                    │  │
│  │  • CuidadoresListadoAPIView (PÚBLICO)                                │  │
│  └────────────────────────────┬─────────────────────────────────────────┘  │
│                               │                                             │
│                               ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  API Gateway Service                                                 │  │
│  │  (Single Entry Point - Orquestación)                                 │  │
│  │  • buscar_disponibilidad()                                           │  │
│  │  • crear_solicitud()                                                 │  │
│  │  • obtener_clima_ciudad()  ← Adapter Pattern                         │  │
│  └────────────────────────────┬─────────────────────────────────────────┘  │
│                               │                                             │
│         ┌─────────────────────┼─────────────────────┐                       │
│         ▼                     ▼                     ▼                       │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────┐           │
│  │ Disponibilidad │  │ Reservas         │  │ Usuarios        │           │
│  │ Service        │  │ Service          │  │ Service         │           │
│  └────────────────┘  └──────────────────┘  └─────────────────┘           │
│         │                    │                     │                       │
│         │    ┌───────────────┼─────────────────┐   │                       │
│         │    ▼               ▼                 ▼   ▼                       │
│         │  ┌────────────────────────────────────────────┐                 │
│         │  │ Domain Layer (Excepciones, Builder)        │                 │
│         │  │ • DomainValidationError                    │                 │
│         │  │ • SolicitudServicioBuilder                 │                 │
│         └──┤ • ResourceNotFoundError                    │                 │
│            └────────────────────────────────────────────┘                 │
│                             │                                             │
│         ┌───────────────────┼────────────────────┐                         │
│         ▼                   ▼                    ▼                         │
│  ┌─────────────────┐ ┌──────────────┐  ┌──────────────────┐            │
│  │ Infra Layer     │ │ Adapter:     │  │ Notificador      │            │
│  │ (ORM, BD)       │ │ Clima        │  │ Factory          │            │
│  │                 │ │ (OpenWeather)│  │ • Mock           │            │
│  │ • Models.py     │ │ • Real       │  │ • LogOnly        │            │
│  │ • ORM queries   │ │ • Mock       │  │ • Real (email)   │            │
│  └─────────────────┘ └──────────────┘  └──────────────────┘            │
│         │                                        │                        │
│         └────────────────┬───────────────────────┘                        │
│                          ▼                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  PostgreSQL Database                                                 │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  Celery Task Queue (Redis Backend)                                   │ │
│  │  • task_nueva_solicitud()                                            │ │
│  │  • task_solicitud_aceptada()                                         │ │
│  │  • task_servicio_completado()                                        │ │
│  │  • task_mensaje_chat()                                               │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└──────────────────────────────────────────────────────────────────────────────┘
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

## 5. DEPLOYMENT DIAGRAM (Infraestructura AWS - Futuro)

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
- **Strangler Pattern**: Flask microservicios extraen funcionalidades del monolito
- **API Gateway**: Nginx centraliza el ruteo (único punto de entrada)
- **Adapter Pattern**: Consumo de APIs externas (OpenWeather) via adapters
- **Factory Pattern**: Notificadores intercambiables (Mock/LogOnly/Real)
- **Builder Pattern**: Construcción fluida de entidades complejas
- **Message Queue**: Redis/Celery para operaciones async (notificaciones, reportes)
- **Layered Architecture**: Presentación → Service → Domain → Infrastructure

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
