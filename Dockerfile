# ==============================================================================
# Tenders.tn - Dockerfile Production
# ==============================================================================
FROM python:3.12-slim

WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY . .

# Supprimer les fichiers sensibles (doivent venir des variables d'env)
RUN rm -f .env serviceAccountKey.json whatsapp_config.json telegram_config.json

# Créer un utilisateur non-root
RUN useradd -m -s /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

# Créer les répertoires nécessaires
RUN mkdir -p /app/data /app/uploads /app/logs

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
