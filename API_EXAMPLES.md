# Paws & Walks API — Curl Examples

Complete guide for testing all API endpoints using curl commands.

---

## Table of Contents

1. [Setup](#setup)
2. [Public Endpoints](#public-endpoints)
3. [Authenticated Endpoints](#authenticated-endpoints)
4. [Microservices](#microservices)
5. [Error Responses](#error-responses)

---

## Setup

### Base URL

**Local Development:**
```
http://localhost:8000/api/
```

**Docker:**
```
http://localhost/api/
```

### Headers

Most endpoints require the following headers:
```
Content-Type: application/json
```

Authentication endpoints require:
```
Authorization: Bearer <token>
```
or session cookies.

### Environment Variables

For easier testing, set these variables:
```bash
# Set base URL
BASE_URL="http://localhost:8000"

# Set user credentials (use actual values)
DUEÑO_ID="550e8400-e29b-41d4-a716-446655440000"
MASCOTA_ID="660e8400-e29b-41d4-a716-446655440001"
CUIDADOR_ID="770e8400-e29b-41d4-a716-446655440002"
```

Then use `$BASE_URL` in curl commands instead of hardcoding URLs.

---

## Public Endpoints

### 1. System Status

Get general system statistics (no authentication required).

```bash
curl -X GET "$BASE_URL/api/v1/sistema/estado/" \
  -H "Content-Type: application/json"
```

**Response:**
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

**Usage:**
```bash
# Pretty print response
curl -s "$BASE_URL/api/v1/sistema/estado/" | jq '.'

# Save to file
curl -s "$BASE_URL/api/v1/sistema/estado/" > sistema_estado.json
```

---

### 2. List Verified Caregivers

Get list of all verified caregivers with ratings (no authentication required).

```bash
curl -X GET "$BASE_URL/api/v1/cuidadores/listado/" \
  -H "Content-Type: application/json"
```

**Response:**
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
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "nombre": "Carlos López",
      "ciudad": "Bogotá",
      "foto": "/media/fotos/carlos.jpg",
      "verificado": true,
      "total_reseñas": 35,
      "rating_promedio": 4.6
    }
  ],
  "timestamp": "2026-05-06T10:35:00Z"
}
```

**Usage Examples:**

```bash
# List all caregivers
curl -s "$BASE_URL/api/v1/cuidadores/listado/" | jq '.'

# Count caregivers
curl -s "$BASE_URL/api/v1/cuidadores/listado/" | jq '.count'

# Get names and ratings only
curl -s "$BASE_URL/api/v1/cuidadores/listado/" | \
  jq '.resultados[] | {nombre, rating_promedio}'

# Find high-rated caregivers (4.7+)
curl -s "$BASE_URL/api/v1/cuidadores/listado/" | \
  jq '.resultados[] | select(.rating_promedio >= 4.7)'
```

---

### 3. Get Weather by City

Get weather information for a city (no authentication required).

```bash
curl -X GET "$BASE_URL/api/v1/clima/?ciudad=Medellín" \
  -H "Content-Type: application/json"
```

**Response:**
```json
{
  "ciudad": "Medellín",
  "temperatura": 22,
  "descripcion": "Parcialmente nublado",
  "humedad": 65,
  "viento": 8,
  "timestamp": "2026-05-06T10:40:00Z"
}
```

**Usage Examples:**

```bash
# Get weather for Medellín
curl -s "$BASE_URL/api/v1/clima/?ciudad=Medellín" | jq '.'

# Get weather for Bogotá
curl -s "$BASE_URL/api/v1/clima/?ciudad=Bogotá" | jq '.'

# Check temperature
curl -s "$BASE_URL/api/v1/clima/?ciudad=Medellín" | jq '.temperatura'

# Get description only
curl -s "$BASE_URL/api/v1/clima/?ciudad=Medellín" | jq '.descripcion'
```

---

## Authenticated Endpoints

### Prerequisites

You need to log in first to get session cookies or tokens.

#### Login (Session-based)

```bash
curl -X POST "$BASE_URL/../login/" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=usuario@example.com&password=contraseña123" \
  -c cookies.txt
```

This saves cookies to `cookies.txt` for subsequent requests.

#### Login (Token-based - Future)

```bash
curl -X POST "$BASE_URL/auth/token/" \
  -H "Content-Type: application/json" \
  -d '{"username":"usuario@example.com","password":"contraseña123"}'
```

**Response:**
```json
{
  "token": "abcd1234efgh5678ijkl9012mnop3456"
}
```

---

### 1. Create Service Request

Create a new service request (paseo or guardería).

```bash
curl -X POST "$BASE_URL/api/v1/solicitudes/" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "idMascota_id": "'$MASCOTA_ID'",
    "tipoServicio": "paseo",
    "fecha": "2026-05-10",
    "duracionMinutos": 60,
    "ubicacionParcela": "Cra 5 #3-45, Medellín"
  }'
```

**Request Fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `idMascota_id` | UUID | Yes | Pet ID |
| `tipoServicio` | string | Yes | "paseo" or "guarderia" |
| `fecha` | date | Yes | Service date (YYYY-MM-DD) |
| `duracionMinutos` | integer | Yes | Duration in minutes |
| `ubicacionParcela` | string | No | Service location |
| `cuidador_id` | UUID | No | Specific caregiver (optional) |

**Response:**
```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "estado": "pendiente",
  "idDueño_id": "550e8400-e29b-41d4-a716-446655440000",
  "idMascota_id": "660e8400-e29b-41d4-a716-446655440001",
  "tipoServicio": "paseo",
  "fecha": "2026-05-10",
  "duracionMinutos": 60,
  "ubicacionParcela": "Cra 5 #3-45, Medellín",
  "created_at": "2026-05-06T10:45:00Z",
  "timestamp": "2026-05-06T10:45:00Z"
}
```

**Usage Examples:**

```bash
# Create a walk request
curl -s -X POST "$BASE_URL/api/v1/solicitudes/" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "idMascota_id": "'$MASCOTA_ID'",
    "tipoServicio": "paseo",
    "fecha": "2026-05-10",
    "duracionMinutos": 60
  }' | jq '.'

