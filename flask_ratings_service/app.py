from flask import Flask, request, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

ratings_db = {}

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

@app.route('/api/v2/calificaciones', methods=['POST'])
def crear_calificacion():
    data = request.get_json()
    id_de = data.get('id_de')
    id_para = data.get('id_para')
    estrellas = data.get('estrellas')
    
    if not all([id_de, id_para, estrellas]):
        return jsonify({'error': 'Faltan campos'}), 400
    
    if not (1 <= estrellas <= 5):
        return jsonify({'error': 'Estrellas debe ser 1-5'}), 400
    
    key = f"{id_de}_{id_para}"
    ratings_db[key] = estrellas
    
    return jsonify({'mensaje': 'Calificación creada'}), 201

@app.route('/api/v2/calificaciones/<user_id>', methods=['GET'])
def obtener_calificaciones(user_id):
    calificaciones = [v for k, v in ratings_db.items() if k.endswith(f"_{user_id}")]
    
    if not calificaciones:
        return jsonify({'promedio': None, 'cantidad': 0}), 200
    
    promedio = sum(calificaciones) / len(calificaciones)
    return jsonify({'promedio': round(promedio, 1), 'cantidad': len(calificaciones)}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)