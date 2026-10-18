"""
Générateur de documents Word (.docx) professionnels, élégants et calibrés SUR UNE SEULE PAGE pour Tenders.tn.
Chaque document est lisible, aéré et tient rigoureusement sur UNE SEULE PAGE A4 :
- Marges optimisées (0.5 pouce / ~1.27 cm)
- Typographie standard très lisible : Calibri 10.5pt pour le texte, 12pt pour les titres, 9.5pt pour les tableaux
- Interligne confortable (1.1)
- Cartouche d'en-tête et métadonnées soigné
- Tableaux professionnels avec alternance de lignes
- Bloc de signature officiel en bas de page
"""

import io
import os
import base64
from datetime import datetime
from typing import Dict, Any, List, Optional

import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

# Palette Corporate Tenders.tn
COLOR_PRIMARY_HEX = "1E3A8A"      # Bleu Marine Nuit #1E3A8A
COLOR_PRIMARY = RGBColor(30, 58, 138)
COLOR_EMERALD_HEX = "059669"      # Vert Émeraude TUNEPS #059669
COLOR_EMERALD = RGBColor(5, 150, 105)
COLOR_DARK = RGBColor(30, 41, 59)          # Slate-800 pour une lecture nette et contrastée
COLOR_MUTED = RGBColor(100, 116, 139)     # Gris slate-500
COLOR_BG_LIGHT_HEX = "F1F5F9"    # Fond très doux Slate-100
COLOR_ACCENT_BG_HEX = "EFF6FF"   # Fond bleu très doux Blue-50

def _set_cell_background(cell, color_hex: str):
    """Définit la couleur de fond d'une cellule Word."""
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)

def _set_cell_margins(cell, top=60, bottom=60, left=100, right=100):
    """Définit les marges internes confortables d'une cellule."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def _create_single_page_document(title_header: str, bid_no: str, company_name: str) -> Document:
    """Initialise un document Word calibré pour tenir élégamment sur 1 SEULE PAGE avec typographie lisible."""
    doc = Document()
    
    # Format strict A4 (8.27 x 11.69 pouces = 210 x 297 mm) et marges à 0.5 in (~1.27 cm)
    for section in doc.sections:
        section.page_width = Inches(8.27)
        section.page_height = Inches(11.69)
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.55)
        section.right_margin = Inches(0.55)
        
        # En-tête discret et lisible
        header = section.header
        hp = header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        hrun = hp.add_run(f"Tenders.tn • {title_header} | Avis TUNEPS N° {bid_no}")
        hrun.font.name = 'Calibri'
        hrun.font.size = Pt(8.5)
        hrun.font.color.rgb = COLOR_MUTED
        
        # Pied de page
        footer = section.footer
        fp = footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        frun = fp.add_run(f"Dossier Officiel de Soumission • {company_name} • Décret n° 2014-1039 • TUNEPS")
        frun.font.name = 'Calibri'
        frun.font.size = Pt(8.5)
        frun.font.color.rgb = COLOR_MUTED

    # Style Normal : taille de lecture standard (10.5pt, très lisible)
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(10.5)
    font.color.rgb = COLOR_DARK
    
    return doc

def _get_image_stream(logo_data: Optional[str]) -> Optional[io.BytesIO]:
    """Extrait un flux binaire d'image à partir d'un data URI ou d'un chemin de fichier."""
    if not logo_data:
        return None
    try:
        if logo_data.startswith("data:image"):
            parts = logo_data.split(",", 1)
            if len(parts) == 2:
                raw = base64.b64decode(parts[1])
                return io.BytesIO(raw)
        elif os.path.exists(logo_data):
            with open(logo_data, "rb") as f:
                return io.BytesIO(f.read())
    except Exception:
        pass
    return None

