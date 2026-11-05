# Yleiskuva

**In English:** [../en/overview.md](../en/overview.md)

## Ongelma

EFDI-kumppanit jakavat sensoridataa **goat-fabricin** kautta. Se on dataverkko, jossa jokainen
organisaatio julkaisee omaan namespaceensa ja lukee muiden julkaisemaa dataa. Käyttäjät
seuraavat tilannetta **TAK**-sovelluksissa (WinTAK, ATAK ja muut CoT-sovellukset), jotka puhuvat
eri kieltä: Cursor on Target (CoT). Näiden väliin tarvitaan jotain, joka kääntää viestit ja
pitää virheellisen datan poissa. Se on TAK-relay.

## Miten data kulkee

Ajattele fabricia postitoimistona, jossa on nimetyt postilokerot. Lähettäjä pudottaa kirjeen
lokeroon `<org>/sensor/v1/uav-1`, ja jokainen, jolla on lukuoikeus, saa siitä kopion. Relay
tilaa sille tärkeät lokerot, kirjoittaa jokaisen kirjeen CoT-muotoon ja välittää sen
TAK-sovelluksille.

```text
 Muut valmistajat       Omat sensorit         Demoskenaariot (harjoitusmerkityt)
      │                      │                          │
      └──────── EFDI goat -fabric (Zenoh, mTLS, NetBird WireGuard -mesh) ──────┘
                                   │
                         ┌─────────▼──────────┐
                         │     TAK-relay      │  relay/tak_gateway.py
                         │ muunna → tarkista  │
                         │ → rajoita → jaa    │
                         └──┬──────┬───────┬──┘
                 UDP 6969/4242   TCP 8087   RTSP 8554 (video)
                  UDP-sovellukset ATAK        TAK "Play Video"
                    WinTAK        WinTAK
```

Polun suojaa neljä kerrosta:

1. **NetBird ja WireGuard** muodostavat salatun meshin osallistujien koneiden välille. Ilman
   sitä fabricin reititintä ei edes tavoiteta.
2. **mTLS:** molemmat osapuolet esittävät sertifikaatin. Sertifikaatin nimi on **slot**
   (32-merkkinen heksatunniste), ja fabric sallii kirjoittamisen vain polkuun `<slot>/**`.
   Muualle kirjoitetut viestit hylätään ilman virheilmoitusta.
3. **Zenoh** kuljettaa viestit (julkaisu ja tilaus avainlausekkeilla, kuten `*/tak/cot/v1/**`).
4. **CoT** on TAKin ymmärtämä muoto: XML-muotoinen `<event>`, jossa on sijainti, tyyppi (oma,
   vihollinen, ilma, maa…) ja aika, jonka jälkeen merkki vanhenee.

## Mitä relay tekee viestille

1. **Tunnistaa** muodon: CoT-XML, `goat.geo.track.v1`, MAVLink, ADS-B, protobuf-radat,
   valmistajakohtaiset ratamuodot ([koko luettelo](relay.md#tunnistetut-muodot)) tai oma
   JSON-telemetria. Tuntemattomat muodot lasketaan ja ohitetaan.
2. **Muuntaa** viestin CoT-muotoon ja päättelee merkin tyypin (osapuoli ja ulottuvuus), jos
   lähde ei kerro sitä.
3. **Tarkistaa:** XML on ehjää, DTD:tä ei ole, koordinaatit ovat sallitulla alueella, merkki ei
   ole jo vanhentunut ja koko on alle 64 KiB. Muiden valmistajien CoT välitetään sellaisenaan
   vasta tämän tarkistuksen jälkeen.
4. **Rajoittaa** tahtia jäljittäin ja poistaa kaksoiskappaleet, jotka saapuvat usean avaimen
   kautta.
5. **Jakaa** viestin jokaiseen ulostuloon. Hidas TAK-asiakas menettää vain omat viestinsä eikä
   voi pysäyttää muita.

Toiseen suuntaan (valinnainen) omien TAK-käyttäjien sijainnit julkaistaan polkuun
`<slot>/tak/pli/v1/<uid>` ja heidän tekemänsä merkit ja piirrokset polkuun
`<slot>/tak/cot/v1/<uid>`, jolloin muut osallistujat näkevät ne. Viestejä ei julkaista koskaan.

## Tuote ja demo

Repossa on kaksi toisistaan erotettua kokonaisuutta:

- **Relay** (`relay/`) on se, mikä otetaan käyttöön. Se lukee oikeaa backbone-dataa.
- **Demo** (`demo/`) näyttää relayn toiminnan. Skenaariot laskevat lentoreitit, ja **demon
  lähetin** (`demo/sender.py`) julkaisee ne polkuun `<slot>/exercise/<skenaario>/v1/<uid>` ja
  CoT-merkin polkuun `<slot>/tak/cot/v1/EXERCISE.<uid>`. Jokaisessa demoviestissä lukee
  `"classification": "SIMULATED"`, ja jokaisen merkin kutsutunnus alkaa sanalla `EXERCISE`.
  Demodataa ei koskaan julkaista polkuun `<slot>/sensor/v1/**`, jossa on oikea telemetria.

Demo käyttää tarkoituksella samaa polkua kuin oikea data: sen merkit kulkevat TAKiin relayn
kautta, eivät sivukanavaa pitkin.

## Sanasto

| Termi | Merkitys |
| --- | --- |
| Fabric, backbone | EFDI goat -dataverkko (Zenoh-reitittimet meshin takana) |
| Slot, org | Identiteetti fabricissa: sertifikaatin CN, samalla oma kirjoitusnamespace |
| Bundle | Onboarding-tiedostot: `<etuliite>-cert.pem`, `<etuliite>-key.pem`, `efdi-ca-root.pem` |
| CoT | Cursor on Target, TAKin käyttämä XML-tapahtumamuoto |
| PLI | Position location information: TAK-käyttäjän oma sijainti |
| Heartbeat | Pakollinen `<slot>/<järjestelmä>/heartbeat/v1`-viesti 60 sekunnin välein |
| Vanheneminen (stale) | Aika, jonka jälkeen TAK poistaa päivittymättömän merkin |
