# Vianetsintä

**In English:** [../en/troubleshooting.md](../en/troubleshooting.md)

Aloita komennolla `python relay/doctor.py` (Dockerissa `docker compose exec tak-relay python3
relay/doctor.py`, kenttäpaketissa `.\run.ps1 -CheckOnly`). Se tarkistaa bundlen, slotin,
varmenteen voimassaolon, NetBirdin, reitittimen, portit ja TAK Serverin, ja kertoo jokaiseen
virheeseen korjauksen.

Käynnissä olevan relayn tila näkyy osoitteessa <http://localhost:8088/>. `/status` antaa saman
JSON-muodossa: `reasons` kertoo, mikä on vialla, ja `counters` näyttää, minne viestit menevät
(`*_in_total`, `*_sent_total`, `*_dropped_total{reason=…}`).

| Oire | Todennäköinen syy | Korjaus |
| --- | --- | --- |
| `fabric link down`, `/healthz` 503 | Mesh alhaalla tai reititin ei vastaa | `netbird status`: Management ja Signal yhdistettyinä, nimipalvelimet 1/1. `goat doctor` |
| Reitittimen nimi ei ratkea | Ei meshissä tai NetBirdin DNS ei ole käytössä | Yhdistä NetBird uudelleen. Docker Desktopissa aseta `EFDI_ROUTER_IP` (mesh-IP isännän `nslookup`-komennolla) |
| Lokissa toistuu `fabric unavailable (…)` | Vanhentunut tai väärä sertifikaatti, väärä reititin | `goat profile show`; tarkista `certs/`-kansion bundle; aseta `GOAT_ROUTER` bundlen mukaan |
| Päättyy virheeseen `cannot determine the org slot` | Sertifikaatin CN ei ole slot | Aseta `GOAT_ORG=<slotin tunniste>` |
| `need exactly one … pair` tai bundlea ei löydy | Hakemistossa on useita identiteettejä | Pidä yksi sertifikaatti- ja avainpari hakemistoa kohden tai aseta `GOAT_CERT`/`GOAT_KEY`/`GOAT_CA` |
| Julkaisu "onnistuu", mutta kukaan ei saa viestiä | Avain on oman slotin ulkopuolella (hylätään hiljaa) | Julkaise vain polkuun `<slot>/…`; tarkista komennolla `goat flow <avain>` |
| `/status` terve, mutta TAK ei näytä mitään | Väärä UDP-kohde, palomuuri tai TAK-tulo pois päältä | Dockerissa käytä osoitetta `host.docker.internal`, ei `127.0.0.1`. Avaa TAK-tulon portti. Tarkista `gateway_output_sent_total` |
| Merkit ilmestyvät ja katoavat | Lähde lähettää vanhentuneita aikaleimoja tai kello on väärässä | Tarkista `gateway_cot_dropped_total{reason="already-stale"}`; synkronoi kello (NTP) |
| `no backbone samples for …` | Tilatuilla avaimilla ei julkaista mitään | `GATEWAY_INGEST_ALL=1` näyttää kaikki valmistajat; katso `/streams` |
| ATAK-yhteys katkeaa | Asiakas ei lukenut dataa 10 sekuntiin | Tarkoituksellinen suojaus; tarkista asiakkaan verkko |
| `port is already allocated` | Jokin muu prosessi käyttää porttia 8087, 8088, 6971, 8554, 8080 tai 7447 | Pysäytä se tai vaihda porttimäärityksen isäntäpuoli |
| `output tcp_client:… not connected` | TAK Server ei vastaa tai hylkää varmenteen | `doctor.py` kertoo syyn; tarkista `TAK_SERVER_P12`, truststore ja `TAK_SERVER_VERIFY_HOSTNAME` |
| Käynnistyksessä `cannot open .p12 (wrong password?)` | Väärä `TAK_SERVER_P12_PASSWORD` | Korjaa salasana. Truststore käyttää samaa salasanaa, ellei `TAK_SERVER_TRUST_PASSWORD` ole asetettu |
| PLI:tä ei julkaista, `reason="not-local"` / `"not-loopback"` / `"not-allowed"` / `"echo"` | Tarkoituksellista: TAK Serverin käyttäjät, muiden koneiden laitteet (Dockerissa myös isäntä) ilman `TAK_INGEST_UIDS`-listaa, listan ulkopuoliset uidit, relayn itse lähettämät merkit | Lisää laitteen uid muuttujaan `TAK_INGEST_UIDS` |
| `PermissionError` avaimelle (Linux) | Kontti ajetaan käyttäjänä UID 10001 | `chmod 640` avaimelle ja lukuoikeus ryhmälle 10001, tai `user: "0"` palvelulle |
| Heartbeat ei näy portaalissa | Järjestelmänimeä ei ole rekisteröity | `python tools/register_portal_topics.py --add-system <nimi> --apply` |
| Kenttälaite: automaattinen käynnistys puuttuu | Ajastetut tehtävät estetty käytännöllä | Asennus käyttää silloin Käynnistys-kansiota; tarkista asennuksen tuloste |
