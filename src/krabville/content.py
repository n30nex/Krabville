from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResidentProfile:
    slug: str
    name: str
    role: str
    home: str
    workplace: str
    color: str
    traits: dict[str, int]
    possessions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventTemplate:
    slug: str
    title: str
    category: str
    summary: str
    prop: str
    strange: bool = False


RESIDENTS = (
    ResidentProfile("latoya-williams", "Latoya Williams", "digital photographer", "Artists' house", "Photo studio", "#b66cff", {"openness": 76, "sociability": 58, "agreeableness": 70, "conscientiousness": 88, "risk": 44}, ("camera bag", "editing tablet", "tea tin")),
    ResidentProfile("rajiv-patel", "Rajiv Patel", "painter and guitarist", "Artists' house", "Painting studio", "#ffca3a", {"openness": 67, "sociability": 72, "agreeableness": 61, "conscientiousness": 84, "risk": 38}, ("paint box", "guitar", "gallery notes")),
    ResidentProfile("abigail-chen", "Abigail Chen", "digital artist", "Artists' house", "Animation lab", "#45b8ff", {"openness": 91, "sociability": 45, "agreeableness": 82, "conscientiousness": 79, "risk": 31}, ("drawing tablet", "prototype controller", "notebook")),
    ResidentProfile("francisco-lopez", "Francisco Lopez", "actor and comedian", "Artists' house", "Theatre workshop", "#ff7448", {"openness": 55, "sociability": 79, "agreeableness": 74, "conscientiousness": 77, "risk": 64}, ("script binder", "prop case", "red mug")),
    ResidentProfile("hailey-johnson", "Hailey Johnson", "writer and podcaster", "Artists' house", "Writing loft", "#65d497", {"openness": 85, "sociability": 64, "agreeableness": 68, "conscientiousness": 86, "risk": 49}, ("field recorder", "draft notebook", "headphones")),
    ResidentProfile("ryan-park", "Ryan Park", "software engineer", "Harbour apartment", "Radio engineering shack", "#5472ff", {"openness": 63, "sociability": 87, "agreeableness": 73, "conscientiousness": 65, "risk": 71}, ("tool roll", "field radio", "debug notebook")),
    ResidentProfile("giorgio-rossi", "Giorgio Rossi", "mathematician", "Observatory cottage", "Lagoon observatory", "#f45b69", {"openness": 72, "sociability": 91, "agreeableness": 66, "conscientiousness": 71, "risk": 42}, ("proof notebook", "telescope key", "walking coat")),
    ResidentProfile("carlos-gomez", "Carlos Gomez", "poet", "Garden apartment", "Library and park", "#ff9f1c", {"openness": 59, "sociability": 57, "agreeableness": 61, "conscientiousness": 92, "risk": 56}, ("poetry notebook", "library card", "pressed leaf")),
    ResidentProfile("ayesha-khan", "Ayesha Khan", "literature student", "Oak Hill dorm", "College library", "#4ecdc4", {"openness": 69, "sociability": 74, "agreeableness": 94, "conscientiousness": 90, "risk": 29}, ("thesis notes", "library books", "blue scarf")),
    ResidentProfile("wolfgang-schulz", "Wolfgang Schulz", "chemistry student athlete", "Oak Hill dorm", "College and training field", "#577590", {"openness": 93, "sociability": 38, "agreeableness": 54, "conscientiousness": 82, "risk": 52}, ("lab notebook", "running shoes", "water bottle")),
    ResidentProfile("mei-lin", "Mei Lin", "philosophy professor", "Lin family home", "Oak Hill College", "#9bde59", {"openness": 96, "sociability": 63, "agreeableness": 85, "conscientiousness": 68, "risk": 58}, ("lecture notes", "garden seeds", "moon charm")),
    ResidentProfile("tom-moreno", "Tom Moreno", "market keeper", "Moreno family home", "Willow Market", "#355070", {"openness": 52, "sociability": 70, "agreeableness": 76, "conscientiousness": 80, "risk": 67}, ("market ledger", "store keys", "wool cap")),
)

