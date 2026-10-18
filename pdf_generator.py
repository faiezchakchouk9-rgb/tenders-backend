"""
Générateur de documents PDF officiels et professionnels pour Tenders.tn (Marchés Publics Tunisie).
Conforme au Décret n° 2014-1039 et optimisé sur 1 SEULE PAGE A4 par document.
Palette Corporate : Bleu Marine Nuit (#1E3A8A), Vert Émeraude (#059669), Fond Slate.
Prêt pour la signature électronique (Token ANCE / TunTrust).
"""

import io
import os
import base64
from datetime import datetime
from typing import Dict, Any, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
)
from reportlab.lib.units import inch

# Palette Corporate Tenders.tn
COLOR_PRIMARY = colors.HexColor("#1E3A8A")     # Bleu Marine Nuit
COLOR_EMERALD = colors.HexColor("#059669")     # Vert Émeraude TUNEPS
COLOR_DARK = colors.HexColor("#1E293B")        # Slate-800
COLOR_MUTED = colors.HexColor("#64748B")       # Slate-500
COLOR_BG_LIGHT = colors.HexColor("#F1F5F9")    # Slate-100
COLOR_ACCENT_BG = colors.HexColor("#EFF6FF")   # Bleu très doux
COLOR_BORDER = colors.HexColor("#CBD5E1")      # Slate-300

def _get_styles():
    styles = getSampleStyleSheet()
    
    # Custom styles
    styles.add(ParagraphStyle(
        'DocBadge',
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=COLOR_EMERALD,
        spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        'DocTitle',
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=COLOR_PRIMARY,
        spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        'SectionHeader',
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=13,
        textColor=COLOR_PRIMARY,
        spaceBefore=5,
        spaceAfter=3,
        keepWithNext=True
    ))
    styles.add(ParagraphStyle(
        'BodyMain',
        fontName='Helvetica',
        fontSize=9.5,
        leading=12.5,
        textColor=COLOR_DARK,
        spaceAfter=3
    ))
    styles.add(ParagraphStyle(
        'BodyBold',
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=12.5,
        textColor=COLOR_DARK
    ))
    styles.add(ParagraphStyle(
        'MetaLabel',
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=10.5,
        textColor=COLOR_PRIMARY
    ))
    styles.add(ParagraphStyle(
        'MetaValue',
        fontName='Helvetica',
        fontSize=8.5,
        leading=10.5,
        textColor=COLOR_DARK
    ))
    styles.add(ParagraphStyle(
        'CalloutText',
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=COLOR_DARK
    ))
    styles.add(ParagraphStyle(
        'TableHeader',
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=10.5,
        textColor=colors.white,
        alignment=1 # Center
    ))
    styles.add(ParagraphStyle(
        'TableCell',
        fontName='Helvetica',
        fontSize=8.5,
        leading=10.5,
        textColor=COLOR_DARK
    ))
    styles.add(ParagraphStyle(
        'TableCellRight',
        fontName='Helvetica',
        fontSize=8.5,
        leading=10.5,
        textColor=COLOR_DARK,
        alignment=2 # Right
    ))
    styles.add(ParagraphStyle(
        'TableCellCenter',
        fontName='Helvetica',
        fontSize=8.5,
        leading=10.5,
        textColor=COLOR_DARK,
        alignment=1 # Center
    ))
    styles.add(ParagraphStyle(
        'SignatureLeft',
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=COLOR_MUTED
    ))
    styles.add(ParagraphStyle(
        'SignatureRight',
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=COLOR_PRIMARY,
        alignment=2
    ))
    styles.add(ParagraphStyle(
        'SignatureSub',
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=10,
        textColor=COLOR_MUTED,
        alignment=2
    ))
    return styles

