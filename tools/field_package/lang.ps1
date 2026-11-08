# Messages of the field package in Finnish and English. Dot-sourced by the other scripts.
# Language: $env:RELAY_LANG (fi | en), chosen in install.ps1 and saved in device.env.
# Saved with a UTF-8 BOM so Windows PowerShell 5.1 reads the Finnish letters correctly.

$Messages = @{
    fi = @{
        no_python          = "Pythonia ({0}) ei löydy. Asenna Python 3.10 tai uudempi (python.org, valitse 'Add to PATH') ja yritä uudelleen."
        venv               = "==> Luodaan Python-ympäristö..."
        deps               = "==> Asennetaan riippuvuudet ({0})..."
        pip_failed         = "Riippuvuuksien asennus epäonnistui. Tarkista verkkoyhteys ja yritä uudelleen."
        no_env             = "device.env puuttuu, joten paketti on rikki. Tee paketti uudelleen (tools/make_relay_package.py)."
        starting           = "[{0}] Käynnistetään relay, loki: {1}"
        stopped            = "[{0}] Relay pysähtyi (koodi {1}). Uusi käynnistys 10 sekunnin kuluttua (Ctrl-C lopettaa)."

        title              = "==> EFDI TAK -relay: asennus"
        choice             = "Valinta"
        invalid            = "Virheellinen valinta, yritä uudelleen."
        bundle_title       = "EFDI-varmennepakettia ei löytynyt tästä kansiosta."
        bundle_prompt      = "Varmennepaketin polku (kansio, .zip tai .tar.gz)"
        bundle_bad         = "Polusta ei löytynyt yhtä varmennetta ja avainta (<slot>-cert.pem, <slot>-key.pem): {0}"
        bundle_copied      = "==> Varmenne kopioitu: {0}"
        system_note        = "Laitteen nimi näkyy EFDI-portaalissa, ja se pitää rekisteröidä portaaliin."
        system_prompt      = "Laitteen nimi (pienet kirjaimet, numerot ja väliviivat)"
        system_bad         = "Nimessä saa olla 3–63 merkkiä: pieniä kirjaimia, numeroita ja väliviivoja."
        too_many_tries     = "Liian monta virheellistä vastausta. Asennus keskeytettiin."
        mode_title         = "Miten TAK-laitteet saavat backbonen tilannekuvan?"
        mode_1             = "  1) Suora        TAK-ohjelma tällä koneella tai nimetyissä laitteissa. TAKiin asetetaan yksi tuloportti."
        mode_2             = "  2) Lähiverkko   Kaikki saman lähiverkon TAK-laitteet saavat tilannekuvan ilman asetuksia.`n                  Vain suljettuun omaan verkkoon: tilannekuva näkyy kaikille verkossa oleville."
        mode_3             = "  3) TAK Server   Relay syöttää organisaation TAK Serveriä, ja kaikki serverin käyttäjät näkevät tilannekuvan."
        mode_direct        = "suora"
        mode_multicast     = "lähiverkko"
        mode_server        = "TAK Server"
        mode_set           = "==> Tila: {0}"
        srv_hint           = "Tarvitset TAK Serverin ylläpitäjältä relaylle asiakasvarmenteen (.p12) ja truststoren (.p12). Voit kopioida ne kansioon certs\tak\."
        srv_address        = "TAK Serverin osoite (esim. tak.example.org tai tak.example.org:8089)"
        srv_p12            = "Relayn asiakasvarmenne (.p12)"
        srv_trust          = "TAK Serverin truststore (.p12)"
        srv_password       = "Varmenteen salasana"
        srv_missing_file   = "Tiedostoa ei löydy: {0}"
        mc_warning         = "Huom: lähiverkkotilassa backbonen tilannekuva näkyy kaikille samassa verkossa oleville."
        mc_uids            = "Laitteet, joiden oman sijainnin saa julkaista backboneen (uidit pilkulla erotettuina, Enter = ei yhdenkään)"
        share_title        = "Jaetaanko näiden TAK-laitteiden merkit ja piirrokset backboneen?"
        share_1            = "  1) Ei      Merkit ja piirrokset pysyvät TAK-verkossa."
        share_2            = "  2) Kyllä   Kaikki CoT-merkit ja piirrokset, myös vihollismerkit, näkyvät muille organisaatioille. Viestejä ei jaeta koskaan."
        share_set_0        = "==> Merkkien ja piirrosten jako: pois päältä"
        share_set_1        = "==> Merkkien ja piirrosten jako: päällä"
        deps_ok            = "==> Riippuvuudet kunnossa."
        perms              = "==> Kansio rajattu tälle käyttäjälle, SYSTEMille ja järjestelmänvalvojille."
        perms_failed       = "Kansion oikeuksia ei voitu rajata. Muut koneen käyttäjät voivat ehkä lukea yksityisen avaimen."
        removing_old_task  = "==> Poistetaan vanha ajastettu tehtävä ({0})..."
        task_system        = "==> Rekisteröidään tehtävä, joka käynnistyy laitteen käynnistyessä (SYSTEM, vaatii järjestelmänvalvojan oikeudet)..."
        task_logon         = "==> Rekisteröidään tehtävä, joka käynnistyy, kun kirjaudut sisään..."
        task_system_failed = "Ajastetun tehtävän luonti epäonnistui. Avaa PowerShell järjestelmänvalvojana ja yritä uudelleen."
        task_fallback      = "==> Tämän tilin oikeudet eivät salli ajastettua tehtävää. Käytetään Käynnistys-kansiota."
        shortcut_made      = "==> Pikakuvake luotu: {0} (käynnistyy jokaisella kirjautumisella, ei vaadi järjestelmänvalvojan oikeuksia)"
        starting_now       = "==> Käynnistetään relay nyt..."
        waiting            = "==> Odotetaan relayn käynnistymistä..."
        healthy            = "==> Relay on käynnissä ja kunnossa."
        not_healthy        = "==> Relay käynnistyi, mutta ei ole vielä kunnossa: {0}"
        not_healthy_hint   = "    Tavallisin syy on puuttuva NetBird-yhteys. Tarkista komennolla 'netbird status'."
        no_answer          = "==> Relay ei vielä vastaa portissa {0}. Ensimmäinen käynnistys voi kestää hetken."
        done               = "Asennus valmis."
        autostart_task     = "Automaattinen käynnistys: ajastettu tehtävä ({0})."
        autostart_startup  = "Automaattinen käynnistys: pikakuvake Käynnistys-kansiossa ({0})."
        restart_note       = "Relay käynnistyy itse uudelleen, jos se kaatuu tai yhteys katkeaa pitkäksi aikaa."
        next_title         = "Seuraavaksi TAK-ohjelmaan:"
        next_direct        = "  Aseta CoT-tuloksi UDP-portti {0} tai TCP-yhteys 127.0.0.1:{1}."
        next_direct_pli    = "  Oman sijainnin lähetys backboneen: TAK-ohjelman UDP-lähtö osoitteeseen 127.0.0.1:{0}."
        next_multicast     = "  Ei asetettavaa. Tilannekuva tulee TAKin oletusosoitteeseen (SA multicast {0})."
        next_server        = "  Ei asetettavaa. Laitteet saavat tilannekuvan TAK Serveriltä."
        status_page        = "Tilasivu:     {0}"
        doctor_hint        = "Vianetsintä:  .\run.ps1 -CheckOnly"
        uninstall_hint     = "Poisto:       uninstall.cmd"

        task_removed       = "Ajastettu tehtävä {0} poistettu."
        task_missing       = "Ajastettua tehtävää {0} ei löytynyt."
        shortcut_removed   = "Käynnistys-kansion pikakuvake poistettu ({0})."
        shortcut_missing   = "Käynnistys-kansion pikakuvaketta ei löytynyt."
        stopping_loop      = "Pysäytetään käynnistyssilmukka (PID {0})..."
        stopping_relay     = "Pysäytetään relay (PID {0})..."
        uninstall_done     = "Poisto valmis. Kansio jätettiin paikalleen; poista se itse, jos et tarvitse sitä."
    }
    en = @{
        no_python          = "Python ({0}) not found. Install Python 3.10 or newer (python.org, tick 'Add to PATH') and try again."
        venv               = "==> Creating the Python environment..."
        deps               = "==> Installing dependencies ({0})..."
        pip_failed         = "Installing the dependencies failed. Check the network connection and try again."
        no_env             = "device.env is missing, so the package is broken. Build it again (tools/make_relay_package.py)."
        starting           = "[{0}] Starting the relay, log: {1}"
        stopped            = "[{0}] The relay stopped (code {1}). Restarting in 10 seconds (Ctrl-C stops)."

        title              = "==> EFDI TAK relay: installation"
        choice             = "Choice"
        invalid            = "Invalid choice, try again."
        bundle_title       = "No EFDI certificate bundle found in this folder."
        bundle_prompt      = "Path to the certificate bundle (folder, .zip or .tar.gz)"
        bundle_bad         = "No single certificate and key (<slot>-cert.pem, <slot>-key.pem) found at: {0}"
        bundle_copied      = "==> Certificate copied: {0}"
        system_note        = "The device name is shown in the EFDI portal and must be registered there."
        system_prompt      = "Device name (lower-case letters, digits and hyphens)"
        system_bad         = "The name must be 3-63 characters: lower-case letters, digits and hyphens."
        too_many_tries     = "Too many invalid answers. Installation stopped."
        mode_title         = "How do the TAK devices get the backbone picture?"
        mode_1             = "  1) Direct       A TAK app on this machine or on named devices. TAK needs one input port."
        mode_2             = "  2) Local network Every TAK device on the same LAN gets the picture without any settings.`n                  Only on a closed network of your own: everyone on the network sees the picture."
        mode_3             = "  3) TAK Server   The relay feeds your organisation's TAK Server, and every user on it sees the picture."
        mode_direct        = "direct"
        mode_multicast     = "local network"
        mode_server        = "TAK Server"
        mode_set           = "==> Mode: {0}"
        srv_hint           = "Ask the TAK Server administrator for a client certificate (.p12) and a truststore (.p12) for the relay. You can copy them to certs\tak\."
        srv_address        = "TAK Server address (e.g. tak.example.org or tak.example.org:8089)"
        srv_p12            = "Relay client certificate (.p12)"
        srv_trust          = "TAK Server truststore (.p12)"
        srv_password       = "Certificate password"
        srv_missing_file   = "File not found: {0}"
        mc_warning         = "Note: in local-network mode everyone on the same network sees the backbone picture."
        mc_uids            = "Devices whose own position may be published to the backbone (uids, comma-separated, Enter = none)"
        share_title        = "Share the markers and drawings of these TAK devices to the backbone?"
        share_1            = "  1) No      Markers and drawings stay on the TAK network."
        share_2            = "  2) Yes     Every CoT marker and drawing, hostile ones too, is shown to other organisations. Messages are never shared."
        share_set_0        = "==> Sharing markers and drawings: off"
        share_set_1        = "==> Sharing markers and drawings: on"
        deps_ok            = "==> Dependencies ready."
        perms              = "==> Folder limited to this user, SYSTEM and Administrators."
        perms_failed       = "Could not limit the folder permissions. Other users of this machine may be able to read the private key."
        removing_old_task  = "==> Removing the old scheduled task ({0})..."
        task_system        = "==> Registering a task that starts with the machine (SYSTEM, needs administrator rights)..."
        task_logon         = "==> Registering a task that starts when you sign in..."
        task_system_failed = "Creating the scheduled task failed. Open PowerShell as administrator and try again."
        task_fallback      = "==> This account may not create scheduled tasks. Using the Startup folder instead."
        shortcut_made      = "==> Shortcut created: {0} (starts at every sign-in, no administrator rights needed)"
        starting_now       = "==> Starting the relay now..."
        waiting            = "==> Waiting for the relay to start..."
        healthy            = "==> The relay is running and healthy."
        not_healthy        = "==> The relay started but is not healthy yet: {0}"
        not_healthy_hint   = "    The usual cause is a missing NetBird connection. Check with 'netbird status'."
        no_answer          = "==> The relay does not answer on port {0} yet. The first start can take a moment."
        done               = "Installation complete."
        autostart_task     = "Automatic start: scheduled task ({0})."
        autostart_startup  = "Automatic start: shortcut in the Startup folder ({0})."
        restart_note       = "The relay restarts by itself if it crashes or the connection is lost for a long time."
        next_title         = "Next, in the TAK app:"
        next_direct        = "  Set the CoT input to UDP port {0}, or a TCP connection to 127.0.0.1:{1}."
        next_direct_pli    = "  To send your own position to the backbone: the TAK app's UDP output to 127.0.0.1:{0}."
        next_multicast     = "  Nothing to set. The picture arrives on TAK's default address (SA multicast {0})."
        next_server        = "  Nothing to set. Devices get the picture from the TAK Server."
        status_page        = "Status page:      {0}"
        doctor_hint        = "Troubleshooting:  .\run.ps1 -CheckOnly"
        uninstall_hint     = "Uninstall:        uninstall.cmd"

        task_removed       = "Scheduled task {0} removed."
        task_missing       = "Scheduled task {0} not found."
        shortcut_removed   = "Startup folder shortcut removed ({0})."
        shortcut_missing   = "No Startup folder shortcut found."
        stopping_loop      = "Stopping the launcher loop (PID {0})..."
        stopping_relay     = "Stopping the relay (PID {0})..."
        uninstall_done     = "Uninstall complete. The folder was left in place; delete it yourself if you no longer need it."
    }
}

function T([string]$Key) {
    $lang = if ($env:RELAY_LANG -eq "en") { "en" } else { "fi" }
    $text = $Messages[$lang][$Key]
    if ($null -eq $text) { return $Key }
    if ($args.Count -gt 0) { return ($text -f $args) }
    return $text
}

function Read-DeviceEnv([string]$Path) {
    # KEY=value lines (comments and empty values skipped) -> hashtable
    $values = @{}
    if (Test-Path $Path) {
        Get-Content $Path | ForEach-Object {
            if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$' -and $Matches[2] -ne '') {
                $values[$Matches[1]] = $Matches[2]
            }
        }
    }
    return $values
}

function Import-DeviceEnv([string]$Path) {
    $values = Read-DeviceEnv $Path
    foreach ($k in $values.Keys) { Set-Item -Path "Env:$k" -Value $values[$k] }
}
