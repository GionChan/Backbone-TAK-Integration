# EFDI TAK -relay: {system}

**In English:** README.en.md

Tämä paketti yhdistää laitteen EFDI-backboneen ja tuo backbonen tilannekuvan TAK-ohjelmiin.
Asennin ottaa tarvittavat ohjelmat käyttöön ja asettaa relayn käynnistymään automaattisesti.

## Ennen asennusta

1. Liitä laite EFDI:n NetBird-verkkoon (`netbird status` → Management ja Signal: Connected).
2. Järjestelmänimen `{system}` pitää olla rekisteröity EFDI-portaaliin. Muuten heartbeat näkyy
   tuntemattomana, mutta data kulkee silti.
3. Jos valitset TAK Server -tilan, pyydä TAK Serverin ylläpitäjältä relaylle asiakasvarmenne
   (.p12) ja truststore (.p12) ja kopioi ne kansioon `certs\tak\`.

## Asennus

Pura zip mihin tahansa kansioon ja kaksoisnapsauta `install.cmd`. Jos Windows varoittaa
("Windows protected your PC"), valitse "More info" → "Run anyway".

Asennin kysyy:

1. **Kielen:** suomi tai englanti.
2. **Tilan:**

| Tila | Kenelle | Mitä TAKiin asetetaan | Kuka näkee tilannekuvan |
| --- | --- | --- | --- |
| 1 Suora | Tämä kone tai muutama nimetty laite | Yksi tuloportti (UDP {tak_udp_port} tai TCP {tak_port}) | Vain asetetut laitteet |
| 2 Lähiverkko | Suljettu oma verkko, esim. ajoneuvon Wi-Fi | Ei mitään | Kaikki samassa verkossa |
| 3 TAK Server | Organisaatio, jolla on TAK Server | Ei mitään | Kaikki serverin käyttäjät |

3. **Tilan lisätiedot:** TAK Server -tilassa serverin osoitteen, varmenteet ja salasanan.
   Lähiverkkotilassa ne laitteet, joiden oman sijainnin saa julkaista backboneen.

Lopuksi asennin käynnistää relayn, tarkistaa sen tilan ja kertoo, mitä TAK-ohjelmaan pitää
asettaa. Valinnat tallentuvat tiedostoon `device.env`.

Laitteelle, jolle kukaan ei kirjaudu (kioski tai palvelin): `install.cmd -AtSystemStartup`
järjestelmänvalvojana. Relay käynnistyy silloin laitteen käynnistyessä.

## Käytön aikana

- **Tilasivu:** <http://127.0.0.1:8088/> näyttää, onko relay kunnossa, ja jos ei ole, miksi.
- **Vianetsintä:** `.\run.ps1 -CheckOnly` tarkistaa varmenteet, NetBirdin, yhteydet ja portit ja
  kertoo jokaiseen virheeseen korjauksen.
- **Lokit:** `logs\relay-VVVVKKPP.log`.

## Asetusten muuttaminen

Muokkaa `device.env`-tiedostoa tai poista siitä rivit `TAK_MODE` ja `RELAY_LANG`, jolloin asennin
kysyy ne uudelleen. Aja sitten `uninstall.cmd` ja `install.cmd`.

Backboneen julkaistaan vain omien laitteiden sijainnit ja vain, kun `TAK_INGEST=1`. TAK Serverin
muiden käyttäjien sijainteja ei julkaista koskaan.

## Poisto

`uninstall.cmd` poistaa automaattisen käynnistyksen ja pysäyttää relayn. Kansio jää paikalleen.

## Tietoturva

Kansiossa `certs\` on organisaation yksityinen avain, ja `device.env` voi sisältää TAK Server
-varmenteen salasanan. Älä jaa pakettia tai kansiota eteenpäin.