def _make_page_header_footer(canvas, doc, title_header: str, bid_no: str, company_name: str):
    """Dessine en-tête et pied de page automatiques via le canvas."""
    canvas.saveState()
    
    # En-tête supérieur
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(COLOR_MUTED)
    header_text = f"Tenders.tn • {title_header} | Avis TUNEPS N° {bid_no}"
    canvas.drawRightString(A4[0] - 36, A4[1] - 25, header_text)
    
    # Ligne discrète
    canvas.setStrokeColor(COLOR_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(36, A4[1] - 28, A4[0] - 36, A4[1] - 28)
    
    # Pied de page inférieur
    canvas.line(36, 32, A4[0] - 36, 32)
    footer_text = f"Dossier Officiel de Soumission • {company_name} • Décret n° 2014-1039 • TUNEPS"
    canvas.drawCentredString(A4[0] / 2.0, 20, footer_text)
    
    canvas.restoreState()

def _create_header_flowable(styles, badge: str, title: str, meta: Dict[str, str], company_profile: Optional[Dict[str, Any]] = None) -> List[Any]:
    flowables = []
    
    # Logo éventuel de l'entreprise
    logo_img = None
    if company_profile and company_profile.get("logo_url"):
        raw_logo = company_profile["logo_url"]
        try:
            if raw_logo.startswith("data:image"):
                b64_data = raw_logo.split(",", 1)[1]
                img_data = base64.b64decode(b64_data)
                logo_stream = io.BytesIO(img_data)
                logo_img = Image(logo_stream, width=1.4*inch, height=0.55*inch)
            elif os.path.exists(raw_logo):
                logo_img = Image(raw_logo, width=1.4*inch, height=0.55*inch)
        except Exception:
            logo_img = None

    # Titre & Badge (avec ou sans logo sur la droite)
    p_badge = Paragraph(badge.upper(), styles['DocBadge'])
    p_title = Paragraph(title, styles['DocTitle'])
    
    if logo_img:
        hdr_table = Table([[ [p_badge, p_title], logo_img ]], colWidths=[5.6*inch, 1.7*inch])
        hdr_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        flowables.append(hdr_table)
    else:
        flowables.append(p_badge)
        flowables.append(p_title)
    
    flowables.append(Spacer(1, 3))
    
    # Cartouche Métadonnées 4 colonnes
    items = list(meta.items())
    rows_count = (len(items) + 1) // 2
    table_data = []
    
    idx = 0
    for r in range(rows_count):
        row_cells = []
        for c_pair in range(2):
            if idx < len(items):
                k, v = items[idx]
                row_cells.append(Paragraph(k, styles['MetaLabel']))
                row_cells.append(Paragraph(str(v), styles['MetaValue']))
                idx += 1
            else:
                row_cells.extend(["", ""])
        table_data.append(row_cells)
    
    meta_table = Table(table_data, colWidths=[1.7*inch, 1.95*inch, 1.7*inch, 1.95*inch])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), COLOR_BG_LIGHT),
        ('BACKGROUND', (2,0), (2,-1), COLOR_BG_LIGHT),
        ('GRID', (0,0), (-1,-1), 0.5, COLOR_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    flowables.append(meta_table)
    flowables.append(Spacer(1, 4))
    
    return flowables

def _create_callout(styles, text: str, title: str = "INSTRUCTION TUNEPS") -> Table:
    p = Paragraph(f"<b>📌 {title} :</b> {text}", styles['CalloutText'])
    t = Table([[p]], colWidths=[7.3*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), COLOR_ACCENT_BG),
        ('BOX', (0,0), (-1,-1), 0.75, COLOR_PRIMARY),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 7),
        ('RIGHTPADDING', (0,0), (-1,-1), 7),
    ]))
    return t

def _create_signature_block(styles, company_name: str, role_title: str = "La Direction Générale") -> Table:
    p_left = Paragraph(
        f"Fait à Tunis, le {datetime.now().strftime('%d/%m/%Y')}<br/>"
        f"Document certifié conforme Décret 2014-1039<br/>"
        f"Plateforme Tenders.tn",
        styles['SignatureLeft']
    )
    p_right = Paragraph(
        f"Pour {company_name}<br/>"
        f"<b>{role_title}</b><br/>"
        f"<i>[Cachet et Signature Électronique ANCE / TunTrust]</i>",
        styles['SignatureRight']
    )
    t = Table([[p_left, p_right]], colWidths=[3.65*inch, 3.65*inch])
    t.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    return t


# ==============================================================================
# 1. ACTE D'ENGAGEMENT (PDF 1 PAGE)
# ==============================================================================

