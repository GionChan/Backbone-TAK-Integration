"""Choose the CoT type (tactical symbol) for an object from everything its message says.

CoT type = "a-<affiliation>-<dimension/function suffix>", e.g. a-h-A-M-F-Q (hostile military fixed-wing UAV).
TAK picks the icon from the longest matching prefix, so an over-specific suffix degrades gracefully to its parent.

Evidence, strongest first: an explicit affiliation/dimension field, an APP-6D SIDC, then keywords in
names/labels/types, then kinematics (altitude/speed). Nothing is ever guessed as hostile:
unknown affiliation is "u" unless the data says otherwise.
"""
import re

# affiliation letter from free text
_AFF_WORDS = [
    (re.compile(r"\b(hostile|enemy|opfor|red ?force|redfor|adversary)\b", re.I), "h"),
    (re.compile(r"\b(suspect)\b", re.I), "s"),
    (re.compile(r"\b(friend(ly)?|blue ?force|bluefor|allied?)\b", re.I), "f"),
    (re.compile(r"\b(neutral|civil(ian)?)\b", re.I), "n"),
    (re.compile(r"\b(unknown|unidentified)\b", re.I), "u"),
]
_AFF_NAMES = {"friend": "f", "friendly": "f", "hostile": "h", "neutral": "n", "unknown": "u", "suspect": "s",
              "assumed friend": "a", "pending": "p", "civilian": "n"}
_SIDC_AFF = {"0": "p", "1": "u", "2": "a", "3": "f", "4": "n", "5": "s", "6": "h"}

# APP-6D symbol set (SIDC digits 5-6) -> coarse CoT suffix
_SYMSET = {"01": "A", "02": "A-W-M", "05": "P", "10": "G-U-C", "11": "G-U-C", "15": "G-E", "20": "G-I",
           "27": "G-I", "30": "S", "35": "U", "40": "G-U-C", "50": "G", "60": "G"}

_DIM = {"air": "A", "space": "P", "ground": "G", "land": "G", "surface": "S", "sea": "S", "maritime": "S",
        "subsurface": "U", "subsea": "U", "underwater": "U"}

_UNIT_WORDS = re.compile(r"\b(brigade|battalion|regiment|company|platoon|division|corps|squadron|detachment|"
                         r"group|section|unit|bde|bn|btn|coy|plt|div)\b", re.I)

