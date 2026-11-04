# Valitse tila

**In English:** [../en/modes.md](../en/modes.md)

`TAK_MODE` ratkaisee, miten TAK-laitteet saavat backbonen tilannekuvan. Valitse yksi tila
relayta kohden:

1. **Onko teillä TAK Server?** → `server`
2. **Onko verkko suljettu ja vain teidän käytössänne?** → `multicast`
3. **Muuten** → `direct` (oletus)

| | `direct` (suora) | `multicast` (lähiverkko) | `server` (TAK Server) |
| --- | --- | --- | --- |
| **Kenelle** | Tämä kone tai muutama nimetty laite | Suljettu oma lähiverkko | Organisaatio, jolla on TAK Server |
| **Mitä TAKiin asetetaan** | Yksi tuloportti: UDP 6969, 4242 (WinTAK) tai TCP 8087 | Ei mitään | Ei mitään, laitteet ovat jo serverillä |
| **Kuka näkee backbonen** | Vain asetetut laitteet | **Kaikki samassa verkkosegmentissä** | Kaikki serverin käyttäjät |
| **Kenen sijainti julkaistaan** (`TAK_INGEST=1`) | Paikalliset laitteet (tai `TAK_INGEST_UIDS`) | Vain `TAK_INGEST_UIDS`-listan uidit | Ei kenenkään oletuksena |
| **Docker** | Kyllä | Vain Linuxin isäntäverkossa | Kyllä |
| **Pakolliset asetukset** | – | – | `TAK_SERVER` ja sen .p12-tiedostot |

## direct

CoT lähtee UDP:llä kohteisiin `TAK_UDP_TARGETS` (tai `TAK_HOST:TAK_UDP_PORT`), ja ATAK tai WinTAK
voi yhdistää TCP-palvelimeen portissa `TAK_PORT` (8087). Tilannekuvan saavat vain laitteet,
jotka on ohjattu relayhin. Toimii kaikkialla, myös Docker Desktopissa.

## multicast

CoT lähtee TAKin SA multicast -ryhmään `239.2.3.1:6969`, jota ATAK, WinTAK ja iTAK kuuntelevat
oletuksena, joten TAKiin ei tarvitse asettaa mitään. TCP-palvelin portissa `TAK_PORT` pysyy päällä
laitteille, jotka eivät voi käyttää multicastia.

- **Jokainen samassa verkkosegmentissä saa backbonen tilannekuvan.** Käytä tilaa vain suljetussa
  omassa verkossa, ei koskaan toimistoverkossa tai jaetussa Wi-Fissä.
- Relay kuulee ryhmästä myös jokaisen laitteen oman sijainnin. Niistä julkaistaan vain
  `TAK_INGEST_UIDS`-listan uidit. Ilman listaa lähiverkosta kuultuja sijainteja ei julkaista.
- Multicast pysyy omassa segmentissään (`TAK_MULTICAST_TTL=1`), ja monet Wi-Fi- ja yritysverkot
  estävät sen. Jos koneessa on useita verkkoja (NetBird, Wi-Fi, Ethernet), aseta
  `TAK_MULTICAST_IF`-muuttujaan lähiverkon IPv4-osoite.
- Docker: `docker compose -f docker-compose.yml -f docker-compose.multicast.yml up -d`
  Linux-isännällä. Docker Desktop (Mac, Windows) ei välitä multicastia; käytä siellä kenttäpakettia.

| Muuttuja | Oletus | Merkitys |
| --- | --- | --- |
| `TAK_MULTICAST_GROUP` | `239.2.3.1:6969` | Ryhmä ja portti |
| `TAK_MULTICAST_IF` | käyttöjärjestelmän valinta | Lähiverkon verkkokortin IPv4-osoite |
| `TAK_MULTICAST_TTL` | `1` | Reitittimien määrä; 1 = vain tämä segmentti |

## server

Relay lähettää virran TAK Serverille (`TAK_SERVER`, ks. [relay: TAK Server](relay.md#tak-server)),
ja jokainen serverin käyttäjä näkee backbonen. Yksi relay TAK Serveriä kohden riittää.

- Paikalliset UDP- ja TCP-lähdöt ovat pois päältä, jotta serverin laitteet eivät saa jokaista
  merkkiä kahdesti. `TAK_LOCAL_OUTPUTS=1` kytkee ne takaisin.
- TAK Serverin käyttäjien sijainteja ei julkaista backboneen, ellei asetuksena ole
  `TAK_INGEST_FROM=local,server`.
- Relay ei käynnisty ilman `TAK_SERVER`-asetusta.

## Kaikissa tiloissa

- Jokaisen relayn lähettämän CoT-viestin `<detail>`-osassa on `<__efdi_relay/>`. Mikään relay ei
  julkaise tällä merkinnällä varustettua tapahtumaa, joten kaksi relayta samassa lähiverkossa tai
  samalla TAK Serverillä ei voi kierrättää merkkejä takaisin backboneen
  (`gateway_ingest_dropped_total{reason="relayed"}`).
- `TAK_SERVER` voidaan lisätä myös `direct`- ja `multicast`-tiloihin, jos halutaan syöttää lisäksi
  TAK Serveriä.
- `python relay/doctor.py` tarkistaa valitun tilan: puuttuvan `TAK_SERVER`-asetuksen,
  multicast-ryhmään liittymisen ja TAK Server -yhteyden.
- Tilasivu (`:8088/`) ja `/status` näyttävät tilan.

## Valinnan tekeminen

| Missä | Miten |
| --- | --- |
| Kenttäpaketti | `install.cmd` kysyy ensin kielen, sitten tilan ja sen lisätiedot. Valmiiksi valittuna: `make_relay_package.py --lang fi --mode server …` |
| Docker | `TAK_MODE=…` tiedostoon `.env`; multicast tarvitsee lisäksi `docker-compose.multicast.yml`-tiedoston |
| Natiivisti | `TAK_MODE=… python relay/tak_gateway.py` |

## Varmistettu

`direct` on varmistettu oikeaa fabricia ja TAK-asiakkaita vasten. `multicast` on testattu oikealla
multicast-liikenteellä loopback-liitännässä ja `server` paikallista TLS-palvelinta ja
asiakasvarmennetta vasten. Kumpaakaan ei ole vielä testattu oikeilla TAK-laitteilla tai oikealla
TAK Serverillä.
