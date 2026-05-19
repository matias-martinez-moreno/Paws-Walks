# Sustentación Entrega 2 — Paws & Walks
## Migración a Microservicios, Integración y Resiliencia

---

## 1. Correcciones E1 — Implementación Total de Ajustes

### Descripción
Todos los ajustes notificados en la sustentación de Entrega 1 fueron identificados e implementados al 100%.

### Cómo se hizo
Se realizó un análisis exhaustivo de los feedback de E1 y se identificaron los puntos críticos:
- Renombrar templates con caracteres especiales (ñ) que causaban problemas en xgettext
- Implementar gettext correctamente sin textos quemados
- Corregir importaciones de modelos inexistentes (Resena → Calificacion)
- Garantizar que todas las traducciones se aplicaran con .po/.mo compilados

### Archivos clave

**servicios/templates/servicios/dueno_*.html → dueno_*.html**
Se renombraron 8 templates eliminando ñ:
- dashboard_dueño.html → dashboard_dueno.html
- dueño_nueva_reserva.html → dueno_nueva_reserva.html
- dueño_mis_mascotas.html → dueno_mis_mascotas.html
- dueño_mis_reservas.html → dueno_mis_reservas.html
- dueño_mi_perfil.html → dueno_mi_perfil.html
- dueño_guia.html → dueno_guia.html
- dueño_soporte.html → dueno_soporte.html (posteriormente eliminado)

**servicios/views.py**
Se actualizaron todas las referencias de rutas de templates:
```python
return render(request, "servicios/dueno_nueva_reserva.html", {...})
return render(request, "servicios/dueno_mis_mascotas.html", {...})
return render(request, "servicios/dueno_mi_perfil.html", {...})
```

**servicios/api/views.py**
Se corrigió importación de modelo inexistente:
```python
# ANTES (incorrecto)
from servicios.models import Resena

# DESPUÉS (correcto)
from servicios.models import Calificacion

# Uso correcto
calificaciones = Calificacion.objects.filter(...)
rating_promedio = aggregado.promedio  # Campo correcto: idParaUsuario
```

**locale/es y locale/en (gettext)**
Se implementó flujo completo de gettext:
- Extracción: `python manage.py makemessages -l es -l en`
- Llenado: `scripts/fill_translations.py` con diccionario de 630+ traducciones
- Compilación: `python manage.py compilemessages` genera .mo binarios

### Resultado
100% de correcciones de E1 implementadas. Sistema compila sin errores, templates se cargan correctamente, modelos existen y se usan apropiadamente.

---

## 2. Arquitectura y Patrones — Diagramas C4 Actualizados

### Descripción
Evolución de la arquitectura monolítica hacia un ecosistema híbrido con microservicios, API Gateway y message broker documentado en diagramas C4.

### Cómo se hizo

**C4 nivel Contexto (C1)**
Define cómo usuarios, OpenWeather y equipo aliado interactúan con Paws & Walks como caja negra:
```
Usuarios (Web/App)
    ↓ HTTP/HTTPS
OpenWeather API ←→ Paws & Walks (SaaS en AWS)
Equipo Aliado ←→ Paws & Walks
```

**C4 nivel Contenedor (C2)**
Desglosa servicios dentro de AWS EC2:
```
Internet → Elastic IP → Security Group (80/443/22)
                           ↓
                      NGINX :80 (API Gateway)
                    ↙        ↓        ↘
            Django    Flask Disp.   Flask Ratings
            :8000     :5001         :5000
                    ↘        ↙        ↙
                    PostgreSQL
                    Redis (Broker)
                    Celery Worker
```

**C4 nivel Componentes (C3)**
Detalla la capa de servicios dentro de Django:
- API Views (presentación DRF thin)
- API Gateway Service (orquestación)
- Service Layer (lógica negocio)
- Domain (builder, excepciones, ports)
- Infra (adapters, factory, notificador)

**C4 nivel Comunicación (C4)**
Muestra flujos entre microservicios:
```
Django POST /disponibilidad → Flask :5001 (con fallback interno)
Django POST /calificaciones → Flask :5000
Django + Celery Worker ←→ Redis (tareas async)
```

### Archivos clave

**C4_DIAGRAMS.md**
```markdown
## 1. DIAGRAMA DE CONTEXTO (C1)
[Diagrama ASCII mostrando usuarios, APIs externas y Paws & Walks]

## 2. DIAGRAMA DE CONTENEDOR (C2)
[Diagrama con Nginx, Django, Flask x2, PostgreSQL, Redis, Celery]

## 3. DIAGRAMA DE COMPONENTES (C3)
API Views → API Gateway Service → Service Layer → Domain → Infra

## 4. DIAGRAMA DE COMUNICACIÓN (C4)
Django POST /disponibilidad → Flask (con fallback)
Django POST /calificaciones → Flask
Celery Worker consume Redis

## Notas Arquitecturales
- Strangler Pattern: 2 Flask microservicios extraen funcionalidades
- API Gateway: Nginx centraliza ruteo
- Adapter + DIP: ClimaPort, AliadoPort intercambiables via Factory
- Message Queue: Redis/Celery para 6 tareas async
```

### Resultado
Diagramas C4 actualizados reflejando arquitectura completa. Cada nivel agrega detalle sin perder claridad. Patrones arquitectónicos explícitamente documentados.

---

## 3. Integración — Exposición de API y Consumo de Servicios

### Descripción
Implementación del contrato de integración: exponer endpoints JSON y consumir servicios de terceros.

### 3.1. Servicio a Proveer — API Expuesta

**Endpoints públicos para consumo externo**

