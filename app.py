from flask import Flask, request, jsonify
import boto3
import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

app = Flask(__name__)

# Configuration Storj depuis variables d'environnement
ACCESS_KEY = os.getenv("STORJ_S3_ACCESS_KEY")
SECRET_KEY = os.getenv("STORJ_S3_SECRET_KEY")
ENDPOINT = os.getenv("STORJ_S3_ENDPOINT")
BUCKET = os.getenv("STORJ_S3_BUCKET")
BACKEND_TOKEN = os.getenv("BACKEND_TOKEN")

# Initialiser le client S3
session = boto3.session.Session()
s3 = session.client(
    service_name="s3",
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    endpoint_url=ENDPOINT
)


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


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)