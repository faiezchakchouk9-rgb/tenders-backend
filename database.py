"""
Modèle de données et schéma SQLite pour les Appels d'Offres Tunisiens.
Gère :
- Le stockage & la déduplication des marchés TUNEPS
- L'ingestion des critères détaillés (Moins disant, cautionnement, CDC, ouverture)
- L'enrichissement sémantique par IA
- L'indexation plein texte SQLite FTS5 (recherche instantanée bilingue < 5ms)
- Les profils des abonnés et l'historique d'envoi
"""
import sqlite3
import json
import logging
import hashlib
import secrets
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("TenderDatabase")

def hash_password(password: str) -> str:
    """Hache de manière sécurisée un mot de passe via PBKDF2-HMAC-SHA256 avec sel aléatoire."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}:{h.hex()}"

def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    """Vérifie un mot de passe contre son hash PBKDF2."""
    if not stored_hash or ":" not in stored_hash:
        return False
    try:
        salt, h = stored_hash.split(":", 1)
        test_h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return secrets.compare_digest(h, test_h.hex())
    except Exception:
        return False


@dataclass
class TenderNotice:
    ep_bid_master_id: int
    bid_no: str
    bid_mod_seq: str
    title_fr: Optional[str]
    title_ar: Optional[str]
    buyer_name: str
    publication_date: Optional[str]
    deadline_date: Optional[str]
    procedure_type: Optional[str]
    url: str
    raw_json: str
    created_at: str = ""
    is_notified: int = 0
    # Champs enrichis par l'IA
    category: Optional[str] = None
    tags: Optional[str] = None  # JSON string
    governorate: Optional[str] = None
    ai_summary: Optional[str] = None
    is_enriched: int = 0
    # Métadonnées détaillées TUNEPS-3
    eval_method: Optional[str] = None      # ex: "Moins disant"
    guarantee_type: Optional[str] = None   # ex: "Cautionnement"
    doc_price: Optional[str] = None        # ex: "0 TND" ou "Gratuit"
    execution_place: Optional[str] = None  # ex: "TUNIS", "SOUSSE"
    opening_date: Optional[str] = None     # ex: "2026-11-16 17:30:00.0"
    is_online: Optional[str] = None        # ex: "En ligne"

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()

@dataclass
class Subscriber:
    company_name: str
    phone: str
    email: str
    categories: List[str]      # ex: ["IT_TELECOM"]
    governorates: List[str]    # ex: ["Tunis", "National"] ou ["ALL"]
    keywords: List[str]        # ex: ["caméra", "firewall"] ou []
    channel: str = "WHATSAPP"  # "WHATSAPP", "EMAIL", "BOTH"
    plan: str = "PRO"          # "STARTER", "PRO", "TRIAL"
    is_active: int = 1
    features: Optional[Dict[str, bool]] = None
    logo_url: Optional[str] = None
    rne_id: Optional[str] = None
    address: Optional[str] = None
    phone_office: Optional[str] = None
    bank_name: Optional[str] = None
    rib: Optional[str] = None
    monthly_pack_quota: Optional[int] = None
    password_hash: Optional[str] = None
    id: Optional[int] = None
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        if self.features is None:
            self.features = {
                "tech_proposal": True,
                "commercial_bpu": True,
                "clarification": True,
                "scoring_simulation": True,
                "submission_pack_zip": True,
                "checklist_admin": True,
                "printable_pdf": True
            }
        if self.monthly_pack_quota is None:
            self.monthly_pack_quota = 3 if self.plan == "TRIAL" else (10 if self.plan == "STARTER" else 100)

class TenderDatabase:
    def __init__(self, db_path: str = "tenders.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Mode WAL pour accès concurrent (scheduler thread + requêtes web)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Table principale des marchés publics
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenders (
                ep_bid_master_id INTEGER PRIMARY KEY,
                bid_no TEXT NOT NULL UNIQUE,
                bid_mod_seq TEXT,
                title_fr TEXT,
                title_ar TEXT,
                buyer_name TEXT,
                publication_date TEXT,
                deadline_date TEXT,
                procedure_type TEXT,
                url TEXT,
                raw_json TEXT,
                created_at TEXT,
                is_notified INTEGER DEFAULT 0,
                category TEXT,
                tags TEXT,
                governorate TEXT,
                ai_summary TEXT,
                is_enriched INTEGER DEFAULT 0,
                eval_method TEXT,
                guarantee_type TEXT,
                doc_price TEXT,
                execution_place TEXT,
                opening_date TEXT,
                is_online TEXT
            )
            """)

            # Migrations automatiques pour les colonnes existantes
            existing_cols = [c[1] for c in cursor.execute("PRAGMA table_info(tenders)").fetchall()]
            new_columns = [
                ("category", "TEXT"),
                ("tags", "TEXT"),
                ("governorate", "TEXT"),
                ("ai_summary", "TEXT"),
                ("is_enriched", "INTEGER DEFAULT 0"),
                ("eval_method", "TEXT"),
                ("guarantee_type", "TEXT"),
                ("doc_price", "TEXT"),
                ("execution_place", "TEXT"),
                ("opening_date", "TEXT"),
                ("is_online", "TEXT")
            ]
            for col_name, col_type in new_columns:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE tenders ADD COLUMN {col_name} {col_type}")

            # Index standard haute performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenders_pub_dt ON tenders(publication_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenders_deadline ON tenders(deadline_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenders_notified ON tenders(is_notified)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenders_category ON tenders(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenders_gov ON tenders(governorate)")

            # Table des Abonnés (Clients)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                categories TEXT NOT NULL,
                governorates TEXT NOT NULL,
                keywords TEXT DEFAULT '[]',
                channel TEXT DEFAULT 'WHATSAPP',
                plan TEXT DEFAULT 'PRO',
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            )
            """)

            # Migrations pour colonnes abonnés (branding, quotas, features)
            sub_cols = [c[1] for c in cursor.execute("PRAGMA table_info(subscribers)").fetchall()]
            new_sub_cols = [
                ("features", "TEXT"),
                ("logo_url", "TEXT"),
                ("rne_id", "TEXT"),
                ("address", "TEXT"),
                ("phone_office", "TEXT"),
                ("bank_name", "TEXT"),
                ("rib", "TEXT"),
                ("monthly_pack_quota", "INTEGER"),
                ("password_hash", "TEXT")
            ]
            for col_name, col_type in new_sub_cols:
                if col_name not in sub_cols:
                    cursor.execute(f"ALTER TABLE subscribers ADD COLUMN {col_name} {col_type}")

            # Table des Logs de Notifications envoyées
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tender_id INTEGER NOT NULL,
                subscriber_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (tender_id) REFERENCES tenders (ep_bid_master_id),
                FOREIGN KEY (subscriber_id) REFERENCES subscribers (id)
            )
            """)

            # Table des Favoris & Dossiers de Candidature (Dashboard Client Privé)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS client_bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id INTEGER NOT NULL,
                tender_id INTEGER NOT NULL,
                status TEXT DEFAULT 'A_ETUDIER',
                notes TEXT DEFAULT '',
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(subscriber_id, tender_id),
                FOREIGN KEY (subscriber_id) REFERENCES subscribers (id),
                FOREIGN KEY (tender_id) REFERENCES tenders (ep_bid_master_id)
            )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_sub ON client_bookmarks(subscriber_id)")

            # Table de Suivi des Dossiers de Soumission Générés ("Mes Dossiers")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS submission_dossiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id INTEGER NOT NULL,
                tender_id INTEGER NOT NULL,
                created_at TEXT,
                files_included TEXT,
                format_type TEXT DEFAULT 'DOCX',
                total_price REAL DEFAULT 0.0,
                status TEXT DEFAULT 'PREPARATION',
                notes TEXT DEFAULT '',
                FOREIGN KEY (subscriber_id) REFERENCES subscribers (id),
                FOREIGN KEY (tender_id) REFERENCES tenders (ep_bid_master_id)
            )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_dossiers_sub ON submission_dossiers(subscriber_id)")

            # Table de Suivi des Quotas Mensuels SaaS
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS monthly_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id INTEGER NOT NULL,
                year_month TEXT NOT NULL,
                packs_count INTEGER DEFAULT 0,
                updated_at TEXT,
                UNIQUE(subscriber_id, year_month),
                FOREIGN KEY (subscriber_id) REFERENCES subscribers (id)
            )
            """)

            # Table des Transactions de Paiement (Flouci, Konnect, Simulation)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id INTEGER NOT NULL,
                gateway TEXT NOT NULL,
                amount_tnd REAL NOT NULL,
                plan TEXT NOT NULL,
                payment_ref TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'PENDING',
                created_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (subscriber_id) REFERENCES subscribers (id)
            )
            """)

            # Table des OTP de Réinitialisation de Mot de Passe WhatsApp
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_otps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                otp_code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                is_used INTEGER DEFAULT 0,
                created_at TEXT,
                FOREIGN KEY (subscriber_id) REFERENCES subscribers (id)
            )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reset_otps_sub ON password_reset_otps(subscriber_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reset_otps_phone ON password_reset_otps(phone)")

            # Initialisation Table Virtuelle FTS5 pour recherche plein texte
            try:
                # Si besoin de mise à jour des colonnes FTS
                cols = [row[1] for row in cursor.execute("PRAGMA table_info(tenders_fts)").fetchall()]
                if cols and "eval_method" not in cols:
                    cursor.execute("DROP TABLE IF EXISTS tenders_fts")
                cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS tenders_fts USING fts5(
                    ep_bid_master_id UNINDEXED,
                    title_fr,
                    title_ar,
                    buyer_name,
                    tags,
                    ai_summary,
                    execution_place,
                    eval_method,
                    guarantee_type,
                    procedure_type
                )
                """)
            except Exception as e:
                logger.warning(f"FTS5 setup note: {e}")

            conn.commit()

        # Synchroniser l'index FTS5
        self.rebuild_fts()

    def rebuild_fts(self):
        """Met à jour l'index FTS5 avec les données de la table tenders."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM tenders_fts")
                cursor.execute("""
                INSERT INTO tenders_fts (
                    ep_bid_master_id, title_fr, title_ar, buyer_name, 
                    tags, ai_summary, execution_place, eval_method, guarantee_type, procedure_type
                )
                SELECT ep_bid_master_id, 
                       COALESCE(title_fr, ''), 
                       COALESCE(title_ar, ''), 
                       COALESCE(buyer_name, ''), 
                       COALESCE(tags, ''), 
                       COALESCE(ai_summary, ''), 
                       COALESCE(execution_place, ''),
                       COALESCE(eval_method, ''),
                       COALESCE(guarantee_type, ''),
                       COALESCE(procedure_type, '')
                FROM tenders
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"Rebuild FTS exception: {e}")

    def save_tender(self, tender: TenderNotice) -> bool:
        """
        Insère ou met à jour si déjà existant.
        Retourne True si un nouvel enregistrement a été créé.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO tenders (
                ep_bid_master_id, bid_no, bid_mod_seq, title_fr, title_ar,
                buyer_name, publication_date, deadline_date, procedure_type,
                url, raw_json, created_at, is_notified,
                category, tags, governorate, ai_summary, is_enriched,
                eval_method, guarantee_type, doc_price, execution_place,
                opening_date, is_online
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ep_bid_master_id) DO UPDATE SET
                deadline_date = excluded.deadline_date,
                eval_method = COALESCE(excluded.eval_method, tenders.eval_method),
                guarantee_type = COALESCE(excluded.guarantee_type, tenders.guarantee_type),
                doc_price = COALESCE(excluded.doc_price, tenders.doc_price),
                execution_place = COALESCE(excluded.execution_place, tenders.execution_place),
                opening_date = COALESCE(excluded.opening_date, tenders.opening_date),
                is_online = COALESCE(excluded.is_online, tenders.is_online)
            """, (
                tender.ep_bid_master_id,
                tender.bid_no,
                tender.bid_mod_seq,
                tender.title_fr,
                tender.title_ar,
                tender.buyer_name,
                tender.publication_date,
                tender.deadline_date,
                tender.procedure_type,
                tender.url,
                tender.raw_json,
                tender.created_at,
                tender.is_notified,
                tender.category,
                tender.tags,
                tender.governorate,
                tender.ai_summary,
                tender.is_enriched,
                tender.eval_method,
                tender.guarantee_type,
                tender.doc_price,
                tender.execution_place,
                tender.opening_date,
                tender.is_online
            ))
            is_new = cursor.rowcount > 0 and cursor.lastrowid == tender.ep_bid_master_id
            conn.commit()

            # Mettre à jour l'index FTS5 pour cet appel d'offres
            try:
                conn.execute("DELETE FROM tenders_fts WHERE ep_bid_master_id = ?", (tender.ep_bid_master_id,))
                conn.execute("""
                INSERT INTO tenders_fts (ep_bid_master_id, title_fr, title_ar, buyer_name, tags, ai_summary, execution_place)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    tender.ep_bid_master_id,
                    tender.title_fr or "",
                    tender.title_ar or "",
                    tender.buyer_name or "",
                    tender.tags or "",
                    tender.ai_summary or "",
                    tender.execution_place or ""
                ))
                conn.commit()
            except Exception:
                pass

            return is_new

    def search_tenders(
        self,
        query: str = "",
        category: str = "",
        governorate: str = "",
        only_open: bool = True,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Moteur de recherche hybride haute performance (FTS5 + filtres relationnels).
        Exécute la requête en < 5ms.
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        where_clauses = []
        params = []

        # 1. Filtre marché ouvert
        if only_open:
            where_clauses.append("t.deadline_date >= ?")
            params.append(now_str)

        # 2. Filtre secteur
        if category and category != "ALL":
            where_clauses.append("t.category = ?")
            params.append(category)

        # 3. Filtre région / gouvernorat
        if governorate and governorate != "ALL":
            where_clauses.append("(t.governorate = ? OR t.execution_place = ? OR t.governorate LIKE ?)")
            params.extend([governorate, governorate, f"%{governorate}%"])

        # 4. Requête texte (FTS5 ou LIKE fallback)
        join_fts = ""
        clean_query = query.strip()
        if clean_query:
            # Nettoyer pour FTS5
            fts_query = "".join([c for c in clean_query if c.isalnum() or c.isspace() or ord(c) > 127]).strip()
            if fts_query:
                # Utiliser FTS5
                join_fts = "JOIN tenders_fts fts ON fts.ep_bid_master_id = t.ep_bid_master_id"
                where_clauses.append("tenders_fts MATCH ?")
                # Format FTS5 wildcard pour chaque mot
                fts_terms = " ".join([f"{term}*" for term in fts_query.split() if term])
                params.append(fts_terms)
            else:
                where_clauses.append("(t.title_fr LIKE ? OR t.title_ar LIKE ? OR t.buyer_name LIKE ?)")
                like_term = f"%{clean_query}%"
                params.extend([like_term, like_term, like_term])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Compter le total
            count_query = f"SELECT COUNT(*) FROM tenders t {join_fts} {where_sql}"
            try:
                total = cursor.execute(count_query, params).fetchone()[0]
            except Exception:
                # Si erreur de syntaxe FTS, fallback sur LIKE
                join_fts = ""
                where_clauses = [c for c in where_clauses if "MATCH" not in c]
                if clean_query:
                    where_clauses.append("(t.title_fr LIKE ? OR t.title_ar LIKE ? OR t.buyer_name LIKE ?)")
                    params = [p for p in params if "*" not in str(p)]
                    like_term = f"%{clean_query}%"
                    params.append(like_term)
                    params.append(like_term)
                    params.append(like_term)
                where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                total = cursor.execute(f"SELECT COUNT(*) FROM tenders t {where_sql}", params).fetchone()[0]

            # Récupérer les données paginées
            select_sql = f"""
            SELECT t.* FROM tenders t {join_fts} {where_sql}
            ORDER BY t.publication_date DESC
            LIMIT ? OFFSET ?
            """
            rows = cursor.execute(select_sql, params + [limit, offset]).fetchall()
            tenders = [TenderNotice(**dict(r)) for r in rows]

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "tenders": tenders
            }

    def get_tender_by_id(self, ep_bid_master_id: int) -> Optional[Dict[str, Any]]:
        """Récupère l'intégralité des données et métadonnées d'un appel d'offres."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tenders WHERE ep_bid_master_id = ?", (ep_bid_master_id,))
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            if data.get("tags"):
                try:
                    data["tags"] = json.loads(data["tags"])
                except Exception:
                    data["tags"] = []
            if data.get("raw_json"):
                try:
                    data["raw_details"] = json.loads(data["raw_json"])
                except Exception:
                    data["raw_details"] = {}
            data["countdown"] = self._calculate_countdown(data.get("deadline_date") or "")
            return data

    def get_unenriched_tenders(self, limit: int = 50) -> List[TenderNotice]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM tenders WHERE is_enriched = 0 ORDER BY publication_date DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [TenderNotice(**dict(r)) for r in rows]

    def update_enrichment(self, ep_bid_master_id: int, category: str, tags: List[str], governorate: str, ai_summary: str):
        with self._get_connection() as conn:
            conn.execute("""
            UPDATE tenders 
            SET category = ?, tags = ?, governorate = ?, ai_summary = ?, is_enriched = 1
            WHERE ep_bid_master_id = ?
            """, (
                category,
                json.dumps(tags, ensure_ascii=False),
                governorate,
                ai_summary,
                ep_bid_master_id
            ))
            conn.commit()

            # Mettre à jour FTS
            try:
                conn.execute("""
                UPDATE tenders_fts SET tags = ?, ai_summary = ? WHERE ep_bid_master_id = ?
                """, (json.dumps(tags, ensure_ascii=False), ai_summary, ep_bid_master_id))
                conn.commit()
            except Exception:
                pass

    def get_unnotified_tenders(self, limit: int = 50) -> List[TenderNotice]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM tenders WHERE is_notified = 0 AND is_enriched = 1 ORDER BY publication_date DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [TenderNotice(**dict(r)) for r in rows]

    def mark_as_notified(self, ep_bid_master_id: int):
        with self._get_connection() as conn:
            conn.execute("UPDATE tenders SET is_notified = 1 WHERE ep_bid_master_id = ?", (ep_bid_master_id,))
            conn.commit()

    # --- Gestion des Abonnés ---

    def add_subscriber(self, sub: Subscriber) -> int:
        existing = self.get_subscriber_by_phone(sub.phone)
        if existing:
            # Mise à jour de l'abonné existant pour éviter les doublons
            self.update_subscriber_profile(
                sub_id=existing.id,
                company_name=sub.company_name or existing.company_name,
                email=sub.email or existing.email,
                categories=sub.categories,
                governorates=sub.governorates,
                keywords=sub.keywords,
                channel=sub.channel
            )
            return existing.id

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO subscribers (
                company_name, phone, email, categories, governorates, keywords,
                channel, plan, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sub.company_name,
                sub.phone,
                sub.email,
                json.dumps(sub.categories, ensure_ascii=False),
                json.dumps(sub.governorates, ensure_ascii=False),
                json.dumps(sub.keywords, ensure_ascii=False),
                sub.channel,
                sub.plan,
                sub.is_active,
                sub.created_at
            ))
            conn.commit()
            return cursor.lastrowid

    def delete_subscriber(self, subscriber_id: int) -> bool:
        """Supprime un abonné ainsi que ses favoris et logs associés."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM client_bookmarks WHERE subscriber_id = ?", (subscriber_id,))
            cursor.execute("DELETE FROM notification_logs WHERE subscriber_id = ?", (subscriber_id,))
            cursor.execute("DELETE FROM subscribers WHERE id = ?", (subscriber_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_active_subscribers(self) -> List[Subscriber]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscribers WHERE is_active = 1")
            rows = cursor.fetchall()
            return [self._row_to_subscriber(r) for r in rows]

    def log_notification(self, tender_id: int, subscriber_id: int, channel: str, status: str = "SENT"):
        with self._get_connection() as conn:
            conn.execute("""
            INSERT INTO notification_logs (tender_id, subscriber_id, channel, sent_at, status)
            VALUES (?, ?, ?, ?, ?)
            """, (tender_id, subscriber_id, channel, datetime.utcnow().isoformat(), status))
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            total = cursor.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
            active_open = cursor.execute("SELECT COUNT(*) FROM tenders WHERE deadline_date >= ?", (now_str,)).fetchone()[0]
            enriched = cursor.execute("SELECT COUNT(*) FROM tenders WHERE is_enriched = 1").fetchone()[0]
            unnotified = cursor.execute("SELECT COUNT(*) FROM tenders WHERE is_notified = 0").fetchone()[0]
            subscribers = cursor.execute("SELECT COUNT(*) FROM subscribers WHERE is_active = 1").fetchone()[0]
            notif_logs = cursor.execute("SELECT COUNT(*) FROM notification_logs").fetchone()[0]
            return {
                "total_tenders": total,
                "active_open_tenders": active_open,
                "enriched": enriched,
                "pending_notifications": unnotified,
                "active_subscribers": subscribers,
                "notifications_sent": notif_logs
            }

    # --- Dashboard Client Privé & Pipeline de Candidatures ---

    def _row_to_subscriber(self, row) -> Subscriber:
        feat_dict = None
        if "features" in row.keys() and row["features"]:
            try:
                feat_dict = json.loads(row["features"])
            except Exception:
                feat_dict = None
        return Subscriber(
            id=row["id"],
            company_name=row["company_name"],
            phone=row["phone"],
            email=row["email"],
            categories=json.loads(row["categories"]) if row["categories"] else ["ALL"],
            governorates=json.loads(row["governorates"]) if row["governorates"] else ["ALL"],
            keywords=json.loads(row["keywords"]) if row["keywords"] else [],
            channel=row["channel"],
            plan=row["plan"],
            is_active=row["is_active"],
            features=feat_dict,
            logo_url=row["logo_url"] if "logo_url" in row.keys() else None,
            rne_id=row["rne_id"] if "rne_id" in row.keys() else None,
            address=row["address"] if "address" in row.keys() else None,
            phone_office=row["phone_office"] if "phone_office" in row.keys() else None,
            bank_name=row["bank_name"] if "bank_name" in row.keys() else None,
            rib=row["rib"] if "rib" in row.keys() else None,
            monthly_pack_quota=row["monthly_pack_quota"] if "monthly_pack_quota" in row.keys() else None,
            password_hash=row["password_hash"] if "password_hash" in row.keys() else None,
            created_at=row["created_at"]
        )

    def get_subscriber_by_phone(self, phone: str) -> Optional[Subscriber]:
        """Trouve un abonné à partir de son numéro de téléphone (tolère 28177888, +21628177888, etc.)."""
        clean_digits = "".join([c for c in phone if c.isdigit()])
        if not clean_digits:
            return None
        short_num = clean_digits[-8:] if len(clean_digits) >= 8 else clean_digits
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM subscribers 
            WHERE phone LIKE ? OR phone LIKE ? 
            ORDER BY 
                (CASE WHEN rne_id IS NOT NULL AND rne_id != '' THEN 0 ELSE 1 END),
                (CASE WHEN logo_url IS NOT NULL AND logo_url != '' THEN 0 ELSE 1 END),
                id ASC
            LIMIT 1
            """, (f"%{short_num}", f"+216{short_num}"))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_subscriber(row)

    def get_subscriber_by_id(self, sub_id: int) -> Optional[Subscriber]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscribers WHERE id = ?", (sub_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_subscriber(row)

    def update_subscriber_features(self, sub_id: int, features: Dict[str, bool]) -> bool:
        """Met à jour les permissions de fonctionnalités activées pour un abonné."""
        sub = self.get_subscriber_by_id(sub_id)
        if not sub:
            return False
        current_features = dict(sub.features or {})
        current_features.update(features)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE subscribers SET features = ? WHERE id = ?", (json.dumps(current_features), sub_id))
            conn.commit()
            return cursor.rowcount > 0

    def update_company_branding(
        self,
        sub_id: int,
        company_name: Optional[str] = None,
        logo_url: Optional[str] = None,
        rne_id: Optional[str] = None,
        address: Optional[str] = None,
        phone_office: Optional[str] = None,
        bank_name: Optional[str] = None,
        rib: Optional[str] = None
    ) -> bool:
        """Met à jour les éléments d'identité de marque et coordonnées officielles de l'entreprise."""
        updates = []
        params = []
        if company_name is not None:
            updates.append("company_name = ?")
            params.append(company_name.strip())
        if logo_url is not None:
            updates.append("logo_url = ?")
            params.append(logo_url.strip())
        if rne_id is not None:
            updates.append("rne_id = ?")
            params.append(rne_id.strip())
        if address is not None:
            updates.append("address = ?")
            params.append(address.strip())
        if phone_office is not None:
            updates.append("phone_office = ?")
            params.append(phone_office.strip())
        if bank_name is not None:
            updates.append("bank_name = ?")
            params.append(bank_name.strip())
        if rib is not None:
            updates.append("rib = ?")
            params.append(rib.strip())

        if not updates:
            return False

        params.append(sub_id)
        with self._get_connection() as conn:
            conn.execute(f"UPDATE subscribers SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            return True

    # --- Gestion des Dossiers de Soumission Historiques ---

    def record_submission_dossier(
        self,
        subscriber_id: int,
        tender_id: int,
        files_included: List[str],
        format_type: str = "DOCX",
        total_price: float = 0.0,
        status: str = "PREPARATION",
        notes: str = ""
    ) -> int:
        now_str = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO submission_dossiers (
                subscriber_id, tender_id, created_at, files_included, format_type, total_price, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                subscriber_id,
                tender_id,
                now_str,
                json.dumps(files_included, ensure_ascii=False),
                format_type,
                total_price,
                status,
                notes
            ))
            conn.commit()
            return cursor.lastrowid

    def get_subscriber_dossiers(self, subscriber_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT d.*, t.bid_no, t.buyer_name, t.title_fr, t.title_ar, t.deadline_date, t.guarantee_type, t.procedure_type
            FROM submission_dossiers d
            JOIN tenders t ON t.ep_bid_master_id = d.tender_id
            WHERE d.subscriber_id = ?
            ORDER BY d.id DESC
            """, (subscriber_id,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                it = dict(r)
                try:
                    it["files_included"] = json.loads(it.get("files_included") or "[]")
                except Exception:
                    it["files_included"] = []
                it["submission_status"] = it.get("status") or "GENERE"
                it["tender_title"] = it.get("title_fr") or it.get("title_ar") or "Appel d'offres"
                it["file_format"] = it.get("format_type") or "ZIP"
                it["files_count"] = len(it["files_included"]) if isinstance(it["files_included"], list) else 1
                results.append(it)
            return results

    def update_dossier_status(self, dossier_id: int, subscriber_id: int, new_status: str, notes: Optional[str] = None) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if notes is not None:
                cursor.execute("UPDATE submission_dossiers SET status = ?, notes = ? WHERE id = ? AND subscriber_id = ?", (new_status, notes, dossier_id, subscriber_id))
            else:
                cursor.execute("UPDATE submission_dossiers SET status = ? WHERE id = ? AND subscriber_id = ?", (new_status, dossier_id, subscriber_id))
            conn.commit()
            return cursor.rowcount > 0

    # --- Quotas Mensuels SaaS & Monétisation ---

    def get_subscriber_usage(self, subscriber_id: int) -> Dict[str, Any]:
        sub = self.get_subscriber_by_id(subscriber_id)
        if not sub:
            return {"used": 0, "quota": 100, "remaining": 100, "plan": "PRO"}
        quota = sub.monthly_pack_quota
        if quota is None:
            quota = 3 if sub.plan == "TRIAL" else (10 if sub.plan == "STARTER" else 100)
        current_month = datetime.now().strftime("%Y-%m")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT packs_count FROM monthly_usage WHERE subscriber_id = ? AND year_month = ?", (subscriber_id, current_month))
            row = cursor.fetchone()
            used = row[0] if row else 0
            return {
                "used": used,
                "quota": quota,
                "remaining": max(0, quota - used),
                "plan": sub.plan,
                "month": current_month
            }

    def check_and_record_usage(self, subscriber_id: int) -> Dict[str, Any]:
        usage = self.get_subscriber_usage(subscriber_id)
        if usage["used"] >= usage["quota"]:
            return {
                "allowed": False,
                "used": usage["used"],
                "quota": usage["quota"],
                "remaining": 0,
                "plan": usage["plan"],
                "message": f"Quota mensuel atteint ({usage['used']}/{usage['quota']} packs). Passez au plan supérieur !"
            }

        current_month = datetime.now().strftime("%Y-%m")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO monthly_usage (subscriber_id, year_month, packs_count, updated_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(subscriber_id, year_month) DO UPDATE SET
                packs_count = monthly_usage.packs_count + 1,
                updated_at = excluded.updated_at
            """, (subscriber_id, current_month, datetime.utcnow().isoformat()))
            conn.commit()

        new_used = usage["used"] + 1
        return {
            "allowed": True,
            "used": new_used,
            "quota": usage["quota"],
            "remaining": max(0, usage["quota"] - new_used),
            "plan": usage["plan"]
        }

    # --- Intelligence Acheteur & Marchés Récurrents ---

    def get_buyer_stats(self, buyer_name: str) -> Dict[str, Any]:
        if not buyer_name:
            return {"total_tenders": 0, "categories": [], "is_recurrent": False, "recurrence_label": "Premier avis répertorié"}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tenders WHERE buyer_name = ?", (buyer_name,))
            count = cursor.fetchone()[0]

            cursor.execute("""
            SELECT category, COUNT(*) as c FROM tenders 
            WHERE buyer_name = ? AND category IS NOT NULL AND category != ''
            GROUP BY category ORDER BY c DESC LIMIT 3
            """, (buyer_name,))
            cats = [{"category": r["category"], "count": r["c"]} for r in cursor.fetchall()]

            cursor.execute("""
            SELECT ep_bid_master_id, bid_no, title_fr, deadline_date FROM tenders 
            WHERE buyer_name = ? ORDER BY deadline_date DESC LIMIT 5
            """, (buyer_name,))
            other_tenders = [dict(r) for r in cursor.fetchall()]

            is_recurrent = count >= 2
            if count >= 8:
                rec_label = f"Grand Acheteur Récurrent ({count} avis publiés)"
                rec_level = "HIGH"
            elif count >= 3:
                rec_label = f"Acheteur Régulier ({count} avis publiés)"
                rec_level = "MEDIUM"
            elif count == 2:
                rec_label = "Acheteur Récurrent (2 avis identifiés)"
                rec_level = "LOW"
            else:
                rec_label = "Nouvel Acheteur (1er avis)"
                rec_level = "NEW"

            return {
                "buyer_name": buyer_name,
                "total_tenders": count,
                "categories": cats,
                "recent_tenders": other_tenders,
                "is_recurrent": is_recurrent,
                "recurrence_label": rec_label,
                "recurrence_level": rec_level
            }

    # --- Paiements Tunisiens (Flouci & Konnect & Simulation) ---

    def record_payment_transaction(
        self,
        subscriber_id: int,
        gateway: str,
        amount_tnd: float,
        plan: str,
        payment_ref: str,
        status: str = "PENDING"
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO payment_transactions (subscriber_id, gateway, amount_tnd, plan, payment_ref, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (subscriber_id, gateway, amount_tnd, plan, payment_ref, status, datetime.utcnow().isoformat()))
            conn.commit()
            return cursor.lastrowid

    def activate_plan_from_payment(self, payment_ref: str, status: str = "SUCCESS") -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM payment_transactions WHERE payment_ref = ?", (payment_ref,))
            row = cursor.fetchone()
            if not row:
                return False
            sub_id = row["subscriber_id"]
            plan = row["plan"]
            cursor.execute("UPDATE payment_transactions SET status = ?, completed_at = ? WHERE payment_ref = ?", (status, datetime.utcnow().isoformat(), payment_ref))
            if status == "SUCCESS":
                quota = 100 if plan == "PRO" else (10 if plan == "STARTER" else 3)
                cursor.execute("UPDATE subscribers SET plan = ?, is_active = 1, monthly_pack_quota = ? WHERE id = ?", (plan, quota, sub_id))
            conn.commit()
            return True


    def set_subscriber_password(self, sub_id: int, password: str) -> bool:
        """Définit ou met à jour le mot de passe d'un abonné de façon sécurisée."""
        if not password or len(password.strip()) < 4:
            return False
        pw_hash = hash_password(password.strip())
        with self._get_connection() as conn:
            conn.execute("UPDATE subscribers SET password_hash = ? WHERE id = ?", (pw_hash, sub_id))
            conn.commit()
            return True

    def verify_subscriber_credentials(self, phone: str, password: str) -> Tuple[bool, Optional[Subscriber], str]:
        """
        Vérifie les identifiants d'un client (téléphone + mot de passe).
        Retourne (is_valid, subscriber, message).
        """
        sub = self.get_subscriber_by_phone(phone)
        if not sub:
            return False, None, "Numéro introuvable. Veuillez vérifier vos identifiants."
        
        # Si aucun mot de passe n'a encore été défini pour cet abonné (premier accès / migration)
        if not sub.password_hash:
            if password and len(password.strip()) >= 4:
                self.set_subscriber_password(sub.id, password)
                sub = self.get_subscriber_by_id(sub.id)
                return True, sub, "Mot de passe initialisé avec succès."
            else:
                return False, sub, "Veuillez saisir un mot de passe valide (min 4 caractères)."

        # Vérification du hash
        if verify_password(password, sub.password_hash):
            return True, sub, "Connexion réussie."
        else:
            return False, sub, "Mot de passe incorrect."

    def create_password_reset_otp(self, phone: str) -> Tuple[Optional[Subscriber], Optional[str]]:
        """
        Génère un code OTP à 6 chiffres temporaire valable 10 minutes pour réinitialiser le mot de passe.
        Retourne (subscriber, otp_code) ou (None, None) si le numéro n'est pas trouvé.
        """
        sub = self.get_subscriber_by_phone(phone)
        if not sub:
            return None, None
        
        otp_code = f"{secrets.randbelow(900000) + 100000:06d}"
        now_dt = datetime.now(timezone.utc)
        created_at = now_dt.isoformat()
        expires_at = (now_dt + timedelta(minutes=10)).isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE password_reset_otps SET is_used = 1 WHERE subscriber_id = ? AND is_used = 0", (sub.id,))
            cursor.execute("""
            INSERT INTO password_reset_otps (subscriber_id, phone, otp_code, expires_at, is_used, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """, (sub.id, sub.phone, otp_code, expires_at, created_at))
            conn.commit()
            
        return sub, otp_code

    def verify_and_consume_password_reset_otp(self, phone: str, otp_code: str, new_password: str) -> Tuple[bool, str]:
        """
        Valide le code OTP (actif, non consommé, non expiré) et met à jour le mot de passe PBKDF2 de l'abonné.
        Retourne (True, "Success") ou (False, message_erreur).
        """
        sub = self.get_subscriber_by_phone(phone)
        if not sub:
            return False, "Numéro de téléphone non associé à un compte Tenders.tn"
        
        if not otp_code or not otp_code.strip():
            return False, "Code OTP invalide ou expiré"
        
        if not new_password or len(new_password.strip()) < 4:
            return False, "Le nouveau mot de passe doit comporter au moins 4 caractères"
            
        clean_otp = otp_code.strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT id, expires_at, is_used FROM password_reset_otps
            WHERE subscriber_id = ? AND otp_code = ? AND is_used = 0
            ORDER BY id DESC LIMIT 1
            """, (sub.id, clean_otp))
            row = cursor.fetchone()
            if not row:
                return False, "Code OTP invalide ou expiré"
            
            otp_id = row["id"]
            expires_at_str = row["expires_at"]
            
            try:
                expires_dt = datetime.fromisoformat(expires_at_str)
                now_dt = datetime.now(timezone.utc) if expires_dt.tzinfo else datetime.utcnow()
                if now_dt > expires_dt:
                    return False, "Code OTP invalide ou expiré"
            except Exception:
                if datetime.now(timezone.utc).isoformat() > expires_at_str:
                    return False, "Code OTP invalide ou expiré"
            
            cursor.execute("UPDATE password_reset_otps SET is_used = 1 WHERE id = ?", (otp_id,))
            conn.commit()
            
        success = self.set_subscriber_password(sub.id, new_password.strip())
        if not success:
            return False, "Erreur lors de la mise à jour du mot de passe"
            
        return True, "Success"

    def update_subscriber_profile(
        self,
        sub_id: int,
        company_name: Optional[str] = None,
        email: Optional[str] = None,
        categories: Optional[List[str]] = None,
        governorates: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        channel: Optional[str] = None,
        password: Optional[str] = None
    ) -> bool:
        updates = []
        params = []
        if company_name is not None:
            updates.append("company_name = ?")
            params.append(company_name.strip())
        if email is not None:
            updates.append("email = ?")
            params.append(email.strip().lower())
        if categories is not None:
            updates.append("categories = ?")
            params.append(json.dumps(categories, ensure_ascii=False))
        if governorates is not None:
            updates.append("governorates = ?")
            params.append(json.dumps(governorates, ensure_ascii=False))
        if keywords is not None:
            updates.append("keywords = ?")
            params.append(json.dumps(keywords, ensure_ascii=False))
        if channel is not None:
            updates.append("channel = ?")
            params.append(channel)
        if password is not None and len(password.strip()) >= 4:
            updates.append("password_hash = ?")
            params.append(hash_password(password.strip()))

        if not updates:
            return False

        params.append(sub_id)
        with self._get_connection() as conn:
            conn.execute(f"UPDATE subscribers SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            return True

    def add_or_update_bookmark(
        self,
        subscriber_id: int,
        tender_id: int,
        status: str = "A_ETUDIER",
        notes: str = ""
    ) -> Dict[str, Any]:
        now_str = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO client_bookmarks (subscriber_id, tender_id, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(subscriber_id, tender_id) DO UPDATE SET
                status = excluded.status,
                notes = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE client_bookmarks.notes END,
                updated_at = excluded.updated_at
            """, (subscriber_id, tender_id, status, notes, now_str, now_str))
            conn.commit()
            return {"status": "SUCCESS", "subscriber_id": subscriber_id, "tender_id": tender_id, "pipeline_status": status}

    def remove_bookmark(self, subscriber_id: int, tender_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM client_bookmarks WHERE subscriber_id = ? AND tender_id = ?", (subscriber_id, tender_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_subscriber_bookmarks(self, subscriber_id: int) -> List[Dict[str, Any]]:
        now = datetime.now()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT b.id AS bookmark_id, b.status AS bookmark_status, b.notes AS bookmark_notes, b.created_at AS bookmarked_at,
                   t.*
            FROM client_bookmarks b
            JOIN tenders t ON t.ep_bid_master_id = b.tender_id
            WHERE b.subscriber_id = ?
            ORDER BY t.deadline_date ASC
            """, (subscriber_id,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                deadline_str = item.get("deadline_date") or ""
                item["countdown"] = self._calculate_countdown(deadline_str, now)
                if item.get("tags"):
                    try:
                        item["tags"] = json.loads(item["tags"])
                    except Exception:
                        item["tags"] = []
                results.append(item)
            return results

    def get_subscriber_matched_tenders(self, subscriber_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        sub = self.get_subscriber_by_id(subscriber_id)
        if not sub:
            return []

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        where_clauses = ["t.deadline_date >= ?"]
        params = [now_str]

        # Catégories
        if "ALL" not in sub.categories and sub.categories:
            cat_placeholders = ",".join(["?"] * len(sub.categories))
            where_clauses.append(f"t.category IN ({cat_placeholders})")
            params.extend(sub.categories)

        # Régions
        if "ALL" not in sub.governorates and sub.governorates:
            gov_or = []
            for g in sub.governorates:
                gov_or.append("(t.governorate = ? OR t.execution_place = ? OR t.governorate LIKE ?)")
                params.extend([g, g, f"%{g}%"])
            gov_or.append("t.governorate LIKE '%national%'")
            where_clauses.append(f"({' OR '.join(gov_or)})")

        where_sql = " AND ".join(where_clauses)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tender_id, status, notes FROM client_bookmarks WHERE subscriber_id = ?", (subscriber_id,))
            bookmarks_map = {row["tender_id"]: {"status": row["status"], "notes": row["notes"]} for row in cursor.fetchall()}

            query = f"""
            SELECT t.* FROM tenders t
            WHERE {where_sql}
            ORDER BY t.publication_date DESC
            LIMIT ?
            """
            rows = cursor.execute(query, params + [limit]).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                t_id = item["ep_bid_master_id"]
                item["is_bookmarked"] = t_id in bookmarks_map
                item["bookmark_status"] = bookmarks_map.get(t_id, {}).get("status")
                item["bookmark_notes"] = bookmarks_map.get(t_id, {}).get("notes", "")
                item["countdown"] = self._calculate_countdown(item.get("deadline_date") or "", now)
                if item.get("tags"):
                    try:
                        item["tags"] = json.loads(item["tags"])
                    except Exception:
                        item["tags"] = []
                results.append(item)
            return results

    def _calculate_countdown(self, deadline_str: str, now_dt: Optional[datetime] = None) -> Dict[str, Any]:
        if not now_dt:
            now_dt = datetime.now()
        if not deadline_str:
            return {"days_left": None, "urgency": "UNKNOWN", "label": "Non spécifié", "badge_color": "slate"}
        try:
            clean_date = deadline_str[:19]
            deadline_dt = datetime.strptime(clean_date, "%Y-%m-%d %H:%M:%S")
            diff = deadline_dt - now_dt
            total_seconds = int(diff.total_seconds())
            days_left = diff.days
            if total_seconds < 0:
                return {"days_left": days_left, "urgency": "EXPIRED", "label": "Clôturé", "badge_color": "gray"}
            elif days_left == 0:
                hours_left = max(0, total_seconds // 3600)
                return {"days_left": 0, "hours_left": hours_left, "urgency": "CRITICAL", "label": f"Dernier jour ({hours_left}h)", "badge_color": "red"}
            elif days_left <= 3:
                return {"days_left": days_left, "urgency": "URGENT", "label": f"J-{days_left} (Urgent)", "badge_color": "red"}
            elif days_left <= 7:
                return {"days_left": days_left, "urgency": "MEDIUM", "label": f"J-{days_left}", "badge_color": "amber"}
            else:
                return {"days_left": days_left, "urgency": "RELAXED", "label": f"J-{days_left}", "badge_color": "emerald"}
        except Exception:
            return {"days_left": None, "urgency": "UNKNOWN", "label": deadline_str[:10], "badge_color": "slate"}

    # --- Administration SaaS & CRM ---

    def get_all_subscribers_admin(self) -> List[Dict[str, Any]]:
        now = datetime.utcnow()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT s.*, 
                   (SELECT COUNT(*) FROM client_bookmarks b WHERE b.subscriber_id = s.id) AS bookmarks_count,
                   (SELECT COUNT(*) FROM notification_logs n WHERE n.subscriber_id = s.id) AS notifs_count
            FROM subscribers s
            ORDER BY s.id DESC
            """)
            rows = cursor.fetchall()
            subs = []
            for r in rows:
                item = dict(r)
                for f in ["categories", "governorates", "keywords"]:
                    if item.get(f):
                        try:
                            item[f] = json.loads(item[f])
                        except Exception:
                            item[f] = []
                # Features
                feat = None
                if item.get("features"):
                    try:
                        feat = json.loads(item["features"])
                    except Exception:
                        feat = None
                if not feat:
                    feat = {
                        "tech_proposal": True,
                        "commercial_bpu": True,
                        "clarification": True,
                        "scoring_simulation": True,
                        "submission_pack_zip": True,
                        "checklist_admin": True,
                        "printable_pdf": True
                    }
                item["features"] = feat
                # Usage mensuel
                current_month = datetime.now().strftime("%Y-%m")
                u_row = cursor.execute("SELECT packs_count FROM monthly_usage WHERE subscriber_id = ? AND year_month = ?", (item["id"], current_month)).fetchone()
                item["used_this_month"] = u_row[0] if u_row else 0
                if not item.get("monthly_pack_quota"):
                    item["monthly_pack_quota"] = 3 if item.get("plan") == "TRIAL" else (10 if item.get("plan") == "STARTER" else 100)
                subs.append(item)
            return subs

    def toggle_subscriber_status(self, subscriber_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE subscribers SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?", (subscriber_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_admin_dashboard_metrics(self) -> Dict[str, Any]:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            total_subs = cursor.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
            active_subs = cursor.execute("SELECT COUNT(*) FROM subscribers WHERE is_active = 1").fetchone()[0]
            trial_subs = cursor.execute("SELECT COUNT(*) FROM subscribers WHERE plan = 'TRIAL'").fetchone()[0]
            pro_subs = cursor.execute("SELECT COUNT(*) FROM subscribers WHERE plan = 'PRO' AND is_active = 1").fetchone()[0]
            starter_subs = cursor.execute("SELECT COUNT(*) FROM subscribers WHERE plan = 'STARTER' AND is_active = 1").fetchone()[0]
            mrr_estimate = (pro_subs * 129) + (starter_subs * 49)

            total_tenders = cursor.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
            active_tenders = cursor.execute("SELECT COUNT(*) FROM tenders WHERE deadline_date >= ?", (now_str,)).fetchone()[0]
            total_bookmarks = cursor.execute("SELECT COUNT(*) FROM client_bookmarks").fetchone()[0]
            total_notifs = cursor.execute("SELECT COUNT(*) FROM notification_logs").fetchone()[0]

            return {
                "total_subscribers": total_subs,
                "active_subscribers": active_subs,
                "trial_subscribers": trial_subs,
                "paying_subscribers": pro_subs + starter_subs,
                "estimated_mrr_tnd": mrr_estimate,
                "total_tenders": total_tenders,
                "active_tenders": active_tenders,
                "total_bookmarks": total_bookmarks,
                "total_notifications_sent": total_notifs
            }