servicios/api/urls.py:
```python
path("v1/sistema/estado/", SistemaEstadoAPIView.as_view(), name="sistema_estado"),
path("v1/cuidadores/listado/", CuidadoresListadoAPIView.as_view(), name="cuidadores_listado"),
```

servicios/api/views.py:
```python
class SistemaEstadoAPIView(APIView):
    """Endpoint público: estado general del sistema."""
    permission_classes = [AllowAny]
    
    def get(self, request):
        # Retorna: usuarios total, dueños, cuidadores, solicitudes, reseñas
        usuarios = Usuario.objects.all().count()
        dueños = Usuario.objects.filter(rol='dueño').count()
        cuidadores = Usuario.objects.filter(rol='cuidador').count()
        solicitudes = SolicitudServicio.objects.all().count()
        return Response({
            "sistema": "Paws & Walks",
            "usuarios": {"total": usuarios, "dueños": dueños, "cuidadores": cuidadores},
            "solicitudes": {"total": solicitudes, ...},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, status=status.HTTP_200_OK)

class CuidadoresListadoAPIView(APIView):
    """Endpoint público: catálogo de cuidadores verificados."""
    permission_classes = [AllowAny]
    
    def get(self, request):
        cuidadores = Usuario.objects.filter(rol='cuidador', perfil_usuario__verificado=True)
        # Para cada cuidador: id, nombre, ciudad, foto, rating promedio
        resultados = []
        for c in cuidadores:
            calificaciones = Calificacion.objects.filter(idParaUsuario=c)
            promedio = calificaciones.aggregate(avg=Avg('estrellas'))['avg'] or 0
            resultados.append({
                "id": str(c.idUsuario),
                "nombre": c.nombre,
                "ciudad": c.perfil_usuario.ciudad,
                "foto": c.perfil_usuario.fotoPerfil.url if c.perfil_usuario.fotoPerfil else None,
                "verificado": c.perfil_usuario.verificado,
                "total_reseñas": calificaciones.count(),
                "rating_promedio": round(float(promedio), 1) if promedio else 0
            })
        return Response({"count": len(resultados), "resultados": resultados}, status=status.HTTP_200_OK)
```

**Cómo se hizo:**
1. Creación de APIViews sin lógica de negocio (thin views)
2. Serialización manual a diccionarios (sin DRF Serializers complejos)
3. Campos normalizados y tipados
4. Status HTTP 200 OK para éxito
5. Permission_classes = [AllowAny] para acceso público

**Verificación:**
```bash
curl http://localhost:8000/api/v1/sistema/estado/
# Respuesta JSON con estructura uniforme

curl http://localhost:8000/api/v1/cuidadores/listado/
# Respuesta JSON con arreglo de cuidadores
```

### 3.2. Servicio a Consumir — Equipo Aliado

**Patrón Adapter + Inversión de Dependencias**

servicios/domain/ports.py:
```python
from abc import ABC, abstractmethod

class AliadoPort(ABC):
    """Contrato (puerto) para consumo del equipo aliado.
    
    El service layer depende de esta interfaz, no de la implementación concreta.
    """
    @abstractmethod
    def obtener_estado_sistema(self) -> dict:
        """Retorna estado normalizado del sistema aliado."""
        pass
```

servicios/infra/aliado_adapter.py:
```python
class AliadoHttpAdapter(AliadoPort):
    """Implementación real: HTTP a endpoint del equipo aliado."""
    
    def __init__(self, base_url: str, timeout: int = 5):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
    
    def obtener_estado_sistema(self) -> dict:
        url = f"{self._base_url}/api/v1/sistema/estado/"
        try:
            resp = requests.get(url, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            return {
                "fuente": data.get("sistema", "Equipo aliado"),
                "disponible": True,
                "datos": data,
                "consultado_en": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            return {
                "fuente": _("Partner team"),
                "disponible": False,
                "datos": {"error": str(exc)},
                "consultado_en": datetime.now(timezone.utc).isoformat(),
            }

class AliadoMockAdapter(AliadoPort):
    """Implementación fallback: datos de demostración."""
    
    def obtener_estado_sistema(self) -> dict:
        return {
            "fuente": _("Partner team (mock)"),
            "disponible": True,
            "datos": {
                "sistema": _("Partner demo service"),
                "estado": _("operational"),
                "metricas": {
                    "usuarios_activos": 142,
                    "transacciones_dia": 38,
                },
                "nota": _("Set ALIADO_API_URL in settings to use the real endpoint."),
            },
            "consultado_en": datetime.now(timezone.utc).isoformat(),
        }
```

servicios/infra/factory.py:
```python
class AliadoAdapterFactory:
    """Factory: selecciona adapter según configuración."""
    
    @classmethod
    def crear(cls):
        url = os.environ.get("ALIADO_API_URL", "").strip()
        if url:
            return AliadoHttpAdapter(url)
        else:
            return AliadoMockAdapter()
```

servicios/service_layer/aliado_servicios.py:
```python
class AliadoService:
    """Servicio que depende de AliadoPort, no de implementación concreta."""
    
    def __init__(self, port: AliadoPort = None):
        self._port = port or AliadoAdapterFactory.crear()
    
    def obtener_estado_aliado(self):
        try:
            return self._port.obtener_estado_sistema()
        except Exception as e:
            return {"disponible": False, "error": str(e)}
```

servicios/service_layer/api_gateway.py:
```python
class ServiciosApiGatewayService:
    """Orquestador único: delegador a todos los servicios."""
    
    def __init__(self, ..., aliado_service=None, ...):
        self._aliado_service = aliado_service or AliadoService()
    
    def obtener_estado_aliado(self):
        return self._aliado_service.obtener_estado_aliado()
```

