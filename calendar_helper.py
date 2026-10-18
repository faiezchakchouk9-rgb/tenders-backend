"""
Générateur de rappels de calendrier (RFC 5545 iCalendar .ics, Google Calendar, Outlook)
pour les dates limites des marchés publics TUNEPS sur Tenders.tn.
Intègre les jalons critiques :
- J-5 : Alerte émission cautionnement bancaire
- J-2 : Alerte scellement électronique du pli TUNEPS
- H-3 : Alerte de clôture finale
"""

from datetime import datetime, timedelta
import urllib.parse
from typing import Dict, Any, Tuple

def parse_deadline(deadline_str: str) -> Tuple[datetime, datetime]:
    """Parse une date limite TUNEPS et retourne (start_dt, end_dt)."""
    now = datetime.now()
    if not deadline_str:
        dt = now + timedelta(days=14)
    else:
        clean_str = deadline_str[:19].replace("T", " ")
        try:
            dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                dt = datetime.strptime(clean_str[:10], "%Y-%m-%d")
            except Exception:
                dt = now + timedelta(days=14)
    
    # Événement de 1 heure sur la date limite
    start_dt = dt - timedelta(hours=1)
    end_dt = dt
    return start_dt, end_dt

def generate_ics(t: Dict[str, Any]) -> str:
    """Génère le contenu textuel d'un fichier .ics standard avec 3 alarmes préconfigurées."""
    bid_no = t.get("bid_no", "SANS_NUM")
    buyer = t.get("buyer_name", "Acheteur Public")
    title = t.get("title_fr") or t.get("title_ar") or "Appel d'Offres TUNEPS"
    url = t.get("url") or "https://www.tuneps.tn"
    guarantee = t.get("guarantee_type") or "Selon CDC"
    deadline_str = t.get("deadline_date") or ""
    
    start_dt, end_dt = parse_deadline(deadline_str)
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dtstart = start_dt.strftime("%Y%m%dT%H%M%S")
    dtend = end_dt.strftime("%Y%m%dT%H%M%S")

    description = (
        f"Avis TUNEPS N° {bid_no}\\n"
        f"Acheteur : {buyer}\\n"
        f"Caution Requise : {guarantee}\\n"
        f"Lien officiel : {url}\\n\\n"
        f"RAPPELS CRITIQUES TENDERS.TN :\\n"
        f"• J-5 : Déposer la demande de caution bancaire.\\n"
        f"• J-2 : Signer et sceller le pli électronique TUNEPS.\\n"
        f"• J-0 : Clôture stricte des dépôts à {end_dt.strftime('%H:%M')}."
    )

    ics = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Tenders.tn//Marchés Publics Tunisie//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:tuneps-{bid_no}-{start_dt.strftime('%Y%m%d')}@tenders.tn",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:[TUNEPS] Date Limite Soumission : {title[:60]} ({bid_no})",
        f"DESCRIPTION:{description}",
        f"LOCATION:Plateforme Nationale TUNEPS (www.tuneps.tn)",
        "STATUS:CONFIRMED",
        
        # Alarme 1 : 5 jours avant (Caution bancaire)
        "BEGIN:VALARM",
        "TRIGGER:-P5D",
        "ACTION:DISPLAY",
        "DESCRIPTION:Tenders.tn : Émettre la caution bancaire provisoire auprès de votre banque",
        "END:VALARM",

        # Alarme 2 : 2 jours avant (Scellement TUNEPS)
        "BEGIN:VALARM",
        "TRIGGER:-P2D",
        "ACTION:DISPLAY",
        "DESCRIPTION:Tenders.tn : Sceller l'enveloppe électronique et vérifier les pièces administratives",
        "END:VALARM",

        # Alarme 3 : 3 heures avant (Clôture)
        "BEGIN:VALARM",
        "TRIGGER:-PT3H",
        "ACTION:DISPLAY",
        "DESCRIPTION:Tenders.tn : Dernières heures avant clôture de l'avis TUNEPS !",
        "END:VALARM",

        "END:VEVENT",
        "END:VCALENDAR"
    ]
    return "\r\n".join(ics)

def get_calendar_web_links(t: Dict[str, Any]) -> Dict[str, str]:
    """Génère les liens d'ajout direct en 1 clic pour Google Calendar et Outlook."""
    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = (t.get("title_fr") or t.get("title_ar") or "")[:80]
    deadline_str = t.get("deadline_date") or ""
    start_dt, end_dt = parse_deadline(deadline_str)
    
    summary = f"[TUNEPS] Dépôt : {title} ({bid_no})"
    details = f"Acheteur : {buyer}\nAvis N° : {bid_no}\nCaution : {t.get('guarantee_type', 'CDC')}\nLien : {t.get('url', 'https://www.tuneps.tn')}"
    location = "Portail TUNEPS (www.tuneps.tn)"

    # Format Google Calendar : YYYYMMDDTHHMMSSZ
    # Convertit en dates simples sans tiret
    g_start = start_dt.strftime("%Y%m%dT%H%M%S")
    g_end = end_dt.strftime("%Y%m%dT%H%M%S")
    g_params = {
        "action": "TEMPLATE",
        "text": summary,
        "dates": f"{g_start}/{g_end}",
        "details": details,
        "location": location
    }
    google_url = f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(g_params)}"

    # Format Outlook Web
    o_params = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": summary,
        "body": details,
        "startdt": start_dt.isoformat(),
        "enddt": end_dt.isoformat(),
        "location": location
    }
    outlook_url = f"https://outlook.live.com/calendar/0/deeplink/compose?{urllib.parse.urlencode(o_params)}"

    return {
        "google_calendar_url": google_url,
        "outlook_calendar_url": outlook_url
    }
