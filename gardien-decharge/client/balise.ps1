# Balise du gardien de décharge — Windows.
# S'exécute en simple utilisateur : aucun droit administrateur, aucune installation.
# Envoie régulièrement le niveau de batterie et l'état secteur au Raspberry Pi.
#
# Lancement manuel :
#   powershell -ExecutionPolicy Bypass -File balise.ps1 -Gardien http://IP_DU_PI:8642
#
# Lancement automatique à l'ouverture de session (sans admin) :
#   Win + R  ->  shell:startup  ->  y créer un raccourci vers :
#   powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\chemin\balise.ps1" -Gardien "http://IP_DU_PI:8642"

param(
    [string]$Gardien = "http://192.168.1.40:8642",
    [int]$IntervalleSecondes = 60
)

while ($true) {
    try {
        $batterie = Get-CimInstance -ClassName Win32_Battery
        if ($batterie) {
            # BatteryStatus 1, 4, 5 = en décharge ; le reste = alimenté par le secteur
            $secteur = if (@(1, 4, 5) -contains [int]$batterie.BatteryStatus) { 0 } else { 1 }
            $niveau = [int]$batterie.EstimatedChargeRemaining
            Invoke-RestMethod -Uri "$Gardien/balise?batterie=$niveau&secteur=$secteur" -TimeoutSec 5 | Out-Null
        }
    } catch {
        # Pi ou réseau momentanément absent : on réessaiera au prochain tour.
    }
    Start-Sleep -Seconds $IntervalleSecondes
}
