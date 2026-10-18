import sqlite3
import json
import database

conn = sqlite3.connect('tenders.db')
c = conn.cursor()

# 1. Profile 1 : ADVANCIA TRAINING (Cabinet de formation & Conseil)
c.execute("""
UPDATE subscribers 
SET company_name = 'ADVANCIA TRAINING',
    categories = '["ETUDES_CONSEIL", "AUTRES"]',
    keywords = '["formation", "conseil", "audit"]'
WHERE phone = '+21628177888'
""")

# 2. Profile 2 : TUNISIE PC / IT SOLUTIONS (Fournisseur matériel informatique)
c.execute("DELETE FROM subscribers WHERE phone = '+21698111222'")
c.execute("""
INSERT INTO subscribers (id, company_name, phone, email, categories, governorates, keywords, channel, plan, is_active, created_at)
VALUES (2, 'TUNISIE PC / IT SOLUTIONS', '+21698111222', 'contact@tunisiepc.tn', '["IT_TELECOM", "FOURNITURES_SERVICES"]', '["ALL"]', '["informatique", "ordinateur", "serveur"]', 'WHATSAPP', 'PRO', 1, datetime('now'))
""")
conn.commit()

db = database.TenderDatabase()
adv_tenders = db.get_subscriber_matched_tenders(1)
pc_tenders = db.get_subscriber_matched_tenders(2)

print(f"=== TEST ADAPTATION MULTI-METIERS ===")
print(f"1. ADVANCIA TRAINING (Formation/Conseil) : {len(adv_tenders)} opportunites ciblees")
for t in adv_tenders[:2]:
    print(f"   -> [Cat: {t['category']}] {t['title_fr'][:65]}")

print(f"\n2. TUNISIE PC (Materiel IT) : {len(pc_tenders)} opportunites ciblees")
for t in pc_tenders[:2]:
    print(f"   -> [Cat: {t['category']}] {t['title_fr'][:65]}")
