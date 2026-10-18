"""
Configuration centralisée Tenders.tn
Charge les variables d'environnement et fournit des valeurs par défaut sécurisées.
"""
import os
from functools import lru_cache


class Settings:
    """Configuration centralisée de la plateforme Tenders.tn."""

    def __init__(self):
        # ---- Environnement ----
        self.ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
        self.DEBUG: bool = self.ENVIRONMENT == "development"
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

        # ---- Serveur ----
        self.APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")
        self.ALLOWED_ORIGINS: list = [
            o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
        ]

        # ---- WhatsApp Meta Cloud API ----
        self.META_PHONE_NUMBER_ID: str = os.getenv("META_PHONE_NUMBER_ID", "")
        self.META_ACCESS_TOKEN: str = os.getenv("META_ACCESS_TOKEN", "")
        self.WHATSAPP_PROVIDER: str = os.getenv("WHATSAPP_PROVIDER", "meta")
        self.META_VERIFY_TOKEN: str = os.getenv("META_VERIFY_TOKEN", "")

        # ---- Green API (fallback) ----
        self.GREEN_API_INSTANCE_ID: str = os.getenv("GREEN_API_INSTANCE_ID", "")
        self.GREEN_API_TOKEN: str = os.getenv("GREEN_API_TOKEN", "")

        # ---- Paiement ----
        self.KONNECT_API_KEY: str = os.getenv("KONNECT_API_KEY", "test_key_sample")
        self.KONNECT_WALLET_ID: str = os.getenv("KONNECT_WALLET_ID", "sample_wallet")

        # ---- Planification ----
        self.SYNC_INTERVAL_MINUTES: int = int(os.getenv("SYNC_INTERVAL_MINUTES", "30"))
        self.MORNING_BRIEFING_HOUR: int = int(os.getenv("MORNING_BRIEFING_HOUR", "8"))

        # ---- Sécurité ----
        self.ADMIN_SECRET_KEY: str = os.getenv("ADMIN_SECRET_KEY", "dev-admin-key-change-me")
        self.JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-jwt-key-change-me")

        # ---- Base de données ----
        self.DB_PATH: str = os.getenv("DB_PATH", "tenders.db")

    @property
    def is_production(self) -> bool:
        """Retourne True si l'environnement est en production."""
        return self.ENVIRONMENT == "production"

    def __repr__(self) -> str:
        return (
            f"Settings(ENVIRONMENT={self.ENVIRONMENT}, "
            f"APP_BASE_URL={self.APP_BASE_URL}, "
            f"DB_PATH={self.DB_PATH})"
        )


@lru_cache()
def get_settings() -> Settings:
    """Retourne l'instance singleton de la configuration."""
    return Settings()