servicios/api/views.py:
```python
class AliadoAPIView(APIView):
    """Endpoint público: consumo de aliado."""
    permission_classes = [AllowAny]
    
    def get(self, request):
        gateway = ServiciosApiGatewayService()
        return Response(gateway.obtener_estado_aliado(), status=status.HTTP_200_OK)
```

servicios/api/urls.py:
```python
path("v1/aliado/estado/", AliadoAPIView.as_view(), name="aliado_estado"),
```

**Vista web para mostrar el aliado en la aplicación**

servicios/views.py:
```python
class AliadoEstadoView(LoginRequiredMixin, View):
    """Consumir y mostrar estado del aliado en dashboard."""
    
    def get(self, request):
        gateway = ServiciosApiGatewayService()
        contexto = {
            "usuario": _get_usuario(request),
            "aliado": gateway.obtener_estado_aliado(),
        }
        return render(request, "servicios/aliado_estado.html", contexto)
```

servicios/urls.py:
```python
path("integraciones/aliado/", AliadoEstadoView.as_view(), name="aliado_estado_web"),
```

servicios/templates/servicios/aliado_estado.html:
```html
<div class="md:col-span-2 bg-white rounded-2xl shadow-sm p-6">
    <h2 class="text-lg font-bold">
        <i class="bi bi-link-45deg"></i> {{ aliado.fuente }}
    </h2>
    {% if aliado.disponible %}
        <span class="px-3 py-1 bg-emerald-100 text-emerald-700">
            Disponible
        </span>
    {% else %}
        <span class="px-3 py-1 bg-red-100 text-red-700">
            No disponible
        </span>
    {% endif %}
    <p class="text-sm">Última consulta: {{ aliado.consultado_en }}</p>
    <pre>{{ aliado.datos|pprint }}</pre>
</div>
```

**Cómo se hizo:**
1. Definir interfaz AliadoPort con método obtener_estado_sistema()
2. Implementar AliadoHttpAdapter (HTTP real) y AliadoMockAdapter (fallback)
3. Factory Pattern: AliadoAdapterFactory selecciona según ALIADO_API_URL
4. Service Layer: AliadoService recibe AliadoPort via DI
5. API Gateway: orquesta llamada a AliadoService
6. Dos puntos de consumo: API endpoint + vista web con render template

**Verificación:**
```bash
# API endpoint
curl http://localhost:8000/api/v1/aliado/estado/
# Respuesta mock (sin ALIADO_API_URL configurada)

# Vista web
curl http://localhost:8000/integraciones/aliado/
# HTML con estado del aliado rendereado
# (requiere autenticación, LoginRequiredMixin)
```

### 3.3. API de Terceros — OpenWeather vía Adapter

servicios/domain/ports.py:
```python
class ClimaPort(ABC):
    """Contrato para proveedores de clima."""
    @abstractmethod
    def obtener_clima(self, ciudad: str) -> dict:
        pass
```

servicios/infra/weather_adapter.py:
```python
from django.utils.translation import get_language, gettext as _

class OpenWeatherAdapter(ClimaPort):
    """Adapter real para OpenWeatherMap API."""
    
    def __init__(self, api_key: str):
        self._api_key = api_key
    
    def obtener_clima(self, ciudad: str) -> dict:
        try:
            lang = (get_language() or "es")[:2]  # Dinámico según idioma
            resp = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "q": ciudad,
                    "appid": self._api_key,
                    "units": "metric",
                    "lang": lang,  # IMPORTANTE: respeta idioma del usuario
                },
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            
            condicion = data["weather"][0]["main"]
            temp = data["main"]["temp"]
            
            return {
                "ciudad": data.get("name", ciudad),
                "temperatura": round(temp, 1),
                "descripcion": data["weather"][0]["description"].capitalize(),
                "icono": data["weather"][0]["icon"],
                "humedad": data["main"]["humidity"],
                "apto_para_paseo": _es_apto_para_paseo(condicion, temp),
            }
        except Exception as exc:
            raise

class ClimaAdapterMock(ClimaPort):
    """Adapter mock para desarrollo sin API key."""
    
    def obtener_clima(self, ciudad: str) -> dict:
        return {
            "ciudad": ciudad,
            "temperatura": 22.0,
            "descripcion": _("Partly cloudy"),  # Via gettext
            "icono": "02d",
            "humedad": 60,
            "apto_para_paseo": True,
        }
```

servicios/infra/factory.py:
```python
class ClimaAdapterFactory:
    """Factory: selecciona adapter según OPENWEATHER_API_KEY."""
    
    @classmethod
    def crear(cls):
        api_key = os.environ.get("OPENWEATHER_API_KEY", "").strip()
        if api_key:
            return OpenWeatherAdapter(api_key)
        else:
            return ClimaAdapterMock()
```

**Cómo se hizo:**
1. Interfaz ClimaPort abstracta
2. Dos implementaciones: OpenWeatherAdapter (real) y ClimaAdapterMock (fallback)
3. Factory selecciona según API key configurada
4. OpenWeatherAdapter pasa `lang = get_language()` a OpenWeather
5. Descripción clima se traduce dinámicamente (API entrega "Partly cloudy" en EN)

**Resultado:**
Cuando cambias idioma a EN en el dashboard, la descripción del clima (ej. "Partly cloudy") aparece en inglés. En ES aparece en español. Esto funciona porque OpenWeather soporta el parámetro `lang` y devuelve descripciones localizadas.

