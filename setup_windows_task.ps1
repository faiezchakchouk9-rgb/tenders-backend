# Script PowerShell pour configurer la tâche planifiée Windows (Exécution toutes les 30 minutes)

$TaskName = "TendersTN_Watcher"
$ProjectPath = "C:\Users\Faiez.chakchouk\.gemini\antigravity\scratch\marches-publics-tunisie"
$PythonExe = "python.exe"
$Arguments = "pipeline.py"

Write-Host "Configuration de la tâche planifiée Windows : $TaskName..." -ForegroundColor Cyan

# Action : exécuter python pipeline.py dans le dossier du projet
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $Arguments -WorkingDirectory $ProjectPath

# Déclencheur : se répète toutes les 30 minutes indéfiniment
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)

# Paramètres : réveil si en veille, exécution en tâche de fond silencieuse
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Enregistrement de la tâche pour l'utilisateur actuel
try {
    # Supprimer si existante
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    
    # Créer la nouvelle tâche
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Veille automatique des marchés publics TUNEPS avec alertes Telegram par IA."
    Write-Host "`n✅ Tâche planifiée enregistrée avec succès !" -ForegroundColor Green
    Write-Host "Le système va interroger TUNEPS automatiquement toutes les 30 minutes en arrière-plan." -ForegroundColor Green
} catch {
    Write-Host "`nErreur lors de l'enregistrement : $_" -ForegroundColor Red
}
