from flask import Flask, request, jsonify, send_from_directory, g
import boto3
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from flask_swagger_ui import get_swaggerui_blueprint

# Charger les variables d'environnement depuis .env
load_dotenv()

app = Flask(__name__)

# Configuration Storj depuis variables d'environnement
ACCESS_KEY = os.getenv("STORJ_S3_ACCESS_KEY")
SECRET_KEY = os.getenv("STORJ_S3_SECRET_KEY")
ENDPOINT = os.getenv("STORJ_S3_ENDPOINT")
BUCKET = os.getenv("STORJ_S3_BUCKET")
BACKEND_TOKEN = os.getenv("BACKEND_TOKEN")

# Statistiques de bande passante
bandwidth_stats = {
    "total_bytes_sent": 0,
    "total_bytes_received": 0,
    "total_requests": 0,
    "start_time": datetime.utcnow().isoformat(),
    "endpoints": {}
}

# Initialiser le client S3
session = boto3.session.Session()
s3 = session.client(
    service_name="s3",
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    endpoint_url=ENDPOINT
)


# Configuration Swagger UI
SWAGGER_URL = '/api/docs'
API_URL = '/openapi.yaml'

swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={
        'app_name': "Storj Worker API"
    }
)

app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)


# Route pour servir le fichier OpenAPI
@app.route('/openapi.yaml')
def openapi_spec():
    return send_from_directory('.', 'openapi.yaml')


# Middleware de suivi de bande passante
@app.before_request
def track_bandwidth_before():
    g.start_time = time.time()
    # Comptabiliser les octets reçus (requête entrante)
    if request.data:
        bytes_received = len(request.data)
        bandwidth_stats["total_bytes_received"] += bytes_received
    elif request.form:
        bytes_received = len(str(request.form).encode('utf-8'))
        bandwidth_stats["total_bytes_received"] += bytes_received


@app.after_request
def track_bandwidth_after(response):
    # Comptabiliser les octets envoyés (réponse sortante)
    if response.data:
        bytes_sent = len(response.data)
        bandwidth_stats["total_bytes_sent"] += bytes_sent

    # Incrémenter le compteur de requêtes
    bandwidth_stats["total_requests"] += 1

    # Statistiques par endpoint
    endpoint = request.endpoint or "unknown"
    if endpoint not in bandwidth_stats["endpoints"]:
        bandwidth_stats["endpoints"][endpoint] = {
            "requests": 0,
            "bytes_sent": 0,
            "bytes_received": 0
        }

    bandwidth_stats["endpoints"][endpoint]["requests"] += 1
    if response.data:
        bandwidth_stats["endpoints"][endpoint]["bytes_sent"] += len(response.data)
    if request.data:
        bandwidth_stats["endpoints"][endpoint]["bytes_received"] += len(request.data)

    return response


# Middleware d'authentification
def check_auth():
    if BACKEND_TOKEN:
        auth = request.headers.get("Authorization")
        if auth != f"Bearer {BACKEND_TOKEN}":
            return jsonify({"error": "Unauthorized"}), 401
    return None


@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    return jsonify({
        "ok": True,
        "bucket": BUCKET,
        "endpoint": ENDPOINT
    })


@app.route("/stats", methods=["GET"])
def get_stats():
    """Retourne les statistiques de bande passante"""
    auth_error = check_auth()
    if auth_error:
        return auth_error

    # Calculer la durée de fonctionnement
    start_time = datetime.fromisoformat(bandwidth_stats["start_time"])
    uptime_seconds = (datetime.utcnow() - start_time).total_seconds()

    # Formater les statistiques
    stats = {
        "bandwidth": {
            "total_bytes_sent": bandwidth_stats["total_bytes_sent"],
            "total_bytes_received": bandwidth_stats["total_bytes_received"],
            "total_bytes": bandwidth_stats["total_bytes_sent"] + bandwidth_stats["total_bytes_received"],
            "total_mb_sent": round(bandwidth_stats["total_bytes_sent"] / (1024 * 1024), 2),
            "total_mb_received": round(bandwidth_stats["total_bytes_received"] / (1024 * 1024), 2),
            "total_mb": round((bandwidth_stats["total_bytes_sent"] + bandwidth_stats["total_bytes_received"]) / (1024 * 1024), 2)
        },
        "requests": {
            "total": bandwidth_stats["total_requests"],
            "by_endpoint": {}
        },
        "uptime": {
            "seconds": round(uptime_seconds, 2),
            "formatted": f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m {int(uptime_seconds % 60)}s"
        },
        "start_time": bandwidth_stats["start_time"],
        "current_time": datetime.utcnow().isoformat()
    }

    # Statistiques par endpoint
    for endpoint, data in bandwidth_stats["endpoints"].items():
        stats["requests"]["by_endpoint"][endpoint] = {
            "requests": data["requests"],
            "bytes_sent": data["bytes_sent"],
            "bytes_received": data["bytes_received"],
            "kb_sent": round(data["bytes_sent"] / 1024, 2),
            "kb_received": round(data["bytes_received"] / 1024, 2)
        }

    return jsonify(stats)


