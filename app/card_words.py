#!/usr/bin/env python3
"""What a card's title says about it, in one place.

The pipeline works these facts out of a title when it builds a batch: the
maker, the year, the card number, the player, the grade, the printing, the
category, and the SKU that comes of them. The website's own products have the
same title - it is the product's name and its Rank Math title - so a field a
product is missing can be worked out from it with the *same* rules rather than
a second set that slowly disagrees.

Everything here is a reading of words, never a guess and never a default: a
title that does not say who made the card has no brand, and ``brand`` comes
back empty. ``card_pipeline`` imports these names and keeps its own behaviour
exactly; the shop tools in ``product_fields`` import them too.
"""
from __future__ import annotations

import re
import unicodedata

# ------------------------------------------------------------------ brands
#: The makers a title is read for, in the order they are looked for. A title
#: naming none of them has no brand - the pipeline's own default ("O-Pee-Chee"
#: when the AI said nothing) belongs to the batch, not to a product that is
#: already on a website, so it is passed in by the caller that wants it.
KNOWN_BRANDS = [
    ("O-Pee-Chee",  r"O-?Pee-?Chee"),
    ("O-Pee-Chee",  r"\bOPC\b"),
    ("Topps",       r"\bTopps\b"),
    ("Parkhurst",   r"\bParkhurst\b"),
    ("Upper Deck",  r"\bUpper\s+Deck\b"),
    ("Bowman",      r"\bBowman\b"),
    ("Fleer",       r"\bFleer\b"),
    ("Score",       r"\bScore\b"),
    ("Pro Set",     r"\bPro\s*Set\b"),
    ("Panini",      r"\bPanini\b"),
]

#: A grade as the pipeline's titles write it: "EX-MT 6", "VG-EX 4", "NM 7".
GRADE_RE = re.compile(
    r"\b("
    r"GEM[\s\-]?MT|GEM|"
    r"NM[\s\-]?MT|"
    r"EX[\s\-]?MT|"
    r"VG[\s\-]?EX|"
    r"NM|MINT|EX|VG|GOOD|FAIR|POOR|PR|FR"
    r")\b\s*(\d+(?:\.\d+)?)?",
    re.IGNORECASE,
)


def extract_brand(seo_title, default_brand=""):
    """The maker a title names, or ``default_brand`` when it names none.

    The default is the caller's: the batch passes "O-Pee-Chee" because a card
    the AI left blank is that shop's card, while a product already on a website
    passes "" - a brand invented for a product that has none is a wrong brand
    on a live listing rather than a useful default.
    """
    for canonical, pattern in KNOWN_BRANDS:
        if re.search(pattern, str(seo_title or ""), re.IGNORECASE):
            return canonical
    return default_brand


def extract_year(seo_title):
    m = re.search(r"(\d{4}-\d{2}|\d{4})", str(seo_title or ""))
    return m.group(1) if m else ""


def extract_card_number(seo_title):
    m = re.search(r"#(\w+)", str(seo_title or ""))
    return m.group(1) if m else ""


def extract_player_name(seo_title, brand):
    m = re.match(r"^\s*(?:\d{4}-\d{2}|\d{4})\s+(.+?)#", str(seo_title or "").strip())
    if not m:
        return ""
    middle = m.group(1).strip()
    for _, pattern in KNOWN_BRANDS:
        stripped = re.sub(
            r"^\s*" + pattern + r"\s*", "", middle, flags=re.IGNORECASE
        )
        if stripped != middle:
            middle = stripped.strip()
            break
    if brand:
        middle = re.sub(
            r"^\s*" + re.escape(brand) + r"\s*", "", middle,
            flags=re.IGNORECASE
        ).strip()
    return middle


def brand_code(brand):
    """The letters a SKU opens with: "O-Pee-Chee" is OPC, "Topps" is TOPPS."""
    parts = re.split(r"[\s\-]+", str(brand or "").strip())
    parts = [p for p in parts if p]
    if len(parts) == 1:
        return parts[0].upper()
    letters = "".join(p[0].upper() for p in parts)
    return letters or str(brand or "").upper()


# ------------------------------------------------------- the printing, by name
#  Some vintage sets printed one card more than one way, and a title that
#  names the printing - "Dark Back", "Light Back", "Corrected Bio" - is a
#  different card: a different printing, a different price, a different
#  product. The SKU is what the website, the CSV and the comparison use to
#  tell two products apart, so the printing goes into the SKU. Two cards that
#  are otherwise identical (same year, number, player and grade) then no
#  longer share one SKU - which is how the light back of a card came to be
#  skipped as "already on the website" the moment the dark back existed.
#
#  The order matters twice over: the phrases are matched as whole words, so
#  "uncorrected" never matches "corrected", and the tokens come out in this
#  order, so one title always produces one SKU. ``woo_create`` keeps the same
#  list of phrases to decide whether a product found by SKU is really the card
#  it is looking for - a check in the suite keeps the two from drifting.
VARIETY_TOKENS = (
    ("dark back", "DB"),
    ("light back", "LB"),
    ("white back", "WB"),
    ("grey back", "GB"),
    ("gray back", "GB"),
    ("uncorrected", "UNCORR"),
    ("corrected", "CORR"),
)