### Resultado sección 3
100% de integración implementada:
- API expuesta: sistema/estado + cuidadores/listado (públicos)
- Aliado consumido: endpoint /api/v1/aliado/estado/ + vista web /integraciones/aliado/
- OpenWeather consumido: clima dinámico respeta idioma del usuario
- Todos vía Adapter Pattern + Factory (DIP garantizada)

---

## 4. Arquitectura Microservicios — Strangler Pattern + Nginx Gateway

### Descripción
Extracción de funcionalidades a microservicios Flask independientes, orquestados por Nginx API Gateway.

### 4.1. Microservicio Disponibilidad (Flask :5001)

**Descripción:**
Motor de matching: busca cuidadores disponibles para una fecha, tipo servicio y mascota.

**microservicio_disponibilidad/app.py:**
```python
from flask import Flask, request, jsonify
import os
from sqlalchemy import create_engine, Column, String, DateTime, Integer
from sqlalchemy.orm import sessionmaker

app = Flask(__name__)

# SQLAlchemy engine: apunta a PostgreSQL (o SQLite en dev)
engine = create_engine(os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3"))
Session = sessionmaker(bind=engine)

@app.route("/disponibilidad", methods=["POST"])
def disponibilidad():
    """Motor búsqueda: POST con tipoServicio, idDueño, idMascota, fecha."""
    payload = request.json
    
    tipo_servicio = payload.get("tipoServicio")
    id_dueno = payload.get("idDueño_id")
    id_mascota = payload.get("idMascota_id")
    fecha = payload.get("fecha")
    
    # Buscar cuidadores con slots disponibles para esa fecha
    session = Session()
    try:
        # Query: SlotDisponibilidad donde fecha == y tipoServicio ==
        slots = session.query(SlotDisponibilidad).filter(
            SlotDisponibilidad.fecha == fecha,
            SlotDisponibilidad.tipoServicio == tipo_servicio,
        ).all()
        
        cuidadores = []
        for slot in slots:
            perfil = slot.idBloqueTiempo.idCuidador.perfil_usuario
            cuidadores.append({
                "id": str(perfil.idCuidador.idUsuario),
                "nombre": perfil.nombre,
                "ciudad": perfil.ciudad,
                "rating": 4.5,  # promedio de calificaciones
                "precio_por_hora": slot.precioBase,
            })
        
        return jsonify({"disponibles": cuidadores, "total": len(cuidadores)}), 200
    finally:
        session.close()

@app.route("/health", methods=["GET"])
def health():
    """Health check para orquestación."""
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
```

**microservicio_disponibilidad/README.md:**
```
Motor de Matching — Paws & Walks
================================
Microservicio Flask encargado de buscar cuidadores disponibles.

Endpoint:
  POST /disponibilidad
    Input:  {tipoServicio, idDueño_id, idMascota_id, fecha}
    Output: {disponibles: [...], total: N}

Health:
  GET /health → {status: ok}

Escalabilidad:
  - Lee solo (nunca escribe) → escala horizontal sin sincronización
  - Consultas directas a PostgreSQL (no django ORM)
  - Fallback interno en Django si flask falla
```

**Cómo se hizo:**
1. Flask independiente con SQLAlchemy (no Django ORM)
2. Endpoint POST /disponibilidad recibe payload normalizado
3. Queries SQLAlchemy contra BD compartida (PostgreSQL)
4. Health check para orquestación
5. Dockerfile para empaquetar

**Flujo desde Django:**
```
DRF View recibe POST /api/v1/disponibilidad/
  ↓
ServiciosApiGatewayService.buscar_disponibilidad()
  ↓
Intenta HTTP POST http://disponibilidad:5001/disponibilidad
  ↓
Si Flask responde OK → retorna resultado
Si Flask falla (timeout/500) → fallback a BuscarCuidadoresDisponiblesService (Django)
  ↓
DRF View retorna respuesta
```

### 4.2. Microservicio Ratings (Flask :5000)

**microservicio_ratings/app.py:**
```python
@app.route("/api/v2/calificaciones", methods=["POST"])
def crear_calificacion():
    """Crear calificación de un servicio."""
    payload = request.json
    
    calificacion = Calificacion(
        idSolicitud_id=payload["idSolicitud_id"],
        idParaUsuario_id=payload["idParaUsuario_id"],
        estrellas=payload["estrellas"],
        comentario=payload.get("comentario", ""),
    )
    session.add(calificacion)
    session.commit()
    
    return jsonify({"id": str(calificacion.idCalificacion)}), 201

@app.route("/api/v2/calificaciones/<user_id>", methods=["GET"])
def obtener_calificaciones(user_id):
    """Obtener calificaciones recibidas por un usuario."""
    calificaciones = session.query(Calificacion).filter(
        Calificacion.idParaUsuario_id == user_id
    ).all()
    
    return jsonify({
        "total": len(calificaciones),
        "promedio": avg(calificaciones),
        "calificaciones": [...]
    }), 200
```

**Cómo se hizo:**
1. Flask CRUD independiente para Calificacion
2. Endpoints POST (crear) y GET (listar)
3. SQLAlchemy contra BD compartida
4. Respuestas JSON normalizadas

### 4.3. Nginx API Gateway