# Create a daycare request
curl -s -X POST "$BASE_URL/api/v1/solicitudes/" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "idMascota_id": "'$MASCOTA_ID'",
    "tipoServicio": "guarderia",
    "fecha": "2026-05-15",
    "duracionMinutos": 480
  }' | jq '.id'
```

---

### 2. Get Service Request Details

Retrieve details of a specific service request.

```bash
curl -X GET "$BASE_URL/api/v1/solicitudes/<uuid>/" \
  -H "Content-Type: application/json" \
  -b cookies.txt
```

**Example:**
```bash
SOLICITUD_ID="880e8400-e29b-41d4-a716-446655440003"
curl -s -X GET "$BASE_URL/api/v1/solicitudes/$SOLICITUD_ID/" \
  -b cookies.txt | jq '.'
```

**Response:**
```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "estado": "pendiente",
  "idDueño_id": "550e8400-e29b-41d4-a716-446655440000",
  "idMascota_id": "660e8400-e29b-41d4-a716-446655440001",
  "tipoServicio": "paseo",
  "fecha": "2026-05-10",
  "duracionMinutos": 60,
  "ubicacionParcela": "Cra 5 #3-45, Medellín",
  "cuidador_id": null,
  "created_at": "2026-05-06T10:45:00Z",
  "updated_at": "2026-05-06T10:45:00Z"
}
```

---

### 3. Cancel Service Request

Cancel a service request.

```bash
curl -X POST "$BASE_URL/api/v1/solicitudes/<uuid>/cancelar/" \
  -H "Content-Type: application/json" \
  -b cookies.txt
```

**Example:**
```bash
SOLICITUD_ID="880e8400-e29b-41d4-a716-446655440003"
curl -s -X POST "$BASE_URL/api/v1/solicitudes/$SOLICITUD_ID/cancelar/" \
  -b cookies.txt | jq '.'
```

**Response:**
```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "estado": "cancelado",
  "message": "Solicitud cancelada exitosamente"
}
```

---

### 4. Search Caregiver Availability

Search for available caregivers (usually done before creating a request).

```bash
curl -X POST "$BASE_URL/api/v1/disponibilidad/" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "tipoServicio": "paseo",
    "fecha": "2026-05-10",
    "duracionMinutos": 60,
    "idMascota_id": "'$MASCOTA_ID'"
  }'
```

**Request Fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `tipoServicio` | string | Yes | "paseo" or "guarderia" |
| `fecha` | date | Yes | Desired service date |
| `duracionMinutos` | integer | Yes | Duration in minutes |
| `idMascota_id` | UUID | No | Pet ID (for validation) |

**Response:**
```json
{
  "disponibles": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "nombre": "María García",
      "ciudad": "Medellín",
      "rating": 4.8,
      "total_reseñas": 42,
      "precio_por_hora": 25000,
      "experiencia_años": 5,
      "especializacion": ["perros", "gatos"]
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "nombre": "Carlos López",
      "ciudad": "Medellín",
      "rating": 4.6,
      "total_reseñas": 35,
      "precio_por_hora": 22000,
      "experiencia_años": 3,
      "especializacion": ["perros"]
    }
  ],
  "timestamp": "2026-05-06T11:00:00Z"
}
```

**Usage Examples:**

```bash
# Search for walks on specific date
curl -s -X POST "$BASE_URL/api/v1/disponibilidad/" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "tipoServicio": "paseo",
    "fecha": "2026-05-10",
    "duracionMinutos": 60
  }' | jq '.disponibles[] | {nombre, ciudad, rating}'