RESIDENT_DETAILS = {
    "latoya-williams": {
        "routine": "Photography, editing, travel stories, and town life",
        "about": "An organized artist with a sharp eye for small details.",
    },
    "rajiv-patel": {
        "routine": "Painting, gallery preparation, guitar, and quiet walks",
        "about": "A thoughtful painter preparing for his first solo show.",
    },
    "abigail-chen": {
        "routine": "Animation, interactive experiments, meals, and collaboration",
        "about": "An animator exploring where art, technology, and play meet.",
    },
    "francisco-lopez": {
        "routine": "Filming, improv, writing, rehearsals, and social time",
        "about": "A natural entertainer turning daily town life into stories.",
    },
    "hailey-johnson": {
        "routine": "Writing, interviews, reading, meals, and town conversations",
        "about": "A storyteller developing a novel and a new local podcast.",
    },
    "ryan-park": {
        "routine": "Building, debugging, research, errands, and evening downtime",
        "about": "A practical problem-solver who keeps Krabville's systems useful.",
    },
    "giorgio-rossi": {
        "routine": "Research, teaching, pattern hunting, meals, and long walks",
        "about": "A mathematician fascinated by patterns in nature and the sky.",
    },
    "carlos-gomez": {
        "routine": "Writing, workshops, reading, nature walks, and reflection",
        "about": "A poet collecting strange and beautiful details from the Lagoon.",
    },
    "ayesha-khan": {
        "routine": "Classes, thesis research, meals, friends, and reading",
        "about": "A determined student researching language and dramatic literature.",
    },
    "wolfgang-schulz": {
        "routine": "Running, chemistry, study, training, meals, and recovery",
        "about": "A disciplined student balancing experiments and competition.",
    },
    "mei-lin": {
        "routine": "Teaching, research, family meals, mentoring, and rest",
        "about": "A professor and parent who helps other people reach their goals.",
    },
    "tom-moreno": {
        "routine": "Opening the market, serving neighbours, supper, and town news",
        "about": "A friendly shopkeeper who knows what the town needs each day.",
    },
}


_MAJOR = {
    "social": (
        ("community-supper", "Community supper", "The square needs volunteers for a shared supper.", "supper-table"),
        ("dockside-concert", "Dockside concert", "A musician arrives and asks the town to build a stage before dusk.", "music-stage"),
        ("cafe-mixup", "Cafe mix-up", "A stack of swapped orders creates an awkward town mystery.", "order-tickets"),
        ("surprise-reunion", "Surprise reunion", "An old friend returns with a story no one remembers the same way.", "visitor-bag"),
        ("harbour-games", "Harbour games", "Residents form teams for a spontaneous day of Lagoon contests.", "signal-flags"),
        ("shared-birthday", "Shared birthday", "Two residents discover the town has recorded the same birthday for both.", "birthday-banner"),
        ("story-circle", "Story circle", "The library asks everyone to contribute one true story and one invention.", "story-cushions"),
        ("portrait-day", "Portrait day", "Mei offers to paint the town, but everyone disagrees about where to pose.", "easel"),
        ("recipe-swap", "Recipe swap", "A recipe exchange turns competitive when one card has no author.", "recipe-board"),
        ("lantern-walk", "Lantern walk", "The town plans a twilight walk along every dock.", "lantern-string"),
        ("welcome-picnic", "Welcome picnic", "A passing crew is invited to eat beside the Lagoon.", "picnic-blanket"),
        ("quiet-hour", "Quiet hour", "Residents agree to one radio-free hour and discover who cannot keep it.", "quiet-sign"),
    ),
    "civic": (
        ("radio-outage", "Radio tower outage", "The town radio goes quiet and neighbours organize a repair watch.", "radio-tools"),
        ("bridge-repair", "Bridge repair", "A loose bridge plank forces everyone to choose another route.", "bridge-planks"),
        ("market-day", "Lagoon market day", "The harbour market draws twice the expected crowd.", "market-stalls"),
        ("lost-parcel", "Lost parcel", "A parcel with no address begins a chain of careful guesses.", "mystery-parcel"),
        ("ferry-delay", "Ferry delay", "A stalled ferry rearranges work, meals, and promises across town.", "ferry-crate"),
        ("garden-project", "Community garden project", "An empty plot becomes the subject of twelve different plans.", "garden-beds"),
        ("library-leak", "Library roof leak", "Rain reaches the archive and residents race to move the oldest books.", "book-crates"),
        ("clinic-drive", "Clinic supply drive", "Ayesha organizes a supply collection before the next ferry.", "supply-boxes"),
        ("dock-cleanup", "Dock cleanup", "The tide leaves the marina covered in driftwood and odd debris.", "cleanup-pile"),
        ("town-map", "Town map revision", "Rajiv asks everyone to name the paths they actually use.", "map-board"),
        ("signal-test", "Signal test", "Latoya schedules a townwide radio test without disturbing the airwaves.", "test-antenna"),
        ("power-flicker", "Power flicker", "A power fault forces the town to share lamps and extension cords.", "cable-reel"),
    ),
    "environment": (
        ("storm-cleanup", "Storm cleanup", "A fast storm leaves branches, puddles, and one stranded rowboat.", "storm-debris"),
        ("fog-bank", "Heavy fog bank", "Dense fog changes routes and brings every sound closer.", "fog-lamps"),
        ("heat-wave", "Lagoon heat wave", "A hot afternoon sends residents searching for shade and cold drinks.", "shade-canopy"),
        ("first-snow", "First snow", "Unexpected snow turns the docks bright and dangerously slick.", "snow-piles"),
        ("high-water", "High water", "The Lagoon rises over the lowest boards before breakfast.", "sandbags"),
        ("wind-warning", "Wind warning", "Strong gusts threaten signs, laundry, and the ferry timetable.", "tied-signs"),
        ("meteor-shower", "Meteor shower", "A clear forecast promises a rare night above the Observatory.", "telescope"),
        ("bird-arrival", "Migrating birds", "A huge flock settles on every roof and refuses to move.", "bird-feeders"),
        ("algae-bloom", "Blue algae bloom", "Bright water near the east dock prompts a careful investigation.", "sample-jars"),
        ("fallen-tree", "Fallen cedar", "A cedar blocks the north path and reveals an old sign beneath it.", "fallen-tree"),
        ("rainbow-tide", "Rainbow tide", "Sunlight and mist turn the harbour into shifting bands of colour.", "prism-flags"),
        ("cold-snap", "Sudden cold snap", "A sharp freeze tests pipes, gardens, and everyone’s spare mittens.", "heater-crates"),
    ),
    "strange": (
        ("crab-cloud", "Crab-shaped cloud", "A perfect crab-shaped cloud drops one dry brass key.", "brass-key"),
        ("second-moon", "Moon in the water", "A second moon appears beneath the Lagoon surface.", "moon-reflection"),
        ("singing-fog", "Singing fog", "A bank of fog hums the same melody near every dock.", "music-fog"),
        ("midnight-mail", "Midnight mail", "Letters arrive in each resident's own handwriting.", "midnight-letters"),
        ("time-slip", "Ten-minute time slip", "Every clock jumps backward while memories disagree.", "stopped-clock"),
        ("upward-rain", "Upside-down rain", "For three minutes, rain rises from the Lagoon.", "upward-rain"),
        ("shared-dream", "Townwide shared dream", "Everyone remembers the same impossible lighthouse.", "dream-lighthouse"),
        ("silent-town", "Silent town", "Every radio, bell, and gull falls silent at once.", "silent-bell"),
        ("future-weather", "Tomorrow's broadcast", "A radio announces tomorrow's weather in a familiar voice.", "future-radio"),
        ("walking-statue", "Walking statue", "The square's stone crab appears beside the ferry at dawn.", "empty-pedestal"),
        ("extra-door", "The extra door", "A painted door appears on the library wall and opens onto blue light.", "blue-door"),
        ("memory-tide", "Memory tide", "Objects left by the water return with handwritten memories attached.", "memory-tags"),
    ),
}