def _add_compact_header(
    doc: Document,
    badge_text: str,
    main_title: str,
    meta_dict: Dict[str, str],
    company_profile: Optional[Dict[str, Any]] = None
):
    """Ajoute un en-tête valorisant et lisible avec logo éventuel et cartouche de métadonnées."""
    img_stream = _get_image_stream(company_profile.get("logo_url") if company_profile else None)
    
    if img_stream:
        # Table d'en-tête à 2 colonnes : Titre à gauche, Logo à droite
        t_hdr = doc.add_table(rows=1, cols=2)
        t_hdr.alignment = WD_TABLE_ALIGNMENT.CENTER
        t_hdr.autofit = False
        c_l, c_r = t_hdr.cell(0, 0), t_hdr.cell(0, 1)
        c_l.width = Inches(5.8)
        c_r.width = Inches(1.6)
        _set_cell_margins(c_l, top=0, bottom=0, left=0, right=0)
        _set_cell_margins(c_r, top=0, bottom=0, left=0, right=0)
        
        pl = c_l.paragraphs[0]
        pl.paragraph_format.space_before = Pt(0)
        pl.paragraph_format.space_after = Pt(2)
        pl.paragraph_format.line_spacing = 1.15
        
        run_badge = pl.add_run(f"{badge_text.upper()}\n")
        run_badge.font.name = 'Calibri'
        run_badge.font.size = Pt(8.5)
        run_badge.font.bold = True
        run_badge.font.color.rgb = COLOR_EMERALD

        run_title = pl.add_run(main_title)
        run_title.font.name = 'Calibri'
        run_title.font.size = Pt(14)
        run_title.font.bold = True
        run_title.font.color.rgb = COLOR_PRIMARY
        
        pr = c_r.paragraphs[0]
        pr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        pr.paragraph_format.space_before = Pt(0)
        pr.paragraph_format.space_after = Pt(0)
        try:
            r_img = pr.add_run()
            r_img.add_picture(img_stream, width=Inches(1.4))
        except Exception:
            pass
    else:
        p_title = doc.add_paragraph()
        p_title.paragraph_format.space_before = Pt(0)
        p_title.paragraph_format.space_after = Pt(3)
        p_title.paragraph_format.line_spacing = 1.15
        
        run_badge = p_title.add_run(f"{badge_text.upper()}\n")
        run_badge.font.name = 'Calibri'
        run_badge.font.size = Pt(9)
        run_badge.font.bold = True
        run_badge.font.color.rgb = COLOR_EMERALD

        run_title = p_title.add_run(main_title)
        run_title.font.name = 'Calibri'
        run_title.font.size = Pt(15)
        run_title.font.bold = True
        run_title.font.color.rgb = COLOR_PRIMARY

    # Cartouche d'informations / Métadonnées en grille 4 cellules bien aérées
    items = list(meta_dict.items())
    rows_count = (len(items) + 1) // 2
    table = doc.add_table(rows=rows_count, cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    col_widths = [Inches(1.8), Inches(2.0), Inches(1.8), Inches(1.8)]
    
    idx = 0
    for r in range(rows_count):
        for c_pair in range(2):
            c_lbl = c_pair * 2
            c_val = c_pair * 2 + 1
            cell_lbl = table.cell(r, c_lbl)
            cell_val = table.cell(r, c_val)
            
            cell_lbl.width = col_widths[c_lbl]
            cell_val.width = col_widths[c_val]
            _set_cell_margins(cell_lbl, top=40, bottom=40, left=60, right=60)
            _set_cell_margins(cell_val, top=40, bottom=40, left=60, right=60)
            
            if idx < len(items):
                k, v = items[idx]
                _set_cell_background(cell_lbl, COLOR_BG_LIGHT_HEX)
                _set_cell_background(cell_val, "FFFFFF")
                
                p_k = cell_lbl.paragraphs[0]
                p_k.paragraph_format.space_before = Pt(0)
                p_k.paragraph_format.space_after = Pt(0)
                p_k.paragraph_format.line_spacing = 1.05
                r_k = p_k.add_run(k)
                r_k.font.name = 'Calibri'
                r_k.font.size = Pt(9)
                r_k.font.bold = True
                r_k.font.color.rgb = COLOR_PRIMARY
                
                p_v = cell_val.paragraphs[0]
                p_v.paragraph_format.space_before = Pt(0)
                p_v.paragraph_format.space_after = Pt(0)
                p_v.paragraph_format.line_spacing = 1.05
                r_v = p_v.add_run(str(v))
                r_v.font.name = 'Calibri'
                r_v.font.size = Pt(9.5)
                r_v.font.color.rgb = COLOR_DARK
                idx += 1
            else:
                _set_cell_background(cell_lbl, "FFFFFF")
                _set_cell_background(cell_val, "FFFFFF")

    # Petit séparateur
    p_spacer = doc.add_paragraph()
    p_spacer.paragraph_format.space_before = Pt(3)
    p_spacer.paragraph_format.space_after = Pt(3)


def _add_section_heading(doc: Document, title: str):
    """Titre de section bien lisible et distinct."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.keep_with_next = True
    run = p.add_run(title)
    run.font.name = 'Calibri'
    run.font.size = Pt(12)
    run.font.bold = True
    run.font.color.rgb = COLOR_PRIMARY

def _add_callout(doc: Document, text: str, title: str = "INSTRUCTION TUNEPS"):
    """Encadré de consigne lisible avec fond coloré doux."""
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    cell = table.cell(0, 0)
    cell.width = Inches(7.4)
    _set_cell_background(cell, COLOR_ACCENT_BG_HEX)
    _set_cell_margins(cell, top=50, bottom=50, left=80, right=80)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15
    r_title = p.add_run(f"📌 {title} : ")
    r_title.font.name = 'Calibri'
    r_title.font.size = Pt(9.5)
    r_title.font.bold = True
    r_title.font.color.rgb = COLOR_PRIMARY
    
    r_body = p.add_run(text)
    r_body.font.name = 'Calibri'
    r_body.font.size = Pt(9.5)
    r_body.font.color.rgb = COLOR_DARK

def _add_signature_block(doc: Document, company_name: str, role_title: str = "La Direction Générale"):
    """Bloc de signature officiel et lisible en bas de page."""
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    cell_l, cell_r = table.cell(0, 0), table.cell(0, 1)
    cell_l.width = Inches(3.7)
    cell_r.width = Inches(3.7)
    _set_cell_margins(cell_l, top=40, bottom=30, left=60, right=60)
    _set_cell_margins(cell_r, top=40, bottom=30, left=60, right=60)
    
    pl = cell_l.paragraphs[0]
    pl.paragraph_format.space_before = Pt(0)
    pl.paragraph_format.space_after = Pt(0)
    pl.paragraph_format.line_spacing = 1.15
    rl = pl.add_run(f"Fait à Tunis, le {datetime.now().strftime('%d/%m/%Y')}\nDocument certifié conforme Décret 2014-1039\nPlateforme Tenders.tn")
    rl.font.name = 'Calibri'
    rl.font.size = Pt(8.5)
    rl.font.color.rgb = COLOR_MUTED
    
    pr = cell_r.paragraphs[0]
    pr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pr.paragraph_format.space_before = Pt(0)
    pr.paragraph_format.space_after = Pt(0)
    pr.paragraph_format.line_spacing = 1.15
    rr1 = pr.add_run(f"Pour {company_name}\n{role_title}\n")
    rr1.font.name = 'Calibri'
    rr1.font.size = Pt(10)
    rr1.font.bold = True
    rr1.font.color.rgb = COLOR_PRIMARY
    
    rr2 = pr.add_run("[Cachet et Signature Électronique ANCE / TunTrust]")
    rr2.font.name = 'Calibri'
    rr2.font.size = Pt(8.5)
    rr2.font.italic = True
    rr2.font.color.rgb = COLOR_MUTED


# ==============================================================================
# 1. ACTE D'ENGAGEMENT (1 PAGE LISIBLE)
# ==============================================================================

def generate_engagement_letter_docx(
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
    
    doc = _create_single_page_document("ACTE D'ENGAGEMENT", bid_no, company_name)
    
    _add_compact_header(
        doc,
        badge_text="OFFRE ADMINISTRATIVE OFFICIELLE • DÉCRET N° 2014-1039 (ART. 54)",
        main_title="ACTE D'ENGAGEMENT SOLENNEL",
        meta_dict={
            "Avis TUNEPS N°": bid_no,
            "Acheteur Public": buyer,
            "Objet du Marché": title,
            "Soumissionnaire": company_name,
            "Matricule / RNE": rne,
            "Délai d'Engagement": "120 jours calendaires"
        },
        company_profile=company_profile
    )

    _add_section_heading(doc, "1. Déclaration Solennelle & Habilitation")
    p1 = doc.add_paragraph()
    p1.paragraph_format.space_before = Pt(2)
    p1.paragraph_format.space_after = Pt(4)
    p1.paragraph_format.line_spacing = 1.15
    p1.add_run("Je soussigné(e), représentant légal de l'entreprise ").font.size = Pt(10.5)
    p1.add_run(company_name).font.bold = True
    p1.runs[-1].font.size = Pt(10.5)
    p1.add_run(f", immatriculée au RNE ({rne}), après examen complet du Dossier d'Appel d'Offres N° ").font.size = Pt(10.5)
    p1.add_run(bid_no).font.bold = True
    p1.runs[-1].font.size = Pt(10.5)
    p1.add_run(f" ({buyer}), déclare sur l'honneur et m'engage formellement à :").font.size = Pt(10.5)

    engagements = [
        ("Respect du Cahier des Charges", "Exécuter l'intégralité des prestations conformément aux clauses administratives et au CCTP."),
        ("Non-faillite & Régularité Légale", "Ne faire l'objet d'aucune procédure de faillite, de liquidation ou d'interdiction au sens de l'Art. 54."),
        ("Régularité Fiscale & CNSS", "Être en règle vis-à-vis des déclarations fiscales tunisiennes et à jour des cotisations sociales."),
        ("Maintien Ferme des Prix", "Maintenir les prix unitaires fermes, non révisables durant 120 jours à compter de la date limite.")
    ]

    for tit_e, desc_e in engagements:
        p_it = doc.add_paragraph()
        p_it.paragraph_format.left_indent = Inches(0.2)
        p_it.paragraph_format.space_before = Pt(1.5)
        p_it.paragraph_format.space_after = Pt(2)
        p_it.paragraph_format.line_spacing = 1.15
        r_chk = p_it.add_run("✔ ")
        r_chk.font.bold = True
        r_chk.font.size = Pt(10.5)
        r_chk.font.color.rgb = COLOR_EMERALD
        r_t = p_it.add_run(f"{tit_e} : ")
        r_t.font.bold = True
        r_t.font.size = Pt(10)
        r_d = p_it.add_run(desc_e)
        r_d.font.size = Pt(10)

    _add_section_heading(doc, "2. Signature & Validation Électronique")
    _add_callout(
        doc,
        "Cet acte solennel doit être signé électroniquement avec certificat ANCE / TunTrust avant scellement dans l'enveloppe administrative TUNEPS.",
        title="DÉPÔT NUMÉRIQUE"
    )

    _add_signature_block(doc, company_name, "La Direction Générale")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ==============================================================================
# 2. DEMANDE DE CAUTION BANCAIRE (1 PAGE LISIBLE)
# ==============================================================================

def generate_bank_guarantee_docx(
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
    
    doc = _create_single_page_document("DEMANDE DE CAUTION", bid_no, company_name)
    
    _add_compact_header(
        doc,
        badge_text="OFFRE ADMINISTRATIVE • CAUTIONNEMENT BANCAIRE PROVISOIRE",
        main_title="DEMANDE D'ÉMISSION DE CAUTIONNEMENT BANCAIRE",
        meta_dict={
            "Avis TUNEPS N°": bid_no,
            "Bénéficiaire (Acheteur)": buyer,
            "Objet du Marché": title,
            "Entreprise Demandeur": company_name,
            "Montant / Quotité Requis": guarantee,
            "Date Limite de Remise": deadline or "Selon avis"
        },
        company_profile=company_profile
    )

    _add_section_heading(doc, "Destinataire de la Demande")
    p_dest = doc.add_paragraph()
    p_dest.paragraph_format.space_before = Pt(2)
    p_dest.paragraph_format.space_after = Pt(3)
    p_dest.paragraph_format.line_spacing = 1.15
    r_d1 = p_dest.add_run("À l'attention de : Monsieur le Directeur d'Agence\n")
    r_d1.font.bold = True
    r_d1.font.size = Pt(10.5)
    r_d2 = p_dest.add_run(f"Banque : {bank} • RIB : {rib}\n")
    r_d2.font.size = Pt(10)

    _add_section_heading(doc, "Objet & Réquisitions Légales (Art. 54 du Décret 2014-1039)")
    p_corps = doc.add_paragraph()
    p_corps.paragraph_format.space_before = Pt(2)
    p_corps.paragraph_format.space_after = Pt(4)
    p_corps.paragraph_format.line_spacing = 1.15
    
    p_corps.add_run(
        f"Monsieur le Directeur,\n\n"
        f"Notre entreprise {company_name} a l'honneur de solliciter la délivrance d'une caution bancaire provisoire au profit de :\n"
        f"• Bénéficiaire (Acheteur Public) : {buyer}\n"
        f"• Objet du Marché : {title}\n"
        f"• Avis TUNEPS N° {bid_no} | Montant de la caution : {guarantee}\n"
        f"• Validité requise : 120 jours calendaires au-delà de la date limite ({deadline})\n\n"
        f"Cette caution solidaire est expressément sollicitée conformément aux prescriptions de l'Article 54 du "
        f"Décret n° 2014-1039 portant réglementation des marchés publics en Tunisie. Nous vous remercions de bien "
        f"vouloir nous délivrer l'attestation originale pour insertion dans notre pli TUNEPS."
    )
    p_corps.runs[0].font.size = Pt(10)

    _add_callout(
        doc,
        "Transmettez ce formulaire à votre agence bancaire au moins 5 jours ouvrés avant la clôture pour assurer l'émission dans les délais.",
        title="DÉLAIS BANCAIRES"
    )

    _add_signature_block(doc, company_name, "La Direction Générale")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ==============================================================================
# 3. MÉMOIRE TECHNIQUE D'EXÉCUTION (1 PAGE LISIBLE)
# ==============================================================================

def generate_technical_proposal_docx(
    t: Dict[str, Any],
    company_name: str,
    tech_data: Dict[str, Any],
    company_profile: Optional[Dict[str, Any]] = None
) -> bytes:
    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = (t.get("title_fr") or t.get("title_ar") or "")[:90]
    
    doc = _create_single_page_document("MÉMOIRE TECHNIQUE", bid_no, company_name)
    
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

    _add_compact_header(
        doc,
        badge_text="OFFRE TECHNIQUE QUALIFIÉE • NOTE TECHNIQUE MAXIMISÉE",
        main_title="MÉMOIRE TECHNIQUE D'EXÉCUTION",
        meta_dict=tech_meta,
        company_profile=company_profile
    )

    sections = tech_data.get("sections", [])
    if sections:
        for s_idx, sec in enumerate(sections[:3], 1):
            _add_section_heading(doc, f"{s_idx}. {sec.get('title', 'Méthodologie')}")
            
            p_c = doc.add_paragraph()
            p_c.paragraph_format.space_before = Pt(1)
            p_c.paragraph_format.space_after = Pt(2)
            p_c.paragraph_format.line_spacing = 1.15
            r_c = p_c.add_run(sec.get("content", "")[:180] + "...")
            r_c.font.size = Pt(10)

            highlights = sec.get("highlights", [])[:2]
            for h in highlights:
                p_h = doc.add_paragraph()
                p_h.paragraph_format.left_indent = Inches(0.2)
                p_h.paragraph_format.space_before = Pt(1)
                p_h.paragraph_format.space_after = Pt(1.5)
                p_h.paragraph_format.line_spacing = 1.15
                r_b = p_h.add_run("▸ ")
                r_b.font.bold = True
                r_b.font.size = Pt(10)
                r_b.font.color.rgb = COLOR_PRIMARY
                r_txt = p_h.add_run(h)
                r_txt.font.size = Pt(9.5)

    _add_callout(
        doc,
        f"L'entreprise {company_name} garantit les niveaux de service (SLA) contractuels et la mobilisation immédiate de ses experts certifiés.",
        title="ENGAGEMENT QUALITÉ"
    )

    _add_signature_block(doc, company_name, "La Direction Technique & Projets")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ==============================================================================
# 4. BORDEREAU DES PRIX UNITAIRES & DQE (1 PAGE LISIBLE)
# ==============================================================================

def generate_commercial_bpu_docx(
    t: Dict[str, Any],
    company_name: str,
    comm_data: Dict[str, Any],
    company_profile: Optional[Dict[str, Any]] = None
) -> bytes:
    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = (t.get("title_fr") or t.get("title_ar") or "")[:90]
    
    doc = _create_single_page_document("BORDEREAU DES PRIX", bid_no, company_name)
    
    total_ht = comm_data.get("total_ht", 0)
    total_ttc = comm_data.get("total_ttc", 0)
    tva = comm_data.get("tva_amount", 0)
    words_ttc = comm_data.get("total_ttc_words", "")

    meta_dict = {
        "Avis TUNEPS N°": bid_no,
        "Acheteur Public": buyer,
        "Objet du Marché": title,
        "Soumissionnaire": company_name,
    }
    if company_profile:
        if company_profile.get("rne_id"):
            meta_dict["Matricule / RNE"] = company_profile["rne_id"]
        if company_profile.get("bank_name") or company_profile.get("rib"):
            meta_dict["Banque & RIB"] = f"{company_profile.get('bank_name', '')} {company_profile.get('rib', '')}".strip()
        if company_profile.get("address"):
            meta_dict["Siège Entreprise"] = company_profile["address"]
    meta_dict["Total Général HT"] = f"{total_ht:,.3f} TND"
    meta_dict["Total Général TTC"] = f"{total_ttc:,.3f} TND"

    _add_compact_header(
        doc,
        badge_text="OFFRE FINANCIÈRE OFFICIELLE • BPU / DQE (DÉCRET N° 2014-1039)",
        main_title="BORDEREAU DES PRIX UNITAIRES (BPU) & DQE",
        meta_dict=meta_dict,
        company_profile=company_profile
    )

    _add_section_heading(doc, "Bordereau des Prix Unitaires & Décomposition")

    items = comm_data.get("items", [])[:4]
    table = doc.add_table(rows=1, cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    headers = ["N°", "Désignation des Prestations", "Qté", "P.U. HT (TND)", "Total HT (TND)"]
    widths = [Inches(0.4), Inches(3.4), Inches(0.6), Inches(1.5), Inches(1.5)]
    
    hdr_row = table.rows[0]
    for idx, (title_h, w) in enumerate(zip(headers, widths)):
        cell = hdr_row.cells[idx]
        cell.width = w
        _set_cell_background(cell, COLOR_PRIMARY_HEX)
        _set_cell_margins(cell, top=40, bottom=40, left=50, right=50)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.05
        if idx in [0, 2]:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif idx in [3, 4]:
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        else:
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run(title_h)
        r.font.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(255, 255, 255)

    for i, it in enumerate(items, 1):
        row = table.add_row()
        desc = it.get("desc") or it.get("designation") or f"Prestation lot {i}"
        qty = it.get("qty") or it.get("quantity") or 1
        pu = it.get("unit_price_ht") or it.get("unit_price") or 0.0
        tot = it.get("total_price_ht") or (qty * pu)

        row_cells = row.cells
        for idx, w in enumerate(widths):
            row_cells[idx].width = w
            _set_cell_margins(row_cells[idx], top=35, bottom=35, left=50, right=50)
            if i % 2 == 0:
                _set_cell_background(row_cells[idx], COLOR_BG_LIGHT_HEX)

        for p_idx, text_val, align in [
            (0, str(i), WD_ALIGN_PARAGRAPH.CENTER),
            (1, desc[:50], WD_ALIGN_PARAGRAPH.LEFT),
            (2, str(qty), WD_ALIGN_PARAGRAPH.CENTER),
            (3, f"{pu:,.3f}", WD_ALIGN_PARAGRAPH.RIGHT),
            (4, f"{tot:,.3f}", WD_ALIGN_PARAGRAPH.RIGHT),
        ]:
            p = row_cells[p_idx].paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.05
            p.alignment = align
            run = p.add_run(text_val)
            run.font.size = Pt(9.5)
            run.font.color.rgb = COLOR_DARK

    _add_section_heading(doc, "Récapitulatif Fiscal & Net à Payer")
    t_recap = doc.add_table(rows=2, cols=4)
    t_recap.alignment = WD_TABLE_ALIGNMENT.CENTER
    t_recap.autofit = False

    recap_cells_data = [
        (0, 0, "Total Hors Taxes (HT)", f"{total_ht:,.3f} TND", False),
        (0, 2, "TVA Légale (19.00%)", f"{tva:,.3f} TND", False),
        (1, 0, "TOTAL GÉNÉRAL TTC", f"{total_ttc:,.3f} TND", True),
        (1, 2, "Net à Percevoir (Retenue 1.5%)", f"{comm_data.get('net_a_payer', 0):,.3f} TND", True),
    ]

    for r_idx, c_idx, lbl, val, is_bold in recap_cells_data:
        cell_l = t_recap.cell(r_idx, c_idx)
        cell_v = t_recap.cell(r_idx, c_idx + 1)
        cell_l.width = Inches(1.8)
        cell_v.width = Inches(1.9)
        _set_cell_margins(cell_l, top=35, bottom=35, left=50, right=50)
        _set_cell_margins(cell_v, top=35, bottom=35, left=50, right=50)
        
        if is_bold:
            _set_cell_background(cell_l, COLOR_ACCENT_BG_HEX)
            _set_cell_background(cell_v, COLOR_ACCENT_BG_HEX)
        else:
            _set_cell_background(cell_l, COLOR_BG_LIGHT_HEX)
            _set_cell_background(cell_v, "FFFFFF")

        pl = cell_l.paragraphs[0]
        pl.paragraph_format.space_before = Pt(0)
        pl.paragraph_format.space_after = Pt(0)
        pl.paragraph_format.line_spacing = 1.05
        rl = pl.add_run(lbl)
        rl.font.size = Pt(9)
        rl.font.bold = is_bold
        if is_bold: rl.font.color.rgb = COLOR_PRIMARY

        pv = cell_v.paragraphs[0]
        pv.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        pv.paragraph_format.space_before = Pt(0)
        pv.paragraph_format.space_after = Pt(0)
        pv.paragraph_format.line_spacing = 1.05
        rv = pv.add_run(val)
        rv.font.size = Pt(9.5)
        rv.font.bold = is_bold
        if is_bold: rv.font.color.rgb = COLOR_PRIMARY

    if words_ttc:
        p_w = doc.add_paragraph()
        p_w.paragraph_format.space_before = Pt(3)
        p_w.paragraph_format.space_after = Pt(2)
        p_w.paragraph_format.line_spacing = 1.15
        r_w1 = p_w.add_run("Montant TTC arrêté en toutes lettres : ")
        r_w1.font.bold = True
        r_w1.font.size = Pt(9)
        r_w2 = p_w.add_run(f"{words_ttc}.")
        r_w2.font.italic = True
        r_w2.font.size = Pt(9)

    _add_signature_block(doc, company_name, "La Direction Financière")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ==============================================================================
# 5. DEMANDE D'ÉCLAIRCISSEMENT HAICOP (1 PAGE LISIBLE)
# ==============================================================================

def generate_clarification_docx(
    t: Dict[str, Any],
    company_name: str,
    risk_data: Dict[str, Any],
    company_profile: Optional[Dict[str, Any]] = None
) -> bytes:
    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = (t.get("title_fr") or t.get("title_ar") or "")[:90]
    
    doc = _create_single_page_document("DEMANDE ÉCLAIRCISSEMENT", bid_no, company_name)
    
    clarif_meta = {
        "Avis TUNEPS": bid_no,
        "Acheteur Public": buyer,
        "Objet du Marché": title,
        "Soumissionnaire": company_name,
    }
    if company_profile and company_profile.get("rne_id"):
        clarif_meta["Matricule / RNE"] = company_profile["rne_id"]
    clarif_meta["Score de Risque"] = f"{risk_data.get('score', 25)}/100 ({risk_data.get('global_badge', 'RISQUE MODÉRÉ')})"
    clarif_meta["Cadre Légal"] = "Articles 45 et 50 (Décret 2014-1039)"

    _add_compact_header(
        doc,
        badge_text="SÉCURISATION JURIDIQUE • ARTICLES 45 & 50 DU DÉCRET 2014-1039",
        main_title="DEMANDE OFFICIELLE D'ÉCLAIRCISSEMENT",
        meta_dict=clarif_meta,
        company_profile=company_profile
    )

    _add_section_heading(doc, "Objet de la Demande d'Éclaircissement")
    p_intro = doc.add_paragraph()
    p_intro.paragraph_format.space_before = Pt(1)
    p_intro.paragraph_format.space_after = Pt(3)
    p_intro.paragraph_format.line_spacing = 1.15
    r_int = p_intro.add_run(
        f"À l'attention de Monsieur le Président de la Commission des Marchés ({buyer}),\n"
        f"Dans le cadre de l'examen de l'avis N° {bid_no}, l'entreprise {company_name} sollicite les clarifications suivantes :"
    )
    r_int.font.size = Pt(10)

    clarifs = risk_data.get("clarifications", [])[:2]
    if clarifs:
        for idx, c in enumerate(clarifs, 1):
            _add_section_heading(doc, f"Point N° {idx} : {c.get('subject', 'Question')}")
            
            p_q = doc.add_paragraph()
            p_q.paragraph_format.left_indent = Inches(0.2)
            p_q.paragraph_format.space_before = Pt(1)
            p_q.paragraph_format.space_after = Pt(1.5)
            p_q.paragraph_format.line_spacing = 1.15
            r_q1 = p_q.add_run("Question : ")
            r_q1.font.bold = True
            r_q1.font.color.rgb = COLOR_PRIMARY
            r_q1.font.size = Pt(9.5)
            r_q2 = p_q.add_run(c.get("question", "")[:140])
            r_q2.font.size = Pt(9.5)

            p_m = doc.add_paragraph()
            p_m.paragraph_format.left_indent = Inches(0.2)
            p_m.paragraph_format.space_before = Pt(1)
            p_m.paragraph_format.space_after = Pt(2)
            p_m.paragraph_format.line_spacing = 1.15
            r_m1 = p_m.add_run("Motivation : ")
            r_m1.font.bold = True
            r_m1.font.size = Pt(9.5)
            r_m2 = p_m.add_run(c.get("motivation", "")[:140])
            r_m2.font.size = Pt(9.5)
    else:
        p_raw = doc.add_paragraph()
        p_raw.paragraph_format.space_before = Pt(1)
        p_raw.paragraph_format.space_after = Pt(3)
        p_raw.paragraph_format.line_spacing = 1.15
        r_raw = p_raw.add_run(risk_data.get("letter_template") or "Demande de clarification des spécifications techniques.")
        r_raw.font.size = Pt(10)

    _add_callout(
        doc,
        "Conformément aux règles HAICOP, toute réponse de l'acheteur public doit faire l'objet d'un additif officiel publié sur TUNEPS.",
        title="PROCÉDURE RÉGLEMENTAIRE"
    )

    _add_signature_block(doc, company_name, "La Direction Juridique & Marchés")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