def variety_tokens(title):
    """The SKU tokens a title's printing earns, in a stable order.

    Only the words decide, so "Dark Back", "Dark-Back" and "dark back" are one
    printing, and a title that names two ("Corrected Bio Light Back") gets both
    tokens. A title naming no printing returns an empty list and keeps the SKU
    a card has always had.
    """
    words = re.sub(r"[^a-z0-9]+", " ", str(title or "").lower())
    words = " %s " % re.sub(r"\s+", " ", words).strip()
    found = []
    for phrase, token in VARIETY_TOKENS:
        if " %s " % phrase in words and token not in found:
            found.append(token)
    return found


def sku_component(text):
    """One piece of a SKU: letters, digits and single dashes, nothing else.

    A SKU travels through a CSV, an Excel sheet, a URL and a shop's own
    search box, so an accent, a space, a slash or a full stop in one is a way
    for the same card to be written two different ways - or for an import to
    refuse the row. Accents are folded to their plain letters ("Jérôme" is
    "Jerome") rather than dropped, so two cards do not become one.
    """
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return text


#  Windows forbids these characters in filenames: \ / : * ? " < > |
#  Also strip trailing dots/spaces (Windows disallows them at the end of a name)
_WIN_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename_component(text):
    """Strip characters that are illegal in Windows filenames (e.g. the
    '?' in a title like 'Baseball or Music?'), so downstream renames
    never hit WinError 123."""
    if not text:
        return ""
    text = _WIN_ILLEGAL_RE.sub("", text)
    text = text.rstrip(" .")
    return text


def grade_slug(grade):
    """A cleaned grade ("EX 5", "VG-EX") as a SKU piece ("EX-5", "VG-EX")."""
    if not grade:
        return ""
    return re.sub(r"\s+", "-", sanitize_filename_component(str(grade).strip()))


def card_sku(card):
    """The SKU this card is given when the batch writes its CSV.

    One definition, used twice: by :func:`build_rows`, where it becomes the
    product's SKU, and by the eBay Quick List, where it is what a card marked
    to skip is recognized by on every later batch. Two spellings of the same
    SKU would mean a skip that stops working the moment the card is listed.
    """
    code = brand_code(card["brand"])
    grade_component = grade_slug(card["grade"])  # e.g. "EX-5", "VG-3"
    #  The printing is part of the SKU (see VARIETY_TOKENS): a dark back
    #  and a light back of one card are two products, and one SKU for both
    #  meant the second was skipped as already there.
    sku_bits = ([code + str(card["year"]), card["card_num"], card["last"],
                 grade_component] + variety_tokens(card["seo_title"]))
    return "-".join(bit for bit in (sku_component(piece)
                                    for piece in sku_bits) if bit)


# ------------------------------------------------------- the grade, in a title
def _grade_at_end(text):
    """The match for the grade a title ends with, or ``None``.

    Only a grade at the *end* counts. A title's own words are a player's name
    first ("Bob Good", "Fair Oaks"), so reading a grade out of the middle of
    one would turn a player into a condition - and the grade a batch uses comes
    from the AI's own estimate, never from the title.
    """
    text = str(text or "").strip().rstrip(".,;: ")
    found = None
    for match in GRADE_RE.finditer(text):
        #  Nothing may follow it but the end of the title: "Bob Good #7" is a
        #  player and a number, and a grade with words after it is not the
        #  grade the title ends with.
        if match.end() == len(text.rstrip()):
            found = match
    return found


def grade_from_title(title):
    """The grade a title states at its end, cleaned ("EX-MT 6"), or ""."""
    match = _grade_at_end(title)
    if not match:
        return ""
    label = re.sub(r"\s+", "-", match.group(1).strip().upper())
    number = str(match.group(2) or "").strip()
    return ("%s %s" % (label, number)).strip() if number else label