MAJOR_EVENTS = tuple(
    EventTemplate(slug, title, category, summary, prop, category == "strange")
    for category, rows in _MAJOR.items()
    for slug, title, summary, prop in rows
)

_MICRO_SUBJECTS = (
    "a loose signal flag", "an unlabeled key", "a windblown sketch", "a warm loaf",
    "a stranded canoe", "a broken umbrella", "a humming radio", "a shy visitor",
    "a fresh set of tracks", "a missing notice", "a bright bottle", "a stubborn gate",
)
_MICRO_ACTIONS = (
    ("discovery", "is found near {place} and becomes the morning's small mystery"),
    ("kindness", "gives two neighbours a reason to help each other at {place}"),
    ("friction", "causes a brief disagreement beside {place}"),
    ("work", "interrupts ordinary work at {place}"),
    ("weather", "changes meaning when the weather turns near {place}"),
    ("rumour", "starts a harmless rumour around {place}"),
)
MICRO_EVENTS = tuple(
    EventTemplate(
        f"micro-{category}-{index + 1}",
        subject.capitalize(),
        category,
        f"{subject.capitalize()} {action}.",
        "small-clue",
    )
    for category, action in _MICRO_ACTIONS
    for index, subject in enumerate(_MICRO_SUBJECTS)
)

assert len(MAJOR_EVENTS) == 48
assert len(MICRO_EVENTS) == 72


