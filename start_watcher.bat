@echo off
title Tenders.tn - Surveillance Automatique TUNEPS
cd /d "C:\Users\Faiez.chakchouk\.gemini\antigravity\scratch\marches-publics-tunisie"
echo =======================================================
echo   Lancement de la Veille Automatique Tenders.tn
echo   Surveillance TUNEPS active toutes les 30 minutes
echo =======================================================
python scheduler.py --interval 30
pause