# Find cheapest available caregiver
curl -s -X POST "$BASE_URL/api/v1/disponibilidad/" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "tipoServicio": "paseo",
    "fecha": "2026-05-10",
    "duracionMinutos": 60
  }' | jq '.disponibles | sort_by(.precio_por_hora) | .[0]'

# Find highest-rated caregiver
curl -s -X POST "$BASE_URL/api/v1/disponibilidad/" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "tipoServicio": "paseo",
    "fecha": "2026-05-10",
    "duracionMinutos": 60
  }' | jq '.disponibles | sort_by(-.rating) | .[0]'
```

---

## Microservices

### Disponibilidad Microservice

Direct endpoint (if running independently at port 5001).

```bash
curl -X GET http://localhost:5001/health
```

**Response:**
```json
{
  "status": "healthy"
}
```

#### Direct Available Caregivers Search

```bash
curl -X POST http://localhost:5001/disponibilidad \
  -H "Content-Type: application/json" \
  -d '{
    "tipoServicio": "paseo",
    "idDueño_id": "'$DUEÑO_ID'",
    "idMascota_id": "'$MASCOTA_ID'",
    "fecha": "2026-05-10",
    "duracionMinutos": 60
  }'
```

---

## Error Responses

### 400 Bad Request

Missing or invalid field in request.

```json
{
  "detail": "Campo 'tipoServicio' es requerido"
}
```

**Solution:** Check all required fields are included and valid.

---

### 401 Unauthorized

Authentication required but not provided.

```json
{
  "detail": "Debe autenticarse primero"
}
```

**Solution:** Log in first and include cookies/tokens.

---

### 403 Forbidden

User doesn't have permission for this action.

```json
{
  "detail": "No tiene permiso para realizar esta acción"
}
```

**Solution:** Ensure you have the correct role (dueño/cuidador).

---

### 404 Not Found

Resource doesn't exist.

```json
{
  "detail": "Solicitud de servicio no encontrada"
}
```

**Solution:** Verify the UUID is correct and the resource exists.

---

### 409 Conflict

Request conflicts with current state.

```json
{
  "detail": "Solicitud ya ha sido cancelada"
}
```

**Solution:** Check the resource's current state before acting.

---

## Testing Workflow

### Complete Flow: Creating a Reservation

```bash
#!/bin/bash

BASE_URL="http://localhost:8000"

echo "1. Login..."
curl -X POST "$BASE_URL/login/" \
  -d "username=usuario@example.com&password=contraseña123" \
  -c cookies.txt \
  -b cookies.txt

echo "2. Get available caregivers..."
curl -s -X POST "$BASE_URL/api/v1/disponibilidad/" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "tipoServicio": "paseo",
    "fecha": "2026-05-10",
    "duracionMinutos": 60,
    "idMascota_id": "'$MASCOTA_ID'"
  }' | jq '.disponibles[0]'

echo "3. Create service request..."
curl -s -X POST "$BASE_URL/api/v1/solicitudes/" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "idMascota_id": "'$MASCOTA_ID'",
    "tipoServicio": "paseo",
    "fecha": "2026-05-10",
    "duracionMinutos": 60
  }' | jq '{id, estado, tipoServicio}'

echo "4. Check system status..."
curl -s "$BASE_URL/api/v1/sistema/estado/" | jq '.total_solicitudes'
```

Save this as `workflow_test.sh`, make it executable, and run it:

```bash
chmod +x workflow_test.sh
./workflow_test.sh
```

---

## Tips & Tricks

### Pretty Print JSON
```bash
curl -s <url> | jq '.'
```

### Save Response to File
```bash
curl -s <url> > response.json
jq '.' response.json
```

### Set Custom Headers
```bash
curl -H "X-Custom-Header: value" <url>
```

### Follow Redirects
```bash
curl -L <url>
```

### Verbose Output
```bash
curl -v <url>
```

### Include Response Headers
```bash
curl -i <url>
```

### Measure Response Time
```bash
curl -w "Time: %{time_total}s\n" -o /dev/null -s <url>
```

---

## References

- [Curl Documentation](https://curl.se/docs/)
- [jq Manual](https://stedolan.github.io/jq/)
- [HTTP Status Codes](https://httpwg.org/specs/rfc9110.html#status.codes)