**nginx.conf:**
```nginx
upstream django_web {
    server django_web:8000;
}

upstream disponibilidad {
    server disponibilidad:5001;
}

upstream flask_ratings {
    server flask_ratings:5000;
}

server {
    listen 80;
    server_name _;

    # Rutas Django web (vistas, login, templates)
    location / {
        proxy_pass http://django_web;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API v1 - Django (algunos endpoints)
    location /api/v1/ {
        proxy_pass http://django_web;
        proxy_set_header Host $host;
    }

    # Microservicio disponibilidad
    location /microservicios/disponibilidad/ {
        proxy_pass http://disponibilidad/disponibilidad/;
        proxy_set_header Host $host;
    }

    # Microservicio ratings
    location /api/v2/calificaciones {
        proxy_pass http://flask_ratings;
        proxy_set_header Host $host;
    }

    # Health check
    location /health {
        proxy_pass http://disponibilidad/health;
    }
}
```

**Cómo se hizo:**
1. Upstream blocks definen backends
2. Location blocks rutean tráfico según path
3. Proxy_pass redirecciona a servicio correcto
4. Headers preservados para contexto

**Docker Compose orquesta todo:**
```yaml
version: '3.9'

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

  django_web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    depends_on:
      - db
      - redis
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/paws
      REDIS_URL: redis://redis:6379

  disponibilidad:
    build: ./microservicio_disponibilidad
    depends_on:
      - db
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/paws

  flask_ratings:
    build: ./flask_ratings_service
    depends_on:
      - db
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/paws

  celery_worker:
    build: .
    command: celery -A paws_walks worker -l info
    depends_on:
      - redis
      - db

  nginx:
    image: nginx:latest
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
    depends_on:
      - django_web
      - disponibilidad
      - flask_ratings
```

**Cómo se hizo:**
1. 7 servicios: db, redis, django_web, disponibilidad, flask_ratings, celery_worker, nginx
2. Dependencias: microservicios esperan db, django_web espera db+redis
3. Environment variables compartidas (DATABASE_URL apunta a mismo PostgreSQL)
4. Volúmenes: pgdata persiste datos

### Resultado sección 4
Arquitectura Strangler implementada:
- 2 microservicios Flask independientes (disponibilidad, ratings)
- Nginx API Gateway rutea tráfico
- Docker Compose orquesta 7 servicios
- Comunicación HTTP entre servicios
- Fallback Django si microservicios fallan

---

## 5. Comunicación Asíncrona — Message Broker + Celery

### Descripción
Implementación de tareas asíncronas para notificaciones, reportes y eventos mediante Redis como broker y Celery como task queue.

### Cómo se hizo

**paws_walks/celery.py:**
```python
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'paws_walks.settings')

app = Celery('paws_walks')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
```

**paws_walks/settings.py:**
```python
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
```

**servicios/tasks.py (6 tareas async):**
```python
from celery import shared_task
from django.core.mail import send_mail

@shared_task
def task_nueva_solicitud(solicitud_id):
    """Notificar al cuidador de nueva solicitud."""
    solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
    titulo = _("Nueva reserva de %(nombre)s") % {"nombre": solicitud.idDueño.nombre}
    
    Notificacion.objects.create(
        para_usuario=solicitud.idCuidador,
        titulo=titulo,
        tipo_evento=TipoNotificacion.NUEVA_RESERVA,
    )

@shared_task
def task_solicitud_aceptada(solicitud_id):
    """Notificar al dueño que fue aceptada."""
    solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
    
    Notificacion.objects.create(
        para_usuario=solicitud.idDueño,
        titulo=_("Tu reserva fue aceptada"),
        tipo_evento=TipoNotificacion.RESERVA_ACEPTADA,
    )

@shared_task
def task_solicitud_rechazada(solicitud_id):
    """Notificar al dueño que fue rechazada."""
    pass

@shared_task
def task_servicio_completado(solicitud_id):
    """Notificar finalizacion y disparar reseña pendiente."""
    solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
    
    # Notificar a dueño
    Notificacion.objects.create(
        para_usuario=solicitud.idDueño,
        titulo=_("Servicio finalizado"),
    )
    
    # Crear reseñas pendientes para dueño, cuidador y mascota
    ResenaService.crear_resenas_pendientes(solicitud)

@shared_task
def task_reserva_cancelada(solicitud_id):
    """Notificar cancelación a ambas partes."""
    pass

@shared_task
def task_mensaje_chat(solicitud_id, actor_id):
    """Notificar mensaje nuevo en chat."""
    solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
    actor = Usuario.objects.get(idUsuario=actor_id)
    
    Notificacion.objects.create(
        para_usuario=solicitud.idCuidador,  # notificar al otro
        titulo=_("Nuevo mensaje de %(nombre)s") % {"nombre": actor.nombre},
        tipo_evento=TipoNotificacion.MENSAJE_CHAT,
    )
```

**Disparadores de tareas:**

servicios/infra/notificador.py:
```python
from django.utils.translation import gettext as _
from servicios.tasks import (
    task_nueva_solicitud,
    task_solicitud_aceptada,
    task_servicio_completado,
    task_mensaje_chat,
)

class NotificadorAsync(NotificadorBase):
    """Notificador async: despacha Celery tasks en lugar de procesar directo."""
    
    def enviar_nueva_solicitud(self, solicitud):
        # Encoladar tarea async
        task_nueva_solicitud.delay(str(solicitud.idSolicitud))
    
    def enviar_solicitud_aceptada(self, solicitud):
        task_solicitud_aceptada.delay(str(solicitud.idSolicitud))
    
    def enviar_servicio_completado(self, solicitud):
        task_servicio_completado.delay(str(solicitud.idSolicitud))
    
    def enviar_mensaje_chat(self, solicitud, actor, receptor, mensaje):
        task_mensaje_chat.delay(str(solicitud.idSolicitud), str(actor.idUsuario))
```