def keyword_from_title(title):
    """The search phrase a title states: the year, the maker and the player.

    "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6 Chicago Black Hawks" is a product
    name - a buyer does not type a condition, a card number or a team into a
    search box, and a keyword that does is the whole title again. The phrase is
    the three words that identify the card in a search: ``1991 O-Pee-Chee
    Dallas Smith``.

    This is the same thing the batch's own focus keyword says: the AI is asked
    for the "best high-volume search phrase, matching the title exactly", and
    for a card that is the year, the maker and the player. A product already on
    a website has no AI document, so the same phrase is read out of its title.

    A part the title does not state is left out rather than guessed, and a
    title that states none of the three has no keyword in it at all.
    """
    told = {"brand": extract_brand(title, ""), "year": extract_year(title),
            "player": ""}
    told["player"] = extract_player_name(title, told["brand"])
    return _keyword_words(told)


def _keyword_words(told):
    """The year, the maker and the player, each once, in that order."""
    words, seen = [], set()
    for word in ((told or {}).get("year"), (told or {}).get("brand"),
                 (told or {}).get("player")):
        word = " ".join(str(word or "").split())
        if not word or word.lower() in seen:
            continue
        seen.add(word.lower())
        words.append(word)
    return " ".join(words)


# ---------------------------------------------------- category / sub-category
SPORT_KEYWORDS = {
    "Hockey Card": [
        r"\bhockey\b", r"\bnhl\b", r"\bstanley cup\b", r"\bgoalie\b",
        r"\bgoaltender\b", r"\bcenterman\b", r"\bleft wing\b", r"\bright wing\b",
        r"\bdefenseman\b", r"\bmaple leafs\b", r"\bcanadiens\b", r"\bbruins\b",
        r"\bblackhawks\b", r"\bred wings\b", r"\boilers\b", r"\bflames\b",
        r"\bcanucks\b", r"\bsenators\b", r"\bpredators\b", r"\bavalanche\b",
        r"\bsharks\b", r"\bducks\b", r"\bpenguins\b", r"\bflyers\b",
        r"\bcapitals\b", r"\bislanders\b", r"\bdevils\b", r"\bsabres\b",
        r"\blightning\b", r"\bhurricanes\b", r"\bcoyotes\b", r"\bblue jackets\b",
        r"\bnordiques\b", r"\bwhalers\b", r"\bnorth stars\b", r"\bwild\b",
    ],
    "Baseball Card": [
        r"\bbaseball\b", r"\bmlb\b", r"\bpitcher\b", r"\boutfielder\b",
        r"\bshortstop\b", r"\bworld series\b", r"\byankees\b", r"\bred sox\b",
        r"\bdodgers\b", r"\bgiants\b", r"\bcubs\b", r"\bmets\b", r"\bbraves\b",
        r"\bastros\b", r"\bcardinals\b", r"\bphillies\b", r"\btigers\b",
        r"\bguardians\b", r"\bathletics\b", r"\bpirates\b", r"\bbrewers\b",
        r"\bmariners\b", r"\bpadres\b", r"\breds\b", r"\btwins\b", r"\bangels\b",
        r"\bblue jays\b", r"\brockies\b", r"\bmarlins\b", r"\bnationals\b",
        r"\brays\b", r"\bwhite sox\b", r"\broyals\b", r"\borioles\b",
    ],
    "Basketball Card": [
        r"\bbasketball\b", r"\bnba\b", r"\bpoint guard\b", r"\bshooting guard\b",
        r"\bsmall forward\b", r"\bpower forward\b", r"\bdunk\b", r"\brebound\b",
        r"\blakers\b", r"\bceltics\b", r"\bbulls\b", r"\bwarriors\b", r"\bnets\b",
        r"\bknicks\b", r"\bheat\b", r"\bspurs\b", r"\brockets\b",
        r"\bmavericks\b", r"\bsuns\b", r"\bclippers\b", r"\bnuggets\b",
        r"\btrail blazers\b", r"\bjazz\b", r"\bgrizzlies\b", r"\bpelicans\b",
        r"\btimberwolves\b", r"\bthunder\b", r"\bmagic\b", r"\bhawks\b",
        r"\bhornets\b", r"\bpistons\b", r"\bpacers\b", r"\bbucks\b",
        r"\bcavaliers\b", r"\b76ers\b", r"\bsixers\b", r"\braptors\b",
    ],
    "Football Card": [
        r"\bfootball\b", r"\bnfl\b", r"\bcfl\b", r"\bquarterback\b",
        r"\brunning back\b", r"\bwide receiver\b", r"\btouchdown\b",
        r"\btight end\b", r"\blinebacker\b", r"\bcowboys\b", r"\bpatriots\b",
        r"\bpackers\b", r"\bsteelers\b", r"\b49ers\b", r"\bniners\b",
        r"\beagles\b", r"\bbears\b", r"\bbroncos\b", r"\braiders\b",
        r"\bchargers\b", r"\bchiefs\b", r"\bbills\b", r"\bdolphins\b",
        r"\bbengals\b", r"\bbrowns\b", r"\bravens\b", r"\btitans\b",
        r"\bcolts\b", r"\bjaguars\b", r"\btexans\b", r"\bcommanders\b",
        r"\bredskins\b", r"\bvikings\b", r"\blions\b", r"\bfalcons\b",
        r"\bsaints\b", r"\bbuccaneers\b", r"\brams\b", r"\bseahawks\b",
    ],
}