def generate_engagement_letter_pdf(
    t: Dict[str, Any],
    company_name: str,
    checklist_data: Dict[str, Any],
    company_profile: Optional[Dict[str, Any]] = None
) -> bytes:
    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = (t.get("title_fr") or t.get("title_ar") or "")[:90]
    deadline = (t.get("deadline_date") or "")[:16]
    rne = (company_profile and company_profile.get("rne_id")) or "En cours"
    
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    styles = _get_styles()
    story = []

    # En-tête & Cartouche
    story.extend(_create_header_flowable(
        styles,
        badge="OFFRE ADMINISTRATIVE OFFICIELLE • DÉCRET N° 2014-1039 (ART. 54)",
        title="ACTE D'ENGAGEMENT SOLENNEL",
        meta={
            "Avis TUNEPS N°": bid_no,
            "Acheteur Public": buyer,
            "Objet du Marché": title,
            "Soumissionnaire": company_name,
            "Matricule / RNE": rne,
            "Délai d'Engagement": "120 jours calendaires"
        },
        company_profile=company_profile
    ))

    # Section 1
    story.append(Paragraph("1. Déclaration Solennelle & Habilitation Légale", styles['SectionHeader']))
    story.append(Paragraph(
        f"Je soussigné(e), représentant légal de l'entreprise <b>{company_name}</b>, immatriculée au Registre National "
        f"des Entreprises (RNE : {rne}), après examen approfondi de toutes les pièces contractuelles de l'Appel d'Offres "
        f"N° <b>{bid_no}</b> émis par <b>{buyer}</b>, déclare sur l'honneur et m'engage fermement à :",
        styles['BodyMain']
    ))

    engagements = [
        ("Respect Intégral du Cahier des Charges", "Exécuter la totalité des prestations strictement conformes aux spécifications du CCTP et clauses CCAG."),
        ("Non-Faillite & Habilitation Juridique", "Ne faire l'objet d'aucune exclusion, interdiction de concourir ou procédure de faillite (Art. 54)."),
        ("Régularité Fiscale & Sociale (CNSS)", "Être en règle vis-à-vis du fisc tunisien et à jour de la totalité des cotisations sociales obligatoires."),
        ("Maintien Ferme & Irrévocable des Prix", "Garantir des prix fermes, non révisables durant 120 jours calendaires à compter de la date limite.")
    ]

    for tit_e, desc_e in engagements:
        p_item = Paragraph(f"<font color='#059669'><b>✔</b></font> <b>{tit_e} :</b> {desc_e}", styles['BodyMain'])
        story.append(p_item)

    story.append(Spacer(1, 3))
    story.append(Paragraph("2. Validation & Signature Électronique", styles['SectionHeader']))
    story.append(_create_callout(
        styles,
        "Cet acte solennel doit être signé électroniquement avec certificat ANCE / TunTrust avant scellement dans l'enveloppe administrative TUNEPS.",
        title="DÉPÔT NUMÉRIQUE OBLIGATOIRE"
    ))
    story.append(Spacer(1, 5))
    story.append(_create_signature_block(styles, company_name, "La Direction Générale"))

    doc.build(story, onFirstPage=lambda c, d: _make_page_header_footer(c, d, "ACTE D'ENGAGEMENT", bid_no, company_name))
    return buf.getvalue()


# ==============================================================================
# 2. DEMANDE DE CAUTION BANCAIRE (PDF 1 PAGE)
# ==============================================================================

