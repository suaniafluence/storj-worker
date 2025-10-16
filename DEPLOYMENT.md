# Déploiement sur AWS EC2

Ce guide explique comment déployer l'application Storj Worker sur un serveur EC2 Amazon.

## Prérequis

- Un compte AWS
- Une instance EC2 (Ubuntu 20.04 ou supérieur recommandé)
- Accès SSH à l'instance
- Python 3.8+ installé sur l'instance

## Étape 1 : Préparer l'instance EC2

### Créer une instance EC2

1. Connectez-vous à la console AWS EC2
2. Cliquez sur "Launch Instance"
3. Choisissez une AMI Ubuntu Server 20.04 LTS ou supérieur
4. Sélectionnez un type d'instance (t2.micro pour le free tier)
5. Configurez le Security Group :
   - SSH (port 22) : votre IP
   - HTTP (port 80) : 0.0.0.0/0
   - Custom TCP (port 5000) : 0.0.0.0/0 (ou configurez avec un reverse proxy)
6. Téléchargez la clé SSH (.pem)

### Connexion SSH

```bash
chmod 400 votre-cle.pem
ssh -i votre-cle.pem ubuntu@<IP-PUBLIQUE-EC2>
```

## Étape 2 : Installation des dépendances sur EC2

```bash
# Mettre à jour le système
sudo apt update && sudo apt upgrade -y

# Installer Python et pip
sudo apt install python3 python3-pip python3-venv git -y

# Installer nginx (optionnel, pour reverse proxy)
sudo apt install nginx -y
```

## Étape 3 : Cloner le projet

```bash
# Cloner depuis GitHub
git clone https://github.com/suaniafluence/storj-worker.git
cd storj-worker
```

## Étape 4 : Configuration de l'environnement

```bash
# Créer un environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

## Étape 5 : Configurer les variables d'environnement

```bash
# Créer le fichier .env
nano .env
```

Ajoutez vos credentials :

```
STORJ_S3_ACCESS_KEY=votre_access_key
STORJ_S3_SECRET_KEY=votre_secret_key
STORJ_S3_ENDPOINT=https://gateway.storjshare.io
STORJ_S3_BUCKET=votre_bucket
BACKEND_TOKEN=votre_token_secret
PORT=5000
```

## Étape 6 : Test de l'application

```bash
# Démarrer l'application en mode test
python app.py
```

Testez depuis votre machine locale :
```bash
curl http://<IP-PUBLIQUE-EC2>:5000/health
```

## Étape 7 : Déploiement en production avec Gunicorn

### Option A : Lancement manuel avec Gunicorn

```bash
# Démarrer avec Gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 4 app:app
```

### Option B : Créer un service systemd (recommandé)

Créer le fichier de service :

```bash
sudo nano /etc/systemd/system/storj-worker.service
```

Contenu du fichier :

```ini
[Unit]
Description=Storj Worker Flask Application
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/storj-worker
Environment="PATH=/home/ubuntu/storj-worker/venv/bin"
ExecStart=/home/ubuntu/storj-worker/venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 4 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Activer et démarrer le service :

```bash
sudo systemctl daemon-reload
sudo systemctl enable storj-worker
sudo systemctl start storj-worker
sudo systemctl status storj-worker
```

Commandes utiles :

```bash
# Redémarrer le service
sudo systemctl restart storj-worker

# Voir les logs
sudo journalctl -u storj-worker -f

# Arrêter le service
sudo systemctl stop storj-worker
```

## Étape 8 : Configuration Nginx (Optionnel mais recommandé)

Créer la configuration Nginx :

```bash
sudo nano /etc/nginx/sites-available/storj-worker
```

Contenu :

```nginx
server {
    listen 80;
    server_name <IP-PUBLIQUE-EC2>;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Activer la configuration :

```bash
sudo ln -s /etc/nginx/sites-available/storj-worker /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Maintenant l'application est accessible via :
```
http://<IP-PUBLIQUE-EC2>/health
```

## Étape 9 : Sécurisation avec SSL (Optionnel)

```bash
# Installer Certbot
sudo apt install certbot python3-certbot-nginx -y

# Obtenir un certificat SSL (nécessite un nom de domaine)
sudo certbot --nginx -d votre-domaine.com
```

## Mise à jour de l'application

```bash
cd /home/ubuntu/storj-worker
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart storj-worker
```

## Surveillance et logs

```bash
# Logs de l'application
sudo journalctl -u storj-worker -f

# Logs Nginx
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Status du service
sudo systemctl status storj-worker
```

## Endpoints disponibles

- `GET /health` - Health check
- `GET /listNotes` - Liste tous les fichiers (authentification requise)
- `POST /readNote` - Lit un fichier (authentification requise)
- `POST /writeNote` - Écrit un fichier (authentification requise)

## Authentification

Pour les endpoints protégés, ajoutez le header :
```
Authorization: Bearer votre_token_secret
```

Exemple :
```bash
curl -H "Authorization: Bearer votre_token_secret" http://<IP-PUBLIQUE-EC2>/listNotes
```