PATH_NODES = {
    "square": (885, 430),
    "square-west": (705, 430),
    "square-east": (1040, 430),
    "square-south": (900, 535),
    "cafe-junction": (535, 430),
    "cafe": (454, 451),
    "post-office": (648, 462),
    "west-bridge": (360, 430),
    "radio": (150, 386),
    "west-north": (360, 240),
    "observatory": (362, 180),
    "northwest-loop": (520, 247),
    "willow": (600, 250),
    "north-center": (820, 300),
    "maple": (806, 250),
    "north-east": (1090, 300),
    "lantern": (1085, 260),
    "clinic": (1105, 470),
    "greenhouse-junction": (1340, 300),
    "glass": (1328, 216),
    "east-north": (1460, 335),
    "post-house": (1580, 315),
    "east-bridge": (1275, 430),
    "birch": (1370, 466),
    "workshop-junction": (1510, 520),
    "workshop": (1588, 580),
    "lower-west": (650, 560),
    "rose-junction": (350, 612),
    "rose": (165, 600),
    "gear": (536, 653),
    "dock-junction": (830, 700),
    "harbour": (850, 795),
    "lower-east": (1120, 610),
    "garden-path": (1190, 650),
    "pine": (1290, 754),
    "shore-path": (1390, 700),
    "lotus": (1455, 786),
}

PATH_EDGES = (
    ("square", "square-west"),
    ("square", "square-east"),
    ("square", "square-south"),
    ("square-west", "cafe-junction"),
    ("square-west", "post-office"),
    ("cafe-junction", "cafe"),
    ("cafe-junction", "west-bridge"),
    ("west-bridge", "radio"),
    ("west-bridge", "west-north"),
    ("west-north", "observatory"),
    ("west-north", "northwest-loop"),
    ("northwest-loop", "willow"),
    ("northwest-loop", "north-center"),
    ("north-center", "maple"),
    ("north-center", "square-west"),
    ("north-center", "north-east"),
    ("north-east", "lantern"),
    ("north-east", "square-east"),
    ("north-east", "greenhouse-junction"),
    ("square-east", "clinic"),
    ("square-east", "east-bridge"),
    ("greenhouse-junction", "glass"),
    ("greenhouse-junction", "east-north"),
    ("east-north", "post-house"),
    ("east-north", "east-bridge"),
    ("east-bridge", "birch"),
    ("east-bridge", "workshop-junction"),
    ("workshop-junction", "workshop"),
    ("square-south", "lower-west"),
    ("square-south", "lower-east"),
    ("lower-west", "post-office"),
    ("lower-west", "rose-junction"),
    ("lower-west", "gear"),
    ("lower-west", "dock-junction"),
    ("rose-junction", "rose"),
    ("dock-junction", "harbour"),
    ("lower-east", "garden-path"),
    ("lower-east", "dock-junction"),
    ("garden-path", "pine"),
    ("garden-path", "shore-path"),
    ("shore-path", "lotus"),
    ("shore-path", "workshop-junction"),
)

LOCATION_ACCESS = {
    "Town Square": "square",
    "Hobbs Cafe": "cafe",
    "Lagoon Library": "gear",
    "Lagoon Clinic": "clinic",
    "Radio Shack": "radio",
    "Harbour Office": "harbour",
    "Boatworks": "lotus",
    "Weather Station": "observatory",
    "Post Office": "post-office",
    "Repair Workshop": "workshop",
    "Observatory": "observatory",
    "Garden Studio": "glass",
    "Ferry Dock": "harbour",
    "North Dock": "north-center",
    "East Dock": "east-bridge",
    "West Dock": "west-bridge",
    "Willow House": "willow",
    "Maple House": "maple",
    "Lantern House": "lantern",
    "Cedar House": "post-house",
    "Glass House": "glass",
    "Post House": "post-office",
    "Rose House": "rose",
    "Gear House": "gear",
    "Birch House": "birch",
    "Pine House": "pine",
    "Lotus House": "lotus",
    "Anchor House": "harbour",
    "Artists' house": "gear",
    "Photo studio": "glass",
    "Painting studio": "willow",
    "Animation lab": "maple",
    "Theatre workshop": "post-house",
    "Writing loft": "lantern",
    "Harbour apartment": "harbour",
    "Radio engineering shack": "radio",
    "Observatory cottage": "observatory",
    "Lagoon observatory": "observatory",
    "Garden apartment": "rose",
    "Library and park": "gear",
    "Oak Hill dorm": "maple",
    "College library": "gear",
    "College and training field": "north-center",
    "Lin family home": "birch",
    "Oak Hill College": "clinic",
    "Moreno family home": "post-house",
    "Willow Market": "cafe",
}

LOCATION_POINTS = {
    location: PATH_NODES[node]
    for location, node in LOCATION_ACCESS.items()
}
