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
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("TenderDatabase")

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
    id: Optional[int] = None
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()

class TenderDatabase:
    def __init__(self, db_path: str = "tenders.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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

    def get_active_subscribers(self) -> List[Subscriber]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscribers WHERE is_active = 1")
            rows = cursor.fetchall()
            subs = []
            for r in rows:
                subs.append(Subscriber(
                    id=r["id"],
                    company_name=r["company_name"],
                    phone=r["phone"],
                    email=r["email"],
                    categories=json.loads(r["categories"]),
                    governorates=json.loads(r["governorates"]),
                    keywords=json.loads(r["keywords"]) if r["keywords"] else [],
                    channel=r["channel"],
                    plan=r["plan"],
                    is_active=r["is_active"],
                    created_at=r["created_at"]
                ))
            return subs

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
