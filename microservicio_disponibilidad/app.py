"""
Microservicio de Disponibilidad — Flask API.
Motor de búsqueda de cuidadores disponibles.
Escala independiente del core transaccional de Django.
"""
import logging
import os

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)


def _get_service():
    try:
        from services import BuscarDisponibilidadService
        return BuscarDisponibilidadService()
    except Exception as e:
        log.error("Error al importar BuscarDisponibilidadService: %s", e)
        raise


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "servicio": "disponibilidad"})


@app.route("/disponibilidad", methods=["POST"])
def buscar_disponibilidad():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"detail": "payload JSON requerido"}), 400

    log.info("Payload recibido: idDueño_id=%s, tipoServicio=%s, mascota=%s",
             data.get("idDueño_id"), data.get("tipoServicio"), data.get("idMascota_id"))

    tipo = data.get("tipoServicio")
    if tipo not in ("paseo", "guarderia"):
        return jsonify({"detail": "tipoServicio debe ser 'paseo' o 'guarderia'"}), 400

    if not data.get("idDueño_id"):
        return jsonify({"detail": "idDueño_id es requerido"}), 400

    try:
        service = _get_service()
        resultado = service.buscar(data)
    except Exception as e:
        log.exception("Error en buscar_disponibilidad")
        return jsonify({"detail": str(e)}), 500

    if isinstance(resultado, dict) and "error" in resultado:
        log.warning("Error en búsqueda: %s", resultado.get("error"))
        status = resultado.pop("status", 400)
        return jsonify({"detail": resultado["error"]}), status

    log.info("Búsqueda exitosa: %d cuidadores encontrados", len(resultado))
    return jsonify(resultado), 200


@app.before_request
def _log_request():
    log.info("==> %s %s (raw_path=%s)", request.method, request.path, request.environ.get("RAW_URI"))


@app.errorhandler(404)
def _handle_404(e):
    rutas = [f"{','.join(r.methods - {'HEAD','OPTIONS'})} {r.rule}" for r in app.url_map.iter_rules()]
    log.error("404 %s %s. Rutas: %s", request.method, request.path, rutas)
    return jsonify({
        "detail": "not found",
        "method": request.method,
        "path": request.path,
        "rutas_disponibles": rutas,
    }), 404


log.info("Rutas registradas: %s", [str(r) for r in app.url_map.iter_rules()])

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    log.info("Iniciando microservicio disponibilidad en puerto %s", port)
    app.run(host="0.0.0.0", port=port, debug=False)