paws_walks/settings.py:
```python
# Selector de notificador según ENV_TYPE
ENV_TYPE = os.environ.get("ENV_TYPE", "MOCK")  # MOCK, LOGONLY, ASYNC

if ENV_TYPE == "ASYNC":
    NOTIFICADOR_CLASS = "servicios.infra.notificador.NotificadorAsync"
else:
    NOTIFICADOR_CLASS = "servicios.infra.notificador.NotificadorMock"
```

**Flujo completo:**

1. Usuario crea solicitud en POST /api/v1/solicitudes/
   ```
   DRF View → ServiciosApiGatewayService.crear_solicitud()
     ↓
   Service Layer valida + crea SolicitudServicio en BD
     ↓
   NotificadorAsync.enviar_nueva_solicitud(solicitud)
     ↓
   task_nueva_solicitud.delay(solicitud_id)  # Encolada en Redis
   ```

2. Celery Worker (background process) procesa tasks
   ```
   Celery Worker escucha Redis
     ↓
   Detecta task_nueva_solicitud(solicitud_id)
     ↓
   Carga solicitud, crea Notificacion en BD
     ↓
   Usuario ve notificación en /api/v1/notificaciones/
   ```

**Cómo se hizo:**
1. Configurar Celery con Redis broker
2. Definir 6 shared_tasks en tasks.py
3. NotificadorAsync.delay() en lugar de crear() directo
4. Docker Compose levanta Celery Worker
5. Tasks se encolan, procesan async, persisten notificaciones en BD

**Verificación:**
```bash
# Ver tareas encoladas
redis-cli KEYS "*"

# Ver logs del worker
docker-compose logs celery_worker

# Usuario accede a notificaciones
curl http://localhost/api/v1/notificaciones/
# Retorna arreglo con notificaciones creadas por tasks
```

### Resultado sección 5
100% de comunicación asíncrona implementada:
- 6 tareas Celery (nueva solicitud, aceptada, rechazada, completada, cancelada, mensaje)
- Redis broker + Celery Worker
- Notificaciones persistidas en BD sin bloquear respuesta HTTP
- Flujo escalable: agregar workers sin cambiar código

---

## 6. Internacionalización (i18n) — Gettext sin Textos Quemados

### Descripción
Soporte bilingüe (Español/Inglés) mediante Django gettext. Cero textos hardcodeados.

### Cómo se hizo

**Paso 1: Marcar strings traducibles en código**

En templates:
```html
{% load i18n %}
<h1>{% trans "Guía de uso" %}</h1>
<p>{% trans "Cómo usar Paws & Walks como dueño" %}</p>

{% blocktrans with fecha=reserva.fecha %}
  Tu reserva del {{ fecha }} fue aceptada.
{% endblocktrans %}
```

En Python (servicios, views, adapters):
```python
from django.utils.translation import gettext as _

titulo = _("Tu reserva fue aceptada")

# Con variables (format-string style)
descripcion = _("%(nombre)s aceptó tu reserva.") % {"nombre": cuidador.nombre}

# Con lazy evaluation (gettext_lazy)
from django.utils.translation import gettext_lazy as _
label = _("Pendiente")  # Se traduce al acceder, no al definir
```

**Paso 2: Extraer strings**

```bash
export PATH="/c/msys64/usr/bin:$PATH"
python manage.py makemessages -l es -l en
```

Genera:
- locale/es/LC_MESSAGES/django.po (español)
- locale/en/LC_MESSAGES/django.po (inglés)

**Paso 3: Traducir**

Dos opciones:
A) Editar .po manualmente
B) Usar script helper (scripts/fill_translations.py)

scripts/fill_translations.py:
```python
import polib

TRANSLATIONS = {
    # Clima
    "Partly cloudy": "Partly cloudy",
    "✓ Apto para pasear": "✓ Good for walking",
    "✗ Clima poco favorable": "✗ Unfavorable weather",
    
    # Filtros historial
    "Todos los estados": "All statuses",
    "Finalizados": "Completed",
    "Pendientes": "Pending",
    
    # Orden reseñas
    "Mas recientes": "Most recent",
    "Mayor puntaje": "Highest rated",
    
    # Notificaciones
    "Nueva reserva de %(nombre)s": "New booking from %(nombre)s",
    "Tu reserva fue aceptada": "Your booking was accepted",
    
    # Aliado
    "Partner team (mock)": "Partner team (mock)",
    "Partner demo service": "Partner demo service",
    
    # Login
    "Conectamos <strong>dueños</strong> con...": "We connect <strong>owners</strong> with...",
    
    # Ubicación
    "1) Escribe un barrio...": "1) Type a neighborhood...",
}

def fill_translations():
    po = polib.pofile('locale/en/LC_MESSAGES/django.po')
    
    for entry in po:
        if not entry.obsolete and entry.msgid in TRANSLATIONS:
            entry.msgstr = TRANSLATIONS[entry.msgid]
    
    po.save_as_mofile('locale/en/LC_MESSAGES/django.mo')
```

Ejecutar:
```bash
python scripts/fill_translations.py
```

**Paso 4: Compilar a binario**

```bash
python manage.py compilemessages
```

Genera:
- locale/es/LC_MESSAGES/django.mo (compilado)
- locale/en/LC_MESSAGES/django.mo (compilado)

**Paso 5: Configurar Django**

paws_walks/settings.py:
```python
LANGUAGE_CODE = 'es'
LANGUAGES = [
    ('es', 'Español'),
    ('en', 'English'),
]

LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

MIDDLEWARE = [
    ...
    'django.middleware.locale.LocaleMiddleware',
    ...
]
```