@app.route("/listNotes", methods=["GET"])
def list_notes():
    """Liste tous les fichiers du bucket"""
    auth_error = check_auth()
    if auth_error:
        return auth_error
    
    try:
        response = s3.list_objects_v2(Bucket=BUCKET)
        files = [obj["Key"] for obj in response.get("Contents", [])]
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/readNote", methods=["POST"])
def read_note():
    """Lit le contenu d'un fichier"""
    auth_error = check_auth()
    if auth_error:
        return auth_error
    
    data = request.get_json()
    filename = data.get("filename")
    
    if not filename:
        return jsonify({"error": "Missing filename"}), 400
    
    try:
        response = s3.get_object(Bucket=BUCKET, Key=filename)
        content = response["Body"].read().decode("utf-8")
        return jsonify({
            "filename": filename,
            "content": content
        })
    except s3.exceptions.NoSuchKey:
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/writeNote", methods=["POST"])
def write_note():
    """Écrit ou met à jour un fichier"""
    auth_error = check_auth()
    if auth_error:
        return auth_error

    data = request.get_json()
    filename = data.get("filename")
    content = data.get("content", "")

    if not filename:
        return jsonify({"error": "Missing filename"}), 400

    try:
        s3.put_object(
            Bucket=BUCKET,
            Key=filename,
            Body=content.encode("utf-8")
        )
        return jsonify({
            "success": True,
            "message": f"{filename} uploaded"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========== CRUD CANVAS ==========

@app.route("/canvas", methods=["GET"])
def list_canvas():
    """Liste tous les fichiers .canvas"""
    auth_error = check_auth()
    if auth_error:
        return auth_error

    try:
        response = s3.list_objects_v2(Bucket=BUCKET)
        canvas_files = [
            obj["Key"] for obj in response.get("Contents", [])
            if obj["Key"].endswith(".canvas")
        ]
        return jsonify({
            "count": len(canvas_files),
            "files": canvas_files
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/canvas/<path:filename>", methods=["GET"])
def get_canvas(filename):
    """Récupère un fichier .canvas spécifique"""
    auth_error = check_auth()
    if auth_error:
        return auth_error

    # Ajouter l'extension .canvas si elle n'est pas présente
    if not filename.endswith(".canvas"):
        filename = f"{filename}.canvas"

    try:
        response = s3.get_object(Bucket=BUCKET, Key=filename)
        content = response["Body"].read().decode("utf-8")

        # Tenter de parser le JSON pour validation
        import json
        try:
            canvas_data = json.loads(content)
        except json.JSONDecodeError:
            canvas_data = content

        return jsonify({
            "filename": filename,
            "content": canvas_data,
            "size": len(content),
            "last_modified": response["LastModified"].isoformat()
        })
    except s3.exceptions.NoSuchKey:
        return jsonify({"error": f"Canvas file '{filename}' not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/canvas", methods=["POST"])
def create_canvas():
    """Crée un nouveau fichier .canvas"""
    auth_error = check_auth()
    if auth_error:
        return auth_error

    data = request.get_json()
    filename = data.get("filename")
    content = data.get("content")

    if not filename:
        return jsonify({"error": "Missing filename"}), 400

    if not content:
        return jsonify({"error": "Missing content"}), 400

    # Ajouter l'extension .canvas si elle n'est pas présente
    if not filename.endswith(".canvas"):
        filename = f"{filename}.canvas"

    try:
        # Vérifier si le fichier existe déjà
        try:
            s3.head_object(Bucket=BUCKET, Key=filename)
            return jsonify({"error": f"Canvas file '{filename}' already exists"}), 409
        except s3.exceptions.ClientError:
            pass

        # Convertir en JSON si c'est un dict/list
        import json
        if isinstance(content, (dict, list)):
            content_str = json.dumps(content, indent=2, ensure_ascii=False)
        else:
            content_str = str(content)

        s3.put_object(
            Bucket=BUCKET,
            Key=filename,
            Body=content_str.encode("utf-8"),
            ContentType="application/json"
        )

        return jsonify({
            "success": True,
            "message": f"Canvas '{filename}' created successfully",
            "filename": filename
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/canvas/<path:filename>", methods=["PUT"])
def update_canvas(filename):
    """Met à jour un fichier .canvas existant"""
    auth_error = check_auth()
    if auth_error:
        return auth_error

    data = request.get_json()
    content = data.get("content")

    if not content:
        return jsonify({"error": "Missing content"}), 400

    # Ajouter l'extension .canvas si elle n'est pas présente
    if not filename.endswith(".canvas"):
        filename = f"{filename}.canvas"

    try:
        # Vérifier si le fichier existe
        try:
            s3.head_object(Bucket=BUCKET, Key=filename)
        except s3.exceptions.ClientError:
            return jsonify({"error": f"Canvas file '{filename}' not found"}), 404

        # Convertir en JSON si c'est un dict/list
        import json
        if isinstance(content, (dict, list)):
            content_str = json.dumps(content, indent=2, ensure_ascii=False)
        else:
            content_str = str(content)

        s3.put_object(
            Bucket=BUCKET,
            Key=filename,
            Body=content_str.encode("utf-8"),
            ContentType="application/json"
        )

        return jsonify({
            "success": True,
            "message": f"Canvas '{filename}' updated successfully",
            "filename": filename
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/canvas/<path:filename>", methods=["DELETE"])
def delete_canvas(filename):
    """Supprime un fichier .canvas"""
    auth_error = check_auth()
    if auth_error:
        return auth_error

    # Ajouter l'extension .canvas si elle n'est pas présente
    if not filename.endswith(".canvas"):
        filename = f"{filename}.canvas"

    try:
        # Vérifier si le fichier existe
        try:
            s3.head_object(Bucket=BUCKET, Key=filename)
        except s3.exceptions.ClientError:
            return jsonify({"error": f"Canvas file '{filename}' not found"}), 404

        s3.delete_object(Bucket=BUCKET, Key=filename)

        return jsonify({
            "success": True,
            "message": f"Canvas '{filename}' deleted successfully",
            "filename": filename
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)