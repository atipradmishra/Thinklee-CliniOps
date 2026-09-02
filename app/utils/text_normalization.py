import re

DUTCH_COMPOUND_SUFFIXES = [
    "overlast",
    "melding",
    "dienst",
    "beheer",
    "controle",
    "incident",
    "beveiliging",
    "lawaai",
    "geluid",
]

def normalize_dutch_compounds(text: str) -> str:
    """
    Splits common Dutch compound suffixes:
    geluidsoverlast -> geluid overlast
    parkeeroverlast -> parkeer overlast
    """
    t = text.lower()

    for suffix in DUTCH_COMPOUND_SUFFIXES:
        t = re.sub(
            rf"(\w+)({suffix})",
            r"\1 \2",
            t
        )

    return t