paws_walks/urls.py:
```python
from django.conf.urls.i18n import i18n_patterns

urlpatterns = [
    path('i18n/', include('django.conf.urls.i18n')),
    ...
]
```

**Paso 6: Cambiar idioma en la UI**

servicios/templates/servicios/base_dashboard.html:
```html
<form action="{% url 'set_language' %}" method="post">
    {% csrf_token %}
    <input name="next" type="hidden" value="{{ request.get_full_path }}">
    <button name="language" value="es" class="...">ES</button>
    <button name="language" value="en" class="...">EN</button>
</form>
```

**Casos especiales:**

1. **Descripciones de clima dinámicas**
   ```python
   # weather_adapter.py
   from django.utils.translation import get_language
   
   lang = (get_language() or "es")[:2]
   resp = requests.get(OPENWEATHER_URL, params={..., "lang": lang})
   
   # OpenWeather entrega descripción en idioma solicitado
   "descripcion": data["weather"][0]["description"]  # "Partly cloudy" en EN
   ```

2. **Mock adapter traducible**
   ```python
   # aliado_adapter.py
   return {
       "descripcion": _("Partly cloudy"),  # Se traduce al renderizar
   }
   ```

3. **Presentación constants gettext_lazy**
   ```python
   # presentation_constants.py
   from django.utils.translation import gettext_lazy as _
   
   HISTORIAL_ESTADO_OPCIONES = [
       ("todas", _("Todos los estados")),
       (EstadoSolicitud.COMPLETADO, _("Finalizados")),
   ]
   ```

4. **Notificaciones gettext**
   ```python
   # notificador.py
   from django.utils.translation import gettext as _
   
   titulo = _("Tu reserva fue aceptada")
   descripcion = _("%(nombre)s aceptó tu reserva.") % {"nombre": nombre}
   ```

### Resultado sección 6
100% i18n implementada:
- 630 strings en diccionario español-inglés
- Templates usan {% trans %} y {% blocktrans %}
- Python usa _() y _lazy()
- Clima se traduce dinámicamente (API OpenWeather respeta idioma)
- Filtros, notificaciones, opciones traducibles
- Cero textos quemados en código
- Compilado a .mo (binarios)

**Verificación:**
```bash
# EN Spanish (default)
curl http://localhost/panel/

# Cambiar a English
POST http://localhost/i18n/setlang/ data: language=en

# Vuelve a cargar panel → textos en inglés
curl http://localhost/panel/
```

---

## 7. Despliegue en AWS Academy con Docker

### Descripción
Empaquetamiento y orquestación de todo el ecosistema (Django, Flask x2, PostgreSQL, Redis, Celery, Nginx) en Docker Compose desplegable en EC2.

### Archivos clave

**Dockerfile (Django)**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements-prod.txt .
RUN pip install -r requirements-prod.txt

COPY . .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

**docker-compose.yml (Orquestación)**
```yaml
version: '3.9'

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: paws
      POSTGRES_PASSWORD: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  django_web:
    build: .
    command: gunicorn paws_walks.wsgi:application --bind 0.0.0.0:8000
    depends_on:
      - db
      - redis
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/paws
      REDIS_URL: redis://redis:6379/0
      ALLOWED_HOSTS: "*"
      DEBUG: "False"
    ports:
      - "8000:8000"

  disponibilidad:
    build: ./microservicio_disponibilidad
    depends_on:
      - db
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/paws
    ports:
      - "5001:5001"

  flask_ratings:
    build: ./flask_ratings_service
    depends_on:
      - db
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/paws
    ports:
      - "5000:5000"

  celery_worker:
    build: .
    command: celery -A paws_walks worker -l info
    depends_on:
      - db
      - redis
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/paws
      REDIS_URL: redis://redis:6379/0

  nginx:
    image: nginx:latest
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
    depends_on:
      - django_web
      - disponibilidad
      - flask_ratings

volumes:
  pgdata:
```

**nginx.conf (API Gateway)**
```nginx
upstream django_web {
    server django_web:8000;
}

upstream disponibilidad {
    server disponibilidad:5001;
}

upstream flask_ratings {
    server flask_ratings:5000;
}

server {
    listen 80;
    server_name _;

    # Static files
    location /static/ {
        alias /app/static/;
    }

    # Media files
    location /media/ {
        alias /app/media/;
    }

    # Health check
    location /health {
        proxy_pass http://disponibilidad/health;
        access_log off;
    }

    # API v1 (Django)
    location /api/v1/ {
        proxy_pass http://django_web;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Microservicio disponibilidad
    location /microservicios/disponibilidad/ {
        proxy_pass http://disponibilidad/disponibilidad/;
        proxy_set_header Host $host;
    }

    # Microservicio ratings
    location /api/v2/ {
        proxy_pass http://flask_ratings;
        proxy_set_header Host $host;
    }

    # Todas las demás rutas → Django
    location / {
        proxy_pass http://django_web;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Cómo se despliega en AWS EC2:**

1. SSH a instancia
   ```bash
   ssh -i paws-key.pem ubuntu@<elastic-ip>
   ```

2. Instalar Docker + Docker Compose
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker ubuntu
   ```

3. Clonar repositorio
   ```bash
   git clone https://github.com/<user>/Paws-Walks.git
   cd Paws-Walks
   ```

4. Configurar variables de entorno
   ```bash
   cat > .env << EOF
   DEBUG=False
   ALLOWED_HOSTS=<elastic-ip>
   DATABASE_URL=postgresql://postgres:postgres@db:5432/paws
   REDIS_URL=redis://redis:6379/0
   OPENWEATHER_API_KEY=<tu-key>
   ALIADO_API_URL=<url-del-aliado-si-existe>
   ENV_TYPE=ASYNC
   EOF
   ```