def generate_bank_guarantee_pdf(
    t: Dict[str, Any],
    company_name: str,
    company_profile: Optional[Dict[str, Any]] = None
) -> bytes:
    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = (t.get("title_fr") or t.get("title_ar") or "")[:90]
    deadline = (t.get("deadline_date") or "")[:16]
    guarantee = t.get("guarantee_type") or "Selon CDC"
    bank = (company_profile and company_profile.get("bank_name")) or "[Nom de votre Banque]"
    rib = (company_profile and company_profile.get("rib")) or "[RIB Bancaire]"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    styles = _get_styles()
    story = []

    story.extend(_create_header_flowable(
        styles,
        badge="OFFRE ADMINISTRATIVE • CAUTIONNEMENT BANCAIRE PROVISOIRE",
        title="DEMANDE D'ÉMISSION DE CAUTION BANCAIRE",
        meta={
            "Avis TUNEPS N°": bid_no,
            "Bénéficiaire (Acheteur)": buyer,
            "Objet du Marché": title,
            "Entreprise Demandeur": company_name,
            "Montant / Quotité": guarantee,
            "Date Limite de Dépôt": deadline or "Selon avis"
        },
        company_profile=company_profile
    ))

    story.append(Paragraph("Destinataire de la Demande", styles['SectionHeader']))
    story.append(Paragraph(
        f"<b>À l'attention de :</b> Monsieur le Directeur d'Agence<br/>"
        f"<b>Établissement Bancaire :</b> {bank} • <b>Compte / RIB :</b> {rib}",
        styles['BodyMain']
    ))

    story.append(Paragraph("Objet & Réquisitions Légales (Art. 54 du Décret 2014-1039)", styles['SectionHeader']))
    story.append(Paragraph(
        f"Monsieur le Directeur,<br/><br/>"
        f"Notre entreprise <b>{company_name}</b> a l'honneur de solliciter la délivrance d'une caution bancaire "
        f"provisoire au profit de :<br/>"
        f"• <b>Bénéficiaire (Acheteur Public) :</b> {buyer}<br/>"
        f"• <b>Objet du Marché :</b> {title}<br/>"
        f"• <b>Avis TUNEPS N° :</b> {bid_no} | <b>Montant requis :</b> {guarantee}<br/>"
        f"• <b>Validité exigée :</b> 120 jours calendaires au-delà de la date limite de remise ({deadline})<br/><br/>"
        f"Cette caution solidaire et irrévocable est expressément requise en application de l'Article 54 du "
        f"Décret n° 2014-1039 portant réglementation des marchés publics en Tunisie. Nous vous remercions de bien "
        f"vouloir établir l'attestation originale afin que nous puissions l'insérer dans notre dossier de soumission TUNEPS.",
        styles['BodyMain']
    ))

    story.append(Spacer(1, 3))
    story.append(_create_callout(
        styles,
        "Transmettez ce formulaire à votre agence bancaire au moins 5 jours ouvrés avant la clôture pour assurer l'émission dans les délais.",
        title="DÉLAIS BANCAIRES CRITIQUES"
    ))
    story.append(Spacer(1, 5))
    story.append(_create_signature_block(styles, company_name, "La Direction Générale"))

    doc.build(story, onFirstPage=lambda c, d: _make_page_header_footer(c, d, "DEMANDE DE CAUTION", bid_no, company_name))
    return buf.getvalue()


# ==============================================================================
# 3. MÉMOIRE TECHNIQUE D'EXÉCUTION (PDF 1 PAGE)
# ==============================================================================

def generate_technical_proposal_pdf(
    t: Dict[str, Any],
    company_name: str,
    tech_data: Dict[str, Any],
    company_profile: Optional[Dict[str, Any]] = None
) -> bytes:
    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = (t.get("title_fr") or t.get("title_ar") or "")[:90]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    styles = _get_styles()
    story = []

    tech_meta = {
        "Avis d'Appel d'Offres": bid_no,
        "Acheteur Public": buyer,
        "Objet des Prestations": title,
        "Soumissionnaire": company_name,
    }
    if company_profile and company_profile.get("rne_id"):
        tech_meta["Matricule / RNE"] = company_profile["rne_id"]
    tech_meta["Note Technique Estimée"] = f"{tech_data.get('score', 85)} / 100"
    tech_meta["Normes Appliquées"] = "ISO 9001 / Agile / CCTP Conforme"

    story.extend(_create_header_flowable(
        styles,
        badge="OFFRE TECHNIQUE QUALIFIÉE • NOTE TECHNIQUE MAXIMISÉE",
        title="MÉMOIRE TECHNIQUE D'EXÉCUTION",
        meta=tech_meta,
        company_profile=company_profile
    ))

    sections = tech_data.get("sections", [])
    if sections:
        for s_idx, sec in enumerate(sections[:3], 1):
            story.append(Paragraph(f"{s_idx}. {sec.get('title', 'Méthodologie')}", styles['SectionHeader']))
            story.append(Paragraph(sec.get("content", "")[:190] + "...", styles['BodyMain']))
            for h in sec.get("highlights", [])[:2]:
                story.append(Paragraph(f"<font color='#1E3A8A'><b>▸</b></font> {h}", styles['BodyMain']))

    story.append(Spacer(1, 3))
    story.append(_create_callout(
        styles,
        f"L'entreprise {company_name} s'engage sur les niveaux de service (SLA) contractuels et la mobilisation immédiate de son équipe certifiée.",
        title="ENGAGEMENT QUALITÉ"
    ))
    story.append(Spacer(1, 5))
    story.append(_create_signature_block(styles, company_name, "La Direction Technique & Projets"))

    doc.build(story, onFirstPage=lambda c, d: _make_page_header_footer(c, d, "MÉMOIRE TECHNIQUE", bid_no, company_name))
    return buf.getvalue()