NON_SPORTS_KEYWORDS = [
    r"\bnon-?sports?\b", r"\bstar wars\b", r"\bmarvel\b", r"\bdc comics\b",
    r"\bgarbage pail kids\b", r"\bpok[eé]mon\b", r"\bmagic:? the gathering\b",
    r"\byu-?gi-?oh\b", r"\bdisney\b", r"\btrading card game\b", r"\btcg\b",
    r"\bwacky packages\b", r"\bmars attacks\b", r"\bbatman\b", r"\bsuperman\b",
    r"\bspider-?man\b", r"\bx-?men\b",
]


def detect_sport_category(text):
    """``("Sports Card", "Hockey Card")`` for the sport a text is about.

    The sport is decided by the words a title, a description and its tags
    already use. A text that names no sport at all lands where this shop puts
    such cards - "Sports Card > Hockey Card" - which is the batch's own rule
    for every card it has ever written, so a product given a category this way
    is filed exactly as the batch files cards without sport words.
    """
    lower = str(text or "").lower()

    for pattern in NON_SPORTS_KEYWORDS:
        if re.search(pattern, lower, re.IGNORECASE):
            return "Non Sports Card", ""

    scores = {}
    for sub, patterns in SPORT_KEYWORDS.items():
        count = sum(1 for p in patterns if re.search(p, lower, re.IGNORECASE))
        if count:
            scores[sub] = count

    if not scores:
        return "Sports Card", "Hockey Card"

    best_sub = max(scores, key=scores.get)
    return "Sports Card", best_sub


def names_sport(text):
    """Whether a text names a sport (or a kind of card) this shop files."""
    lower = str(text or "").lower()
    if any(re.search(pattern, lower, re.IGNORECASE)
           for pattern in NON_SPORTS_KEYWORDS):
        return True
    return any(re.search(pattern, lower, re.IGNORECASE)
               for patterns in SPORT_KEYWORDS.values()
               for pattern in patterns)


def category_label(category, subcategory):
    return category if not subcategory else f"{category} > {subcategory}"


def category_names(text):
    """The category path a text names, parent first: ``["Sports Card", ...]``."""
    category, subcategory = detect_sport_category(text)
    return [name for name in (category, subcategory) if name]


# ---------------------------------------------------------- the words, once
def _tag_words(told):
    """The words a title states, in the order a card's tags are read."""
    words, seen = [], set()
    for word in (told["year"], told["brand"], told["player"],
                 ("#" + told["card_num"]) if told["card_num"] else ""):
        word = str(word or "").strip()
        if not word or word.lower() in seen:
            continue
        seen.add(word.lower())
        words.append(word)
    return words


def tags_from_title(title):
    """The tags a title already states: the year, the maker, the player, #no.

    Nothing is added to them: a tag that is not in the product's own name is a
    word the seller did not write, and the batch's tags come from the AI, not
    from here.
    """
    return _tag_words(facts(title))


def facts(title):
    """Everything one title says about its card, and nothing it does not.

    ``brand`` and ``grade`` are empty when the title names neither, ``sku`` is
    empty when the title does not say enough to build one, and ``keyword`` is
    the search phrase the title states - the year, the maker and the player.
    """
    title = str(title or "").strip()
    brand = extract_brand(title, "")
    year = extract_year(title)
    card_num = extract_card_number(title)
    player = extract_player_name(title, brand)
    grade = grade_from_title(title)
    told = {
        "title": title,
        "brand": brand,
        "year": year,
        "card_num": card_num,
        "player": player,
        "last": player.split()[-1] if player else "",
        "grade": grade,
        "keyword": "",
        "categories": category_names(title),
        "tags": [],
        "sku": "",
    }
    told["keyword"] = _keyword_words(told)
    told["tags"] = _tag_words(told)
    if told["year"] and told["card_num"] and told["last"]:
        #  The same function the batch's CSV uses, given the facts the title
        #  states - so a SKU worked out here and a SKU worked out by a batch
        #  agree word for word when they are given the same card.
        told["sku"] = card_sku({"brand": told["brand"], "year": told["year"],
                                "card_num": told["card_num"],
                                "last": told["last"], "grade": told["grade"],
                                "seo_title": title})
    return told
