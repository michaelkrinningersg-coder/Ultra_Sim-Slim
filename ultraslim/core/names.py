"""Nationen, Namen und Teams.

Alle Fahrer sind fiktiv. Die Listen enthalten gebräuchliche Vor- und
Nachnamen; Übereinstimmungen mit realen Personen sind Zufall.

Acht Nationen statt der zwölf des Originals — die, in denen
Ultradistanzrennen tatsächlich zu Hause sind.
"""

from __future__ import annotations

NATIONS: dict[str, str] = {
    "AUT": "Österreich",
    "GER": "Deutschland",
    "SUI": "Schweiz",
    "ITA": "Italien",
    "GBR": "Großbritannien",
    "USA": "Vereinigte Staaten",
    "NED": "Niederlande",
    "BEL": "Belgien",
}

#: Relative Häufigkeit im Fahrerpool.
NATION_WEIGHTS: dict[str, float] = {
    "AUT": 1.6,
    "GER": 2.6,
    "SUI": 1.4,
    "ITA": 1.8,
    "GBR": 1.8,
    "USA": 1.5,
    "NED": 1.3,
    "BEL": 1.2,
}

FIRST_NAMES: dict[str, tuple[str, ...]] = {
    "AUT": ("Matthias", "Stefan", "Georg", "Andreas", "Lukas", "Fabian", "Christoph", "Bernhard",
            "Elias", "Valentin", "Gregor", "Hannes", "Raphael", "Tobias", "Klemens", "Severin"),
    "GER": ("Jonas", "Lukas", "Felix", "Moritz", "Tobias", "Niklas", "Sebastian", "Jannik",
            "Maximilian", "Florian", "Simon", "Hendrik", "Kilian", "Marvin", "Ole", "Bastian"),
    "SUI": ("Silvan", "Marco", "Reto", "Fabian", "Nico", "Cyrill", "Andri", "Gian",
            "Lars", "Robin", "Simon", "Yannick", "Kevin", "Joel", "Timon", "Beat"),
    "ITA": ("Matteo", "Lorenzo", "Alessandro", "Davide", "Andrea", "Giulio", "Federico", "Simone",
            "Marco", "Nicola", "Riccardo", "Tommaso", "Filippo", "Emanuele", "Stefano", "Luca"),
    "GBR": ("Oliver", "Harry", "George", "Callum", "Tom", "Alfie", "Ewan", "Rhys",
            "Connor", "Dan", "Josh", "Freddie", "Lewis", "Owen", "Charlie", "Nathan"),
    "USA": ("Tyler", "Brandon", "Jared", "Cole", "Austin", "Evan", "Derek", "Casey",
            "Trevor", "Shane", "Devin", "Garrett", "Blake", "Chase", "Logan", "Curtis"),
    "NED": ("Sven", "Bram", "Daan", "Jelle", "Thijs", "Wouter", "Ruben", "Koen",
            "Stijn", "Lars", "Joris", "Sander", "Bas", "Teun", "Rick", "Maarten"),
    "BEL": ("Wout", "Jasper", "Tim", "Robbe", "Senne", "Arne", "Lander", "Dries",
            "Nils", "Ward", "Milan", "Seppe", "Brent", "Jarne", "Kobe", "Vincent"),
}

LAST_NAMES: dict[str, tuple[str, ...]] = {
    "AUT": ("Steinlechner", "Gruber", "Hofstätter", "Aigner", "Pichler", "Ranzinger", "Moosbrugger",
            "Zeilinger", "Haslinger", "Kirchmair", "Eibl", "Wieser", "Prantl", "Sailer",
            "Aichinger", "Rebernig"),
    "GER": ("Brandt", "Vogler", "Kaltenbach", "Heinrich", "Ostermann", "Reinhardt", "Sturm",
            "Wiegand", "Falkenberg", "Merten", "Sandner", "Rothbauer", "Kienzle", "Nolte",
            "Ebersbach", "Hufnagel"),
    "SUI": ("Brunner", "Zurbriggen", "Frei", "Aebersold", "Rüegg", "Cadonau", "Bättig",
            "Schneiter", "Hodel", "Vonlanthen", "Bernasconi", "Lauber", "Marti", "Gasser",
            "Studer", "Amrein"),
    "ITA": ("Bellandi", "Carraro", "Fontanelli", "Moretti", "Sartori", "Viganò", "Ferrero",
            "Zanotti", "Pastore", "Rinaldi", "Tosetti", "Basso", "Colombari", "Mazzocchi",
            "Perotti", "Salvadori"),
    "GBR": ("Ashworth", "Brookes", "Chatterton", "Dunmore", "Eastwood", "Fairhurst", "Grantham",
            "Hollis", "Kingsley", "Lansdale", "Mowbray", "Prescott", "Radcliffe", "Stanbury",
            "Thorne", "Waverley"),
    "USA": ("Alderman", "Bridgewater", "Coleridge", "Dunlap", "Ellery", "Fairbanks", "Granger",
            "Halloway", "Ivers", "Jennings", "Kessler", "Lockhart", "Marlowe", "Northrup",
            "Pemberton", "Quimby"),
    "NED": ("Boersma", "De Ruiter", "Van Dijk", "Hoekstra", "Kamphuis", "Leeuwen", "Mulder",
            "Nijhoff", "Oosterhuis", "Prins", "Roelofs", "Steenbergen", "Terlouw", "Vermeer",
            "Wagenaar", "Zwart"),
    "BEL": ("Aerts", "Beeckman", "Cools", "Dewulf", "Everaert", "Goossens", "Hendrickx",
            "Janssens", "Lambrecht", "Maes", "Nys", "Peeters", "Roelandts", "Segers",
            "Vandaele", "Wauters"),
}

#: Die fünfundzwanzig Teams, benannt wie im echten Radsport: **Ausrüster
#: und Radmarke**, durch einen Halbgeviertstrich verbunden.
#:
#: **Die Marken sind echt, die Teams sind es nicht.** Keine der genannten
#: Firmen hat mit diesem Programm zu tun, sponsert nichts und weiß nichts
#: davon; die Namen stehen hier, weil eine erfundene Marke neben einer
#: erfundenen Mannschaft die Illusion zweimal bricht.
#:
#: Feste Paare statt zufälliger Kombinationen: Ein Team soll über Saisons
#: hinweg dasselbe Team bleiben.
TEAM_NAMES: tuple[str, ...] = (
    "Vaude–Canyon",
    "Ortlieb–Cube",
    "Deuter–Rose",
    "Osprey–Trek",
    "Mammut–Scott",
    "Fjällräven–Bianchi",
    "Patagonia–Cervélo",
    "Salomon–Specialized",
    "Jack Wolfskin–Focus",
    "Arc'teryx–Pinarello",
    "Black Diamond–Cannondale",
    "Petzl–Lapierre",
    "Thule–Giant",
    "Exped–BMC",
    "Sea to Summit–Merida",
    "Haglöfs–Ridley",
    "Norrøna–Orbea",
    "Bergans–Colnago",
    "Rab–Wilier",
    "Montane–Storck",
    "Icebreaker–Stevens",
    "Buff–Ghost",
    "Camelbak–Felt",
    "Salewa–De Rosa",
    "Schöffel–Kona",
)

__all__ = ["NATIONS", "NATION_WEIGHTS", "FIRST_NAMES", "LAST_NAMES", "TEAM_NAMES"]