# ==============================================================================
# 4. BORDEREAU DES PRIX UNITAIRES & DQE (PDF 1 PAGE)
# ==============================================================================

def generate_commercial_bpu_pdf(
    t: Dict[str, Any],
    company_name: str,
    comm_data: Dict[str, Any],
    company_profile: Optional[Dict[str, Any]] = None
) -> bytes:
    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = (t.get("title_fr") or t.get("title_ar") or "")[:90]

    total_ht = comm_data.get("total_ht", 0)
    total_ttc = comm_data.get("total_ttc", 0)
    tva = comm_data.get("tva_amount", 0)
    words_ttc = comm_data.get("total_ttc_words", "")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    styles = _get_styles()
    story = []

    meta = {
        "Avis TUNEPS N°": bid_no,
        "Acheteur Public": buyer,
        "Objet du Marché": title,
        "Soumissionnaire": company_name,
    }
    if company_profile:
        if company_profile.get("rne_id"):
            meta["Matricule / RNE"] = company_profile["rne_id"]
        if company_profile.get("bank_name") or company_profile.get("rib"):
            meta["Banque & RIB"] = f"{company_profile.get('bank_name', '')} {company_profile.get('rib', '')}".strip()
        if company_profile.get("address"):
            meta["Siège Entreprise"] = company_profile["address"]
    meta["Total Général HT"] = f"{total_ht:,.3f} TND"
    meta["Total Général TTC"] = f"{total_ttc:,.3f} TND"

    story.extend(_create_header_flowable(
        styles,
        badge="OFFRE FINANCIÈRE OFFICIELLE • BPU / DQE (DÉCRET N° 2014-1039)",
        title="BORDEREAU DES PRIX UNITAIRES & DQE",
        meta=meta,
        company_profile=company_profile
    ))

    story.append(Paragraph("Bordereau des Prix Unitaires & Décomposition", styles['SectionHeader']))

    # Tableau BPU
    items = comm_data.get("items", [])[:4]
    bpu_data = [[
        Paragraph("N°", styles['TableHeader']),
        Paragraph("Désignation des Prestations", styles['TableHeader']),
        Paragraph("Qté", styles['TableHeader']),
        Paragraph("P.U. HT (TND)", styles['TableHeader']),
        Paragraph("Total HT (TND)", styles['TableHeader'])
    ]]

    for i, it in enumerate(items, 1):
        desc = it.get("desc") or it.get("designation") or f"Prestation lot {i}"
        qty = it.get("qty") or it.get("quantity") or 1
        pu = it.get("unit_price_ht") or it.get("unit_price") or 0.0
        tot = it.get("total_price_ht") or (qty * pu)

        bpu_data.append([
            Paragraph(str(i), styles['TableCellCenter']),
            Paragraph(desc[:55], styles['TableCell']),
            Paragraph(str(qty), styles['TableCellCenter']),
            Paragraph(f"{pu:,.3f}", styles['TableCellRight']),
            Paragraph(f"{tot:,.3f}", styles['TableCellRight'])
        ])

    bpu_table = Table(bpu_data, colWidths=[0.4*inch, 3.5*inch, 0.6*inch, 1.4*inch, 1.4*inch])
    bpu_style = [
        ('BACKGROUND', (0,0), (-1,0), COLOR_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, COLOR_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]
    for r_idx in range(1, len(bpu_data)):
        if r_idx % 2 == 0:
            bpu_style.append(('BACKGROUND', (0, r_idx), (-1, r_idx), COLOR_BG_LIGHT))
    bpu_table.setStyle(TableStyle(bpu_style))
    story.append(bpu_table)

    story.append(Spacer(1, 3))
    story.append(Paragraph("Récapitulatif Fiscal & Net à Payer", styles['SectionHeader']))

    recap_data = [
        [
            Paragraph("Total Hors Taxes (HT)", styles['MetaLabel']),
            Paragraph(f"{total_ht:,.3f} TND", styles['TableCellRight']),
            Paragraph("TVA Légale (19.00%)", styles['MetaLabel']),
            Paragraph(f"{tva:,.3f} TND", styles['TableCellRight'])
        ],
        [
            Paragraph("<b>TOTAL GÉNÉRAL TTC</b>", styles['MetaLabel']),
            Paragraph(f"<b>{total_ttc:,.3f} TND</b>", styles['TableCellRight']),
            Paragraph("<b>Net à Percevoir (Retenue 1.5%)</b>", styles['MetaLabel']),
            Paragraph(f"<b>{comm_data.get('net_a_payer', 0):,.3f} TND</b>", styles['TableCellRight'])
        ]
    ]
    recap_table = Table(recap_data, colWidths=[1.8*inch, 1.85*inch, 1.8*inch, 1.85*inch])
    recap_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), COLOR_BG_LIGHT),
        ('BACKGROUND', (0,1), (-1,1), COLOR_ACCENT_BG),
        ('GRID', (0,0), (-1,-1), 0.5, COLOR_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(recap_table)

    if words_ttc:
        story.append(Spacer(1, 2))
        story.append(Paragraph(f"<b>Montant TTC arrêté en toutes lettres :</b> <i>{words_ttc}.</i>", styles['BodyMain']))

    story.append(Spacer(1, 4))
    story.append(_create_signature_block(styles, company_name, "La Direction Financière"))

    doc.build(story, onFirstPage=lambda c, d: _make_page_header_footer(c, d, "BORDEREAU DES PRIX", bid_no, company_name))
    return buf.getvalue()


# ==============================================================================
# 5. DEMANDE D'ÉCLAIRCISSEMENT HAICOP (PDF 1 PAGE)
# ==============================================================================

def generate_clarification_pdf(
    t: Dict[str, Any],
    company_name: str,
    risk_data: Dict[str, Any],
    company_profile: Optional[Dict[str, Any]] = None
) -> bytes:
    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = (t.get("title_fr") or t.get("title_ar") or "")[:90]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    styles = _get_styles()
    story = []

    clarif_meta = {
        "Avis TUNEPS": bid_no,
        "Acheteur Public": buyer,
        "Objet du Marché": title,
        "Soumissionnaire": company_name,
    }
    if company_profile and company_profile.get("rne_id"):
        clarif_meta["Matricule / RNE"] = company_profile["rne_id"]
    clarif_meta["Score de Risque"] = f"{risk_data.get('score', 25)}/100"
    clarif_meta["Cadre Réglementaire"] = "Articles 45 et 50 (HAICOP)"

    story.extend(_create_header_flowable(
        styles,
        badge="SÉCURISATION JURIDIQUE • ARTICLES 45 & 50 DU DÉCRET 2014-1039",
        title="DEMANDE OFFICIELLE D'ÉCLAIRCISSEMENT",
        meta=clarif_meta,
        company_profile=company_profile
    ))

    story.append(Paragraph("Objet de la Demande d'Éclaircissement", styles['SectionHeader']))
    story.append(Paragraph(
        f"À l'attention de Monsieur le Président de la Commission des Marchés (<b>{buyer}</b>),<br/>"
        f"Dans le cadre de l'examen de l'avis N° <b>{bid_no}</b>, l'entreprise <b>{company_name}</b> sollicite formellement "
        f"les clarifications suivantes afin de garantir une offre optimale et conforme :",
        styles['BodyMain']
    ))

    clarifs = risk_data.get("clarifications", [])[:2]
    if clarifs:
        for idx, c in enumerate(clarifs, 1):
            story.append(Paragraph(f"Point N° {idx} : {c.get('subject', 'Question')}", styles['SectionHeader']))
            story.append(Paragraph(f"<b>Question :</b> {c.get('question', '')[:150]}", styles['BodyMain']))
            story.append(Paragraph(f"<b>Motivation légale :</b> {c.get('motivation', '')[:150]}", styles['BodyMain']))
    else:
        story.append(Paragraph(risk_data.get("letter_template") or "Demande de clarification sur les spécifications techniques.", styles['BodyMain']))

    story.append(Spacer(1, 3))
    story.append(_create_callout(
        styles,
        "Conformément aux règles HAICOP, toute réponse de l'acheteur public doit faire l'objet d'un additif officiel publié sur TUNEPS.",
        title="PROCÉDURE RÉGLEMENTAIRE TUNEPS"
    ))
    story.append(Spacer(1, 5))
    story.append(_create_signature_block(styles, company_name, "La Direction Juridique & Marchés"))

    doc.build(story, onFirstPage=lambda c, d: _make_page_header_footer(c, d, "DEMANDE ÉCLAIRCISSEMENT", bid_no, company_name))
    return buf.getvalue()
