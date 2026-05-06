#!/bin/bash

# ============================================================
# Test Script for Paws & Walks API Endpoints
# ============================================================
# This script validates all public API endpoints with curl
# Usage: bash test_endpoints.sh [base_url] [verbose]
# Example: bash test_endpoints.sh http://localhost:8000 v
# ============================================================

set -e

# Configuration
BASE_URL="${1:-http://localhost:8000}"
VERBOSE="${2:-}"
TIMEOUT=10
PASSED=0
FAILED=0

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}\n"
}

print_test() {
    echo -e "${YELLOW}[TEST]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED++))
}

print_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED++))
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

check_json_field() {
    local json=$1
    local field=$2
    if echo "$json" | jq -e ".$field" > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# ============================================================
# TESTS
# ============================================================

print_header "Paws & Walks API Endpoint Validation"
print_info "Base URL: $BASE_URL"
print_info "Timeout: ${TIMEOUT}s"

# Test 1: API Docs availability
print_test "API Documentation (Swagger) availability"
RESPONSE=$(curl -s -w "\n%{http_code}" -m $TIMEOUT "$BASE_URL/api/docs/" 2>/dev/null || echo "000")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "200" ]; then
    print_success "Swagger UI is accessible at /api/docs/"
else
    print_error "Swagger UI not accessible (HTTP $HTTP_CODE)"
fi

# Test 2: OpenAPI Schema
print_test "OpenAPI Schema availability"
RESPONSE=$(curl -s -w "\n%{http_code}" -m $TIMEOUT "$BASE_URL/api/schema/" 2>/dev/null || echo "000")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "200" ]; then
    print_success "OpenAPI schema available at /api/schema/"
else
    print_error "OpenAPI schema not accessible (HTTP $HTTP_CODE)"
fi

# Test 3: Sistema Estado endpoint
print_test "GET /api/v1/sistema/estado/ - System Status"
RESPONSE=$(curl -s -w "\n%{http_code}" -m $TIMEOUT \
    -H "Content-Type: application/json" \
    "$BASE_URL/api/v1/sistema/estado/" 2>/dev/null || echo "000")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    if check_json_field "$BODY" "total_usuarios"; then
        print_success "Sistema estado endpoint returns valid JSON with required fields"
        if [ "$VERBOSE" = "v" ] || [ "$VERBOSE" = "verbose" ]; then
            echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
        fi
    else
        print_error "Sistema estado endpoint returns JSON but missing expected fields"
        echo "$BODY"
    fi
else
    print_error "Sistema estado endpoint failed (HTTP $HTTP_CODE)"
fi

# Test 4: Cuidadores Listado endpoint
print_test "GET /api/v1/cuidadores/listado/ - Caregivers List"
RESPONSE=$(curl -s -w "\n%{http_code}" -m $TIMEOUT \
    -H "Content-Type: application/json" \
    "$BASE_URL/api/v1/cuidadores/listado/" 2>/dev/null || echo "000")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    if check_json_field "$BODY" "count"; then
        print_success "Cuidadores listado endpoint returns valid JSON with count field"
        COUNT=$(echo "$BODY" | jq '.count' 2>/dev/null || echo "unknown")
        print_info "Total caregivers available: $COUNT"

        if [ "$VERBOSE" = "v" ] || [ "$VERBOSE" = "verbose" ]; then
            echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
        fi
    else
        print_error "Cuidadores listado endpoint returns JSON but missing count field"
        echo "$BODY"
    fi
else
    print_error "Cuidadores listado endpoint failed (HTTP $HTTP_CODE)"
fi

# Test 5: Clima endpoint (public)
print_test "GET /api/v1/clima/?ciudad=Medellín - Weather Data"
RESPONSE=$(curl -s -w "\n%{http_code}" -m $TIMEOUT \
    -H "Content-Type: application/json" \
    "$BASE_URL/api/v1/clima/?ciudad=Medellín" 2>/dev/null || echo "000")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "404" ]; then
    if [ "$HTTP_CODE" = "200" ]; then
        if check_json_field "$BODY" "ciudad" || check_json_field "$BODY" "temperatura"; then
            print_success "Clima endpoint returns valid response"
            if [ "$VERBOSE" = "v" ] || [ "$VERBOSE" = "verbose" ]; then
                echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
            fi
        else
            print_error "Clima endpoint returns JSON but missing expected weather fields"
        fi
    else
        print_success "Clima endpoint accessible (may return 404 if city not found)"
    fi
else
    print_error "Clima endpoint failed (HTTP $HTTP_CODE)"
fi

# Test 6: Health check for microservices (if running)
print_test "Health check - Disponibilidad microservice"
RESPONSE=$(curl -s -w "\n%{http_code}" -m $TIMEOUT \
    -H "Content-Type: application/json" \
    "http://localhost:5001/health" 2>/dev/null || echo "000")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "404" ]; then
    print_success "Disponibilidad microservice is reachable"
else
    print_info "Disponibilidad microservice not running (expected if not in Docker: HTTP $HTTP_CODE)"
fi

# ============================================================
# SUMMARY
# ============================================================

print_header "Test Summary"
TOTAL=$((PASSED + FAILED))
print_info "Tests Passed: ${GREEN}$PASSED${NC}"
print_info "Tests Failed: ${RED}$FAILED${NC}"
print_info "Total Tests: $TOTAL"

if [ $FAILED -eq 0 ]; then
    echo -e "\n${GREEN}✓ All tests passed!${NC}\n"
    exit 0
else
    echo -e "\n${RED}✗ Some tests failed. Please check the output above.${NC}\n"
    exit 1
fi