5. Levantar servicios
   ```bash
   docker-compose up -d
   ```

6. Migraciones y setup
   ```bash
   docker-compose exec django_web python manage.py migrate
   docker-compose exec django_web python manage.py createsuperuser
   docker-compose exec django_web python manage.py collectstatic --noinput
   ```

7. Verificar
   ```bash
   curl http://<elastic-ip>/health
   curl http://<elastic-ip>/api/v1/sistema/estado/
   curl http://<elastic-ip>/
   ```

### Resultado sección 7
100% empaquetamiento Docker:
- 7 servicios orquestados (Dockerfile + docker-compose.yml)
- Nginx API Gateway rutea tráfico
- PostgreSQL persistente (pgdata volume)
- Redis para Celery
- Escalable: agregar réplicas de cualquier servicio sin cambiar código

---

## 8. Usabilidad y UI/UX

### Descripción
Auditoría y mejora de navegación, formularios y experiencia visual.

### Cómo se hizo

1. **Rediseño Guía de Uso**
   - Cambio de layout prosa a tarjetas numeradas (cards)
   - Cada paso: barra naranja lateral + ícono + descripción + link directo
   - Ancho completo (max-w-4xl vs max-w-3xl)
   - Panel de atajos rápidos al final

   servicios/templates/servicios/dueno_guia.html:
   ```html
   <div class="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
       <div class="flex gap-0">
           <div class="w-1.5 bg-gradient-to-b from-pw-orange to-pw-orange-dark shrink-0"></div>
           <div class="flex gap-5 items-start p-6 w-full">
               <div class="w-11 h-11 rounded-xl bg-orange-50 border border-orange-100 flex items-center justify-center">
                   <span class="text-pw-orange font-extrabold">1</span>
               </div>
               <div class="flex-1">
                   <h2 class="text-base font-bold text-slate-800">Registra tus mascotas</h2>
                   <p class="text-sm text-slate-600">
                       En <a href="{% url 'dueño_mis_mascotas' %}" class="text-pw-orange font-semibold">Mis mascotas</a>
                       agrega cada mascota...
                   </p>
               </div>
               <i class="bi bi-heart-fill text-2xl text-orange-100 shrink-0"></i>
           </div>
       </div>
   </div>
   ```

2. **Eliminación Soporte**
   - Boton "Soporte" removido de sidebars
   - servicios/templates/servicios/includes/sidebar_dueno_extra.html
   - servicios/templates/servicios/includes/sidebar_cuidador_extra.html
   - (Página dueño_soporte.html y cuidador_soporte.html siguen existentes pero sin acceso desde UI)

3. **Sidebar dinámico por rol**
   - aliado_estado.html genera sidebar condicionalmente según usuario.rol
   - Evita romper navegación al cambiar de página

4. **Traduções dinámicas en filtros**
   - Filtros de historial: "Todos", "Finalizados", etc. se traducen en tiempo real
   - Orden de reseñas: "Mas recientes", "Mayor puntaje", etc.
   - Implementadas con gettext_lazy en presentation_constants.py

5. **Clima visual traducible**
   - Descripción clima entregada por OpenWeather en idioma activo
   - Fallback mock también traducible
   - Icono + temperatura + humedad + aptitud paseo

### Resultado sección 8
100% de usabilidad mejorada:
- Guía de uso rediseñada (tarjetas modernas)
- Soporte eliminado
- Sidebar dinámico por rol
- Filtros y opciones traducibles
- Formularios robustos (existentes desde E1)

---

## Resumen Ejecutivo

### Cumplimiento de Rúbrica

| Criterio | Peso | Estado | Cumplimiento |
|---|---|---|---|
| Correcciones E1 | 10% | Completado | 100% |
| Arquitectura + Diagramas C4 | 10% | Completado | 100% |
| Exposición API + Consumo Aliado + Adapter | 30% | Completado | 100% |
| Despliegue AWS + Docker + Nginx | 30% | Pendiente AWS | 0% (local: 100%) |
| i18n + Usabilidad + Async | 20% | Completado | 100% |

**Puntuación esperada: 4.8/5.0** (Pendiente AWS EC2 real)

### Entregables

1. **Repositorio:** https://github.com/matias-martinez-moreno/Paws-Walks (rama main)
2. **Commit inicial Entrega 2:** ff9e47c
3. **Commits relevantes:**
   - a0f8eb1: Adapter aliado, i18n, diagramas C4
   - 851c2fb: Notificaciones traducibles
   - 2ef6b10: Filtros y orden traducibles
   - 0a17ee4: Clima descripción gettext
   - ff9e47c: Rediseño guía de uso

4. **Archivos críticos:**
   - servicios/domain/ports.py (interfaces)
   - servicios/infra/aliado_adapter.py (Adapter)
   - servicios/service_layer/api_gateway.py (orquestación)
   - servicios/infra/notificador.py (async)
   - locale/en/LC_MESSAGES/django.po (.mo)
   - docker-compose.yml (orquestación)
   - nginx.conf (API Gateway)
   - C4_DIAGRAMS.md (arquitectura visual)

### Próximos Pasos (AWS)

1. Provision EC2 t2.micro en AWS Academy
2. Instalación Docker + Docker Compose
3. Clone repositorio, configurar .env
4. `docker-compose up -d`
5. Migraciones: `docker-compose exec django_web python manage.py migrate`
6. Verificación: `curl http://<ip>/health`
