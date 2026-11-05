# EFDI TAK -relay: {system} (Linux)

**In English:** README.en.md

Tämä paketti yhdistää laitteen EFDI-backboneen ja tuo backbonen tilannekuvan TAK-laitteisiin.
Riippuvuudet x86_64- ja aarch64-koneille ovat mukana, joten asennus ei tarvitse verkkoyhteyttä.
Asennin asettaa relayn käynnistymään automaattisesti.

Tarvitaan: Linux, jossa on glibc 2.28 tai uudempi (esim. Debian 10+, Ubuntu 20.04+ tai 64-bittinen
Raspberry Pi OS), Python 3.10 tai uudempi venv-moduulin kanssa (`sudo apt install python3
python3-venv`) sekä bash.

## Ennen asennusta

1. Liitä laite EFDI:n NetBird-verkkoon (`netbird status` → Management ja Signal: Connected).
2. Järjestelmänimen `{system}` pitää olla rekisteröity EFDI-portaaliin. Muuten heartbeat näkyy
   tuntemattomana, mutta data kulkee silti.
3. Jos valitset TAK Server -tilan, pyydä TAK Serverin ylläpitäjältä relaylle asiakasvarmenne
   (.p12) ja truststore (.p12) ja kopioi ne kansioon `certs/tak/`.

## Asennus

Pura paketti ja aja asennin sillä käyttäjällä, joka ajaa relayta (ei pääkäyttäjänä):

```bash
tar -xzf <paketti>.tar.gz && cd <kansio>
./install.sh             # käynnistyy, kun kirjaudut sisään (käyttäjän systemd-palvelu)
./install.sh --at-boot   # käynnistyy koneen mukana; pyytää sudo-oikeutta vain palvelun asentamiseen
```

Jos tämä on julkaisun pohjapaketti, asennin kysyy ensin EFDI-varmennepaketin (kansio, `.zip`
tai `.tar.gz`) ja laitteen nimen. Sen jälkeen se kysyy:

1. **Kielen:** suomi tai englanti.
2. **Tilan:**

| Tila | Kenelle | Mitä TAKiin asetetaan | Kuka näkee tilannekuvan |
| --- | --- | --- | --- |
| 1 Suora | Nimetyt laitteet (UDP) sekä ATAK ja WinTAK TCP:llä {tak_port} | Relayn osoite | Vain asetetut laitteet |
| 2 Lähiverkko | Suljettu oma verkko | Ei mitään | Kaikki samassa verkossa |
| 3 TAK Server | Organisaatio, jolla on TAK Server | Ei mitään | Kaikki serverin käyttäjät |

3. **Tilan lisätiedot:** suorassa tilassa minne CoT lähtee UDP:llä ja minkä muiden laitteiden
   oman sijainnin saa julkaista; TAK Server -tilassa serverin osoitteen, varmenteet ja salasanan;
   lähiverkkotilassa ne laitteet, joiden oman sijainnin saa julkaista.

Ilman uid-listaa backboneen saavat julkaista sijaintinsa vain tämän koneen TAK-sovellukset. TAK
Serverin käyttäjien sijainteja ei julkaista koskaan.

Asennin rajaa varmenteet ja `device.env`-tiedoston vain tämän käyttäjän luettaviksi. Jos
systemd:tä ei ole, asennin lisää crontabiin `@reboot`-rivin.

## Käytön aikana

- **Tilasivu:** <http://127.0.0.1:8088/> (vain tällä koneella).
- **Vianetsintä:** `./run.sh --check-only` tarkistaa varmenteet, NetBirdin, yhteydet ja portit ja
  kertoo jokaiseen virheeseen korjauksen.
- **Lokit:** `logs/relay-VVVVKKPP.log`.
- **Palomuuri:** verkon TAK-laitteiden pitää tavoittaa TCP-portti {tak_port} ja UDP-portti 6971
  (suora tila) tai multicast-ryhmä (lähiverkko).

## Asetusten muuttaminen

Muokkaa `device.env`-tiedostoa tai poista siitä rivit `TAK_MODE` ja `RELAY_LANG`, jolloin asennin
kysyy ne uudelleen. Aja sitten `./uninstall.sh` ja `./install.sh`.

## Poisto

`./uninstall.sh` poistaa automaattisen käynnistyksen ja pysäyttää relayn. Kansio jää paikalleen.

## Tietoturva

Kansiossa `certs/` on organisaation yksityinen avain, ja `device.env` voi sisältää TAK Server
-varmenteen salasanan. Älä jaa pakettia tai kansiota eteenpäin.