# (pattern, unit-level suffix or None, equipment/individual-level suffix)
_KEYWORDS = [
    # air
    (r"\b(missile|rocket|munition|loitering)\b", None, "A-W-M"),
    (r"\b(uav|uas|drone|quadcopter|multirotor|quad|hexacopter|rpas|unmanned aerial)\b", "G-U-C-V", "A-M-F-Q"),
    (r"\b(helicopter|helo|rotary|rotor)\b", "G-U-C-V", "A-M-H"),
    (r"\b(fighter|jet|bomber|aircraft|airplane|plane|fixed[- ]wing|awacs|transport aircraft)\b", "G-U-C-V", "A-M-F"),
    (r"\b(balloon|airship)\b", None, "A-M-L"),
    # surface / subsurface
    (r"\b(submarine|sub-?surface|uuv)\b", None, "U-S"),
    (r"\b(frigate|destroyer|corvette|cruiser|carrier|warship|minesweeper|patrol (boat|vessel))\b", None, "S-C-L"),
    (r"\b(ship|vessel|boat|tanker|cargo|ferry|usv|trawler|yacht)\b", None, "S-X"),
    # ground equipment
    (r"\b(tank|mbt|main battle)\b", "G-U-C-A", "G-E-V-A-T"),
    (r"\b(apc|ifv|bmp|btr|armou?red (vehicle|personnel)|infantry fighting)\b", "G-U-C-A", "G-E-V-A-A"),
    (r"\b(howitzer|artillery|mortar|mlrs|rocket launcher|field gun)\b", "G-U-C-F", "G-E-W-H"),
    (r"\b(air defen[sc]e|sam (site|battery)|anti[- ]aircraft)\b", "G-U-C-D", "G-E-W-D"),
    (r"\b(radar)\b", None, "G-E-S-R"),
    (r"\b(ugv|robocar|robot|unmanned ground)\b", None, "G-E-V"),
    (r"\b(truck|lorry|bus|van|vehicle|car|jeep|humvee|convoy)\b", "G-U-S", "G-E-V"),
    # ground units / individuals
    (r"\b(infantry|rifle|jaeger|grenadier|motori[sz]ed|mechani[sz]ed|light infantry|marine)\b", "G-U-C-I", "G-U-C-I"),
    (r"\b(armou?r|cavalry)\b", "G-U-C-A", "G-U-C-A"),
    (r"\b(engineer|sapper|pioneer)\b", "G-U-C-E", "G-U-C-E"),
    (r"\b(recon|reconnaissance|scout|sniper)\b", "G-U-C-R", "G-U-C-R"),
    (r"\b(medical|medic|hospital|ambulance)\b", "G-U-S-M", "G-U-S-M"),
    (r"\b(logistic|supply|service support|maintenance|transport|sustainment|css)\b", "G-U-S", "G-U-S"),
    (r"\b(signal|communications?|command|hq|headquarters|staff)\b", "G-U-U", "G-U-U"),
    (r"\b(special forces|sof|commando)\b", "G-U-C-S", "G-U-C-S"),
    (r"\b(person|people|soldier|pedestrian|personnel|dismount|troop)s?\b", "G-U-C-I", "G-U-C-I"),
]
_KEYWORDS = [(re.compile(p, re.I), unit, eq) for p, unit, eq in _KEYWORDS]


def affiliation(explicit=None, text="", sidc=None, default="u") -> str:
    """Affiliation letter. Explicit field > SIDC > words in text > default (unknown)."""
    if explicit:
        e = str(explicit).strip().lower()
        if e in _AFF_NAMES:
            return _AFF_NAMES[e]
        if len(e) == 1 and e in "pufansh":
            return e
    if sidc and len(str(sidc)) >= 4 and str(sidc)[3] in _SIDC_AFF:
        return _SIDC_AFF[str(sidc)[3]]
    for rx, letter in _AFF_WORDS:
        if rx.search(text or ""):
            return letter
    return default


def suffix(text="", dimension=None, sidc=None, hae=None, speed_mps=None, default_dim="G") -> tuple:
    """(cot suffix, basis) where basis says what decided it: keyword | sidc | dimension | kinematics | default."""
    text = text or ""
    unit_level = bool(_UNIT_WORDS.search(text))
    for rx, unit, eq in _KEYWORDS:
        if rx.search(text):
            chosen = unit if (unit_level and unit) else eq
            if chosen:
                return chosen, "keyword"
    if sidc and len(str(sidc)) >= 6 and str(sidc)[4:6] in _SYMSET:
        return _SYMSET[str(sidc)[4:6]], "sidc"
    if dimension and str(dimension).strip().lower() in _DIM:
        return _DIM[str(dimension).strip().lower()], "dimension"
    if (hae is not None and hae > 500) or (speed_mps is not None and speed_mps > 80):
        return "A", "kinematics"
    return default_dim, "default"


def cot_type(text="", explicit_affiliation=None, dimension=None, sidc=None, hae=None, speed_mps=None,
             default_affiliation="u", default_dim="G", forced_type=None) -> tuple:
    """(cot_type, basis). forced_type (a valid source-provided CoT type) wins."""
    if forced_type and re.fullmatch(r"a-[pufansh](-[A-Za-z0-9_]+)+", str(forced_type)):
        return str(forced_type), "source"
    aff = affiliation(explicit_affiliation, text, sidc, default_affiliation)
    suf, basis = suffix(text, dimension, sidc, hae, speed_mps, default_dim)
    return f"a-{aff}-{suf}", basis
