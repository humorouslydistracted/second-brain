# Synthetic dataset assets shared by the v1 and v2 generators.
#
# v2 notes:
# - INDIA_LEDGER_REASONS / GLOBAL_LEDGER_REASONS are retained here for the v1
#   generator. The v2 generator does not import them: ledger writes in v2 always
#   emit `note: null` (see dataset_v2_plan.md §1 / finetuning_data_sanity.md
#   "v2 - Ledger reason note").
# - The Tanglish single-date / range keys flagged below are Pattern C in v2 and
#   are excluded from query generation. They appear only inside todo-write
#   Pattern B contexts (`naliku room clean pannanum`).

INDIA_NAMES = [
    "Aadhira", "Aakash", "Aaliya", "Aarthi", "Abhinav", "Aditya", "Afsana", "Ajay", "Akila", "Akshay",
    "Amala", "Amar", "Amritha", "Anand", "Ananya", "Anbu", "Anitha", "Anjali", "Anjana", "Anwar",
    "Aravind", "Arjun", "Arul", "Ashika", "Ashwin", "Asif", "Athira", "Avinash", "Ayesha", "Bala",
    "Bhanu", "Bharath", "Bhavani", "Bhuvana", "Charan", "Charulatha", "Danish", "Darshan", "Deepak", "Deepika",
    "Devi", "Dhanush", "Divya", "Elango", "Farah", "Farook", "Fathima", "Gautham", "Gayathri", "Giri",
    "Gokila", "Gopinath", "Hari", "Harish", "Haritha", "Hemalatha", "Ibrahim", "Indhu", "Ishwarya", "Jagadeesh",
    "Janaki", "Jeeva", "Jenifer", "Jerin", "Kala", "Kalai", "Karthi", "Karthika", "Kavin", "Keerthana",
    "Kishore", "Krishna", "Kumaran", "Lakshmi", "Lalitha", "Madhu", "Mahesh", "Malathi", "Manikandan", "Meena",
    "Mithra", "Mohan", "Muthu", "Nandhini", "Naveen", "Nazreen", "Nila", "Nirmal", "Nisha", "Noorjahan",
    "Pari", "Pavithra", "Prabhu", "Pradeep", "Pranav", "Priya", "Rahim", "Rajesh", "Ramya", "Ranjani",
    "Rashid", "Revathi", "Rithik", "Rohini", "Sahana", "Sakthi", "Saranya", "Saravanan", "Sathish", "Selvi",
    "Shabana", "Shalini", "Shankar", "Siva", "Sneha", "Subash", "Sudha", "Suhail", "Sujatha", "Suresh",
    "Swetha", "Tamil", "Tharun", "Thenmozhi", "Uma", "Umesh", "Vaishnavi", "Varun", "Vasanth", "Vidhya",
    "Vignesh", "Vijaya", "Vinod", "Yasmin", "Yogesh", "Yuvika", "Zara", "amma", "appa", "anna",
    "akka", "thambi", "thangachi", "athai", "chithi", "chithappa", "mama", "mami", "paati", "thatha", "perima", "peripa",
    "machi", "macha", "machan"
]

GLOBAL_NAMES = [
    "Avery", "Bianca", "Caleb", "Camila", "Damian", "Daphne", "Elias", "Elena", "Felix", "Fiona",
    "Gabriel", "Gemma", "Hanna", "Harper", "Hugo", "Irene", "Isaac", "Jasper", "Jonah", "Julia",
    "Kai", "Keira", "Lena", "Luca", "Mara", "Mason", "Milo", "Naomi", "Nolan", "Olive",
    "Owen", "Piper", "Quentin", "Rhea", "Riley", "Roman", "Sasha", "Sienna", "Soren", "Stella",
    "Theo", "Tobias", "Una", "Vera", "Wes", "Willow", "Xenia", "Yara", "Zane", "Zoe",
]

INDIA_NOTE_TOPICS = [
    "metro recharge", "inverter buzzing", "terrace cleaning", "EB meter reading", "monsoon water storage", "seed trays",
    "UPI settlement reminder", "local model latency", "LPG booking", "ration shelf restock", "coconut jaggery", "temple car route",
    "hostel reimbursement", "railway tatkal plan", "silk blouse measurement", "water can delivery", "balcony pigeon netting",
    "school ID photocopy", "festival shopping notes", "printer toner check", "shared cab reimbursement", "road tax reminder",
    "groundnut oil comparison", "backup power test", "mosquito coil stock", "soap bulk pack", "induction stove issue",
    "maid leave note", "UPI sound box recharge", "ragi batter ratio", " summer buttermilk", "dengue prevention list",
    "pantry refill shortlist", "exam hall ticket reminder", "laptop repair quote", "temple donation note", "grocery price drift",
    "bus pass renewal", "water purifier candle change", "fuse box label", "milk card balance", "pharmacy refill slip",
    "property tax receipt", "terrace leak check", "train platform change", "library fine note", "noise complaint draft",
    "seed germination log", "raincoat storage", "curd starter batch", "rice sack rate check", "mixer service reminder",
    "tailor follow-up", "courier tracking note", "mediclaim document list", "college fee receipt", "milk boiler replacement",
]

GLOBAL_NOTE_TOPICS = [
    "bagel recipe notes", "museum membership", "oat milk shelf test", "bike lane detour", "laundromat token issue",
    "garden compost trial", "studio shelving", "battery drain", "portable SSD benchmark", "orchard lease",
    "ferry timing note", "gallery opening hours", "tram delay pattern", "camping stove checklist", "renters insurance note",
    "paper lamp measurements", "book club summary", "cafe Wi-Fi reliability", "greenhouse humidity note", "photo archive cleanup",
    "basement heater noise", "winter tire quote", "seed catalog picks", "sourdough starter log", "bicycle chain care",
    "public library event note", "subway closure reminder", "market stall comparison", "travel card balance", "ceramic glaze note",
]

INDIA_EXPENSE = {
    "groceries": [
        "little millet", "poha", "brown chana", "jaggery powder", "curry leaves", "aavin curd", "idhayam sesame oil", "asafoetida",
        "idli rice", "filter coffee powder", "urad dal", "toor dal", "samba wheat rava", "groundnut oil", "mustard seeds",
        "dried red chilli", "coconut", "coriander", "mint leaves", "banana stem", "drumstick", "tomato", "onion", "turmeric powder",
    ],
    "transport": [
        "auto fare", "bus fare", "suburban rail pass", "metro card topup", "share auto", "town bus pass", "platform ticket",
        "parking shuttle", "cab fare", "bike taxi", "sleeper bus fare", "local train ticket", "ferry ticket", "toll gate",
    ],
    "dining": [
        "curd rice", "veg meals", "filter coffee", "tea and bun", "parotta dinner", "masala dosa", "lemon juice", "tender coconut",
        "idiyappam breakfast", "biryani parcel", "chaat plate", "falooda", "paneer roll", "kulfi", "sandwich combo",
    ],
    "bills_utilities": [
        "EB bill", "broadband bill", "LPG refill", "water tax", "apartment maintenance", "electricity bill", "generator charge",
        "sewage charge", "gas pipeline bill", "drinking water bill", "garbage collection fee", "society sinking fund",
    ],
    "recharge_subscription": [
        "jio topup", "airtel recharge", "dth recharge", "spotify duo", "cloud backup plan", "OTT family pack", "google one",
        "hotstar annual", "net banking SMS charge", "data booster", "caller tune pack", "wifi extender plan",
    ],
    "household": [
        "floor cleaner", "mop refill", "scrub pad", "bucket", "dustbin liners", "sink strainer", "mop bucket", "detergent cake",
        "liquid detergent", "steel scrubber", "pooja oil", "match box carton", "toilet cleaner", "bleaching powder",
        "mosquito bat", "broom", "cloth clips", "gas lighter",
    ],
    "health": [
        "clinic fee", "lab test", "vitamin c syrup", "pain relief gel", "inhaler refill", "eye drops", "dental cleaning",
        "blood test", "calcium tablets", "fever tablets", "physio session", "mask pack", "glucose strips",
    ],
    "personal_care": [
        "dove soap", "lux soap", "head and shoulders", "face wash", "toothpaste combo", "body lotion", "parachute",
        "clinic plus", "sunscreen", "beard trimmer blade", "sanitary pads", "hand wash refill", "comb set",
    ],
    "education": [
        "exam fee", "course workbook", "school building fund", "executive course fee", "reference guide", "tuition notebook",
        "seminar registration", "lab manual", "entrance coaching fee", "university duplicate ID", "graph sheets", "school diary",
    ],
    "work": [
        "xerox", "courier charge", "printer paper", "domain renewal", "stationery set", "ID card lamination", "whiteboard marker",
        "packing tape", "USB drive", "co-working day pass", "document binding", "passport photo print", "register book",
    ],
    "entertainment": [
        "movie ticket", "museum admission", "cricket match ticket", "tram museum booklet", "concert pass", "streaming rental",
        "bowling lane", "theme park pass", "book fair ticket", "zoo ticket", "play ticket",
    ],
    "travel": [
        "travel sim adapter", "hostel deposit", "visa photo booth", "airport shuttle", "weekend stay booking", "luggage wrap",
        "travel pillow", "cloak room fee", "intercity taxi", "guest house advance", "boarding pass print",
    ],
    "vehicle": [
        "petrol", "diesel", "parking", "car insurance", "ev charging", "puncture repair", "chain lubricant", "air fill",
        "engine oil", "service wash", "wheel alignment", "helmet visor polish", "fastag recharge", "bike insurance",
    ],
    "shopping": [
        "raincoat", "sandal", "tote bag", "curtain fabric", "steel lunch box", "phone cover", "bedsheet", "office chair cushion",
        "water bottle", "umbrella", "slippers", "pressure cooker gasket", "lunch carrier", "school shoes", "charger cable",
    ],
    "other": [
        "temple hundi", "waiter tip", "personal loan emi", "donation box", "villa token", "community hall advance", "rent",
        "society event contribution", "tailor advance", "maid bonus", "festival donation", "ATM card replacement fee",
    ],
}

GLOBAL_EXPENSE = {
    "groceries": ["bagel", "oat milk", "tahini", "rye flour", "olive brine", "parsley", "avocado", "rice vinegar", "pita bread", "granola"],
    "transport": ["tram fare", "subway day pass", "ferry ticket", "bike-share unlock", "commuter rail ticket", "parking meter", "airport train"],
    "dining": ["ramen bowl", "sourdough toast", "coffee beans tasting", "brunch plate", "pasta lunch", "croissant and latte", "soup combo"],
    "bills_utilities": ["heating bill", "laundromat card topup", "internet fee", "tenant association fee", "water bill", "trash collection"],
    "recharge_subscription": ["music app premium", "design app subscription", "cloud archive plan", "mobile data pack", "video pass"],
    "household": ["paper napkins", "laundromat coins", "dish brush refill", "storage bins", "light bulb pack", "glass cleaner"],
    "health": ["pharmacy copay", "thermometer battery", "clinic copay", "vitamin gummies", "bandage roll"],
    "personal_care": ["shampoo refill", "body lotion", "deodorant stick", "toothpaste", "razor cartridge"],
    "education": ["workshop ticket", "research archive fee", "course reader", "online certificate", "museum lecture pass"],
    "work": ["cowork day pass", "notebook stack", "shipping label roll", "printer toner", "mailing tube"],
    "entertainment": ["gallery pass", "museum admission", "film festival ticket", "arcade card", "concert ticket"],
    "travel": ["travel sim adapter", "luggage storage", "hostel locker", "airport bus", "ferry locker"],
    "vehicle": ["parking meter", "tire pressure check", "ev charging", "bike repair", "roadside assist"],
    "shopping": ["rain jacket", "notebook A5", "usb-c cable 2m", "wool scarf", "storage basket"],
    "other": ["charity jar", "service tip", "club entry", "locker deposit", "monthly rent"],
}

INDIA_BUY = [
    "aavin curd", "idli rice", "poha", "hing", "surf excel", "lux", "dove", "scrub pad", "floor cleaner", "steel lunch box",
    "sink strainer", "asafoetida", "green tea jasmine", "coriander", "fenugreek leaves", "millets", "bulb", "notebook A5",
    "helmet", "visor cleaner", "parachute", "clinic plus", "toor dal", "urad dal", "ragi flour", "sesame oil", "mustard seeds",
    "cumin", "detergent cake", "liquid hand wash", "toothpaste", "sanitary pads", "agarbathi", "camphor", "cotton wick",
    "pooja oil", "steel tumbler", "pressure cooker gasket", "mop refill", "bath towel", "bedsheet", "mosquito coil", "match box",
    "water can", "LED tube light", "extension board", "phone charger", "USB cable", "milk packet", "paneer", "curd starter",
    "banana chips", "groundnut oil", "rice flour", "kitchen tissue", "toilet cleaner", "broom", "dustbin liners", "laundry basket",
    "coconut", "banana leaf", "tomato", "onion", "ginger garlic paste", "shaving razor", "face wash", "body lotion",
]

GLOBAL_BUY = [
    "bagel", "oat milk", "paper napkins", "hdmi cable", "printer ink", "extension cord", "cycle lock", "painter's tape",
    "marker set", "storage clips", "usb-c cable 2m", "granola", "olive oil", "dish brush", "wool socks", "rain jacket",
    "battery pack", "coffee filters", "laundry pods", "glass cleaner", "oven mitts", "cork board", "sourdough starter jar",
    "insulated bottle", "desk lamp", "bike light", "canvas tote", "toothpaste", "bandage roll", "thermal mug",
]

INDIA_TODOS = [
    "pay EB bill", "renew gas connection papers", "submit hostel reimbursement", "book train tatkal", "renew library card",
    "send rent receipt to admin", "scan passport", "refill asthma prescription", "compare sofa fabrics", "measure balcony grill",
    "pay newspaper vendor", "call tile vendor", "book eye test", "submit parking form", "return studio locker key",
    "pay school fees", "visit ration shop", "collect courier from office", "book AC maintenance", "follow up on water can delivery",
    "renew driving licence", "pay broadband bill", "check inverter battery", "send UPI screenshot", "book plumber visit",
    "drop tailoring cloth", "collect spectacles", "buy train platform ticket", "book doctor follow-up", "submit college form",
    "renew FASTag", "pay milk account", "order gas cylinder", "collect ID card", "send property tax proof",
    "check scooter insurance", "schedule pest control", "call electrician", "pay maid salary", "book car wash",
    "collect laptop from service center", "buy gift wrap", "visit bank branch", "print hall ticket", "submit PF form",
]

INDIA_TODO_NOUNS = [
    "passport renewal", "mom birthday gift", "broadband bill", "school form", "gas subsidy issue", "bike insurance",
    "bank KYC", "electricity complaint", "ration card update", "vaccination certificate print", "hostel gate pass",
    "water tax receipt", "property papers", "tailor balance", "scooter service", "medical claim", "milk account",
    "parking renewal", "train refund", "college bonafide letter",
]

GLOBAL_TODOS = [
    "call landlord", "book bike service", "renew museum card", "send HOA email", "print visa copy", "check boiler service",
    "email residency host", "book dental cleaning", "renew transit pass", "drop package at locker", "call plumber",
    "book studio inspection", "pay utility bill", "schedule recycling pickup", "renew library membership", "check mailroom parcel",
    "book haircut", "send renter insurance proof", "collect laundry", "update parking permit", "pay daycare fee",
]

GLOBAL_TODO_NOUNS = [
    "laundromat card", "orchard lease", "gallery membership", "renters insurance", "garden permit", "storage locker",
    "parking permit", "visa copy", "bike registration", "boiler service",
]

INDIA_LEDGER_REASONS = [
    "rent share", "train tickets", "dinner bill", "UPI transfer", "movie tickets", "pharmacy pickup", "cab split",
    "hostel mess advance", "festival shopping", "wedding contribution", "tea stall bill", "milk account", "petrol split",
    "grocery share", "platform ticket", "college notes print", "lunch parcel", "bus ticket bundle", "doctor fee share",
    "water can payment", "apartment maintenance share", "tailor advance", "room deposit", "internet bill share",
    "school van fee", "gift contribution", "temple trip", "catering advance", "electrician cash", "repair share",
]

GLOBAL_LEDGER_REASONS = [
    "museum pass", "studio deposit", "brunch bill", "hostel booking", "ferry tickets", "gallery pass", "groceries split",
    "subway card", "bike repair", "camping permit", "shared dinner", "internet split", "rental deposit", "laundry card",
    "book fair tickets",
]

SINGLE_DATE_OPTIONS = [
    (None, "2026-05-05"), ("today", "2026-05-05"), ("yesterday", "2026-05-04"), ("last sunday", "2026-05-03"),
    ("on may 1", "2026-05-01"), ("on may 9", "2026-05-09"), ("friday", "2026-05-08"), ("next monday", "2026-05-11"),
    ("tomorrow", "2026-05-06"), ("this morning", "2026-05-05"), ("last night", "2026-05-04"), ("monday", "2026-05-04"),
    ("tuesday", "2026-05-05"), ("wednesday", "2026-05-06"), ("thursday", "2026-05-07"), ("saturday", "2026-05-09"),
    ("last friday", "2026-05-01"), ("last monday", "2026-04-27"), ("first may", "2026-05-01"), ("may 5", "2026-05-05"),
    ("on 5 may", "2026-05-05"), ("this evening", "2026-05-05"), ("early morning", "2026-05-05"), ("weekend", "2026-05-09"),
]

RANGE_OPTIONS = {
    "today": ("2026-05-05", "2026-05-05"),
    "yesterday": ("2026-05-04", "2026-05-04"),
    "last sunday": ("2026-05-03", "2026-05-03"),
    "this week": ("2026-05-04", "2026-05-10"),
    "last week": ("2026-04-27", "2026-05-03"),
    "this month": ("2026-05-01", "2026-05-31"),
    "current month": ("2026-05-01", "2026-05-31"),
    "month to date": ("2026-05-01", "2026-05-05"),
    "last month": ("2026-04-01", "2026-04-30"),
    "april": ("2026-04-01", "2026-04-30"),
    "may": ("2026-05-01", "2026-05-31"),
    "january": ("2026-01-01", "2026-01-31"),
    "since january": ("2026-01-01", "2026-05-05"),
    "on may 1": ("2026-05-01", "2026-05-01"),
    "on may 9": ("2026-05-09", "2026-05-09"),
    "may 12": ("2026-05-12", "2026-05-12"),
    "last 7 days": ("2026-04-29", "2026-05-05"),
    "past 10 days": ("2026-04-26", "2026-05-05"),
    "first week of may": ("2026-05-01", "2026-05-07"),
    "second week of may": ("2026-05-08", "2026-05-14"),
    "weekend": ("2026-05-09", "2026-05-10"),
    "monday": ("2026-05-04", "2026-05-04"),
    "friday": ("2026-05-08", "2026-05-08"),
    "this quarter": ("2026-04-01", "2026-06-30"),
}

# Expansion pass: materially broaden the source pools so the large synthetic run
# has enough effective diversity instead of only a large row count.

INDIA_NAMES += [
    "Abirami", "Adhavan", "Agalya", "Akshara", "Ammu", "Amudha", "Anbarasu", "Anirudh", "Arasi", "Arthi",
    "Arunmozhi", "Aswathy", "Azhagu", "Balaji", "Bavithra", "Bhuvi", "Chandru", "Chandrika", "Dharani", "Dheena",
    "Dhiya", "Dileep", "Elakkiya", "Esakki", "Feroz", "Gayu", "Gomathi", "Guna", "Hameed", "Hareesh",
    "Hasini", "Hemavathi", "Ilakkiya", "Imran", "Inba", "Janarthan", "Janvi", "Jayanthi", "Jegan", "Jothi",
    "Kabilan", "Kajal", "Kani", "Kanimozhi", "Karthikeyan", "Kausalya", "Kavitha", "Kayal", "Khadeeja", "Kowsi",
    "Krupa", "Logesh", "Madesh", "Magesh", "Mahalakshmi", "Malar", "Mariya", "Mersy", "Mugilan", "Murugan",
    "Nagaraj", "Nalini", "Naveena", "Nethra", "Nivetha", "Padma", "Pandi", "Pooja", "Poornima", "Prasanna",
    "Preethi", "Punitha", "Raagul", "Raja", "Rajalakshmi", "Raji", "Ramesh", "Ranjith", "Reshma", "Roja",
    "Sadiq", "Sakina", "Sangeetha", "Sanjay", "Santhiya", "Sathya", "Senthil", "Shafeeq", "Sharmila", "Sheela",
    "Sherin", "Shyam", "Siddhu", "Sowbarnika", "Srihari", "Srinidhi", "Suhana", "Surya", "Tamilselvi", "Thilaga",
    "Thiru", "Udhaya", "Umadevi", "Valli", "Vanitha", "Vasanthi", "Veena", "Velmurugan", "Venkatesh", "Vetri",
    "Vinitha", "Viswa", "Yaalini", "Yuvan", "abi", "akkaa", "annan", "periamma", "periappa", "machan",
    "machi", "sithi", "sithappa", "mama", "mottaimaadi paati", "athimber", "anni", "marumagal", "periamma", "thambi paiyan",
    "Archana", "Baskaran", "Chinmayi", "Dharshan", "Ezhil", "Fathima Beevi", "Ganesan", "Hema", "Ilamaran", "Jayanth",
    "Kowsalya", "Lokeshwari", "Mahal", "Nataraj", "Poonkodi", "Rithanya", "Shree", "Thivya", "Vimal", "Yuvaraj",
]

GLOBAL_NAMES += [
    "Adrian", "Alicia", "Amelia", "Andre", "Anya", "Arlo", "Astrid", "Audrey", "Benedict", "Blair",
    "Bruno", "Cassia", "Celine", "Cora", "Diego", "Edith", "Elliot", "Emmett", "Esther", "Etta",
    "Flora", "Freya", "Gideon", "Hazel", "Helena", "Imogen", "Ivy", "Jude", "Kieran", "Laila",
    "Levi", "Lila", "Louisa", "Maeve", "Magnus", "Nadia", "Orion", "Penny", "Phoebe", "Rory",
    "Rosalie", "Rowan", "Sabine", "Selma", "Silas", "Tessa", "Valerie", "Willa", "Yvette", "Zelda",
]

INDIA_NOTE_TOPICS += [
    "auto stand complaint", "milk packet count", "UPI refund check", "vegetable rate note", "balcony plant pruning",
    "ceiling fan wobble", "EB office visit", "scooter service quote", "borrowed vessel reminder", "grocery shelf labels",
    "UPS battery backup", "festival leave plan", "school van timing", "monthly provision list", "fridge door gasket",
    "rice cooker switch issue", "travel flask leak", "temple prasadam token", "hall curtain measurement", "ceiling seepage photo",
    "kitchen exhaust cleaning", "printer cable check", "mobile recharge comparison", "bus route diversion", "tailor blouse delay",
    "loan EMI reminder", "electric stove coil issue", "water motor switch", "neem oil spray mix", "pickle jar refill",
    "flower vendor balance", "veetu vaasal cleaning", "rainwater drum lid", "medicine strip count", "wifi dead zone",
    "phone storage cleanup", "receipt envelope", "festival train waiting list", "spice dabba refill", "laptop hinge crack",
    "tap leak recording", "tea dust comparison", "scooter key duplicate", "helmet visor scratch", "milk sweet trial",
    "apartment notice draft", "resident welfare dues", "fridge freezer icing", "mosquito net fitting", "old charger sorting",
    "EB due date reminder", "gas lighter spark issue", "ash gourd recipe note", "terrace cloth line", "voter ID xerox",
    "water sump schedule", "neighbour borrowing list", "medical store balance", "temple visit expense note", "idli batter fermentation",
]

GLOBAL_NOTE_TOPICS += [
    "parking permit renewal", "shared kitchen cleanup", "bus detour memo", "coffee grinder settings", "attic storage list",
    "garden hose leak", "hostel key deposit", "library printer issue", "window seal draft", "subway map shortcut",
    "museum audio guide note", "flea market shortlist", "green tea steep test", "cable organizer sizes", "winter glove comparison",
    "bakery queue timing", "film roll storage", "kettle limescale", "book donation drop", "bicycle bell replacement",
    "toolbox label plan", "neighborhood watch note", "street market budget", "public fountain hours", "guest room checklist",
    "weekend ferry timing", "office locker code", "seedling tray depth", "garden bench repair", "umbrella stand note",
]

INDIA_EXPENSE["groceries"].extend([
    "capsicum", "brinjal", "beetroot", "raw banana", "bottle gourd", "cabbage", "cauliflower", "green peas",
    "sambar powder", "rasam powder", "pepper", "jeera", "cashew", "almonds", "raisins", "ghee",
    "paneer", "curd chilli", "papad", "rava", "maida", "besan", "semiya", "aval",
])
INDIA_EXPENSE["transport"].extend([
    "MTC bus ticket", "OMR toll", "parking token", "subway foot overbridge ticket", "electric shuttle", "share cab",
    "bus depot pass", "railway reservation charge", "night auto fare", "station bike stand", "city bus change",
    "monthly metro pass", "tourist bus fare", "school van extra trip",
])
INDIA_EXPENSE["dining"].extend([
    "mini tiffin", "meals parcel", "vada combo", "idli set", "pongal breakfast", "kothu parotta", "fried rice",
    "juice shop bill", "samosa tea", "pani puri", "ice cream cup", "naan gravy combo", "family biryani bucket",
    "biscuit tea", "snack packet",
])
INDIA_EXPENSE["bills_utilities"].extend([
    "wifi bill", "mobile postpaid bill", "RO service charge", "septic tank fee", "drain cleaning fee", "UPS AMC",
    "apartment lift maintenance", "sump cleaning charge", "watchman fund", "security charge", "society corpus fee", "generator diesel share",
])
INDIA_EXPENSE["recharge_subscription"].extend([
    "vi recharge", "bsnl topup", "youtube premium", "amazon prime", "netflix share", "gaana plan",
    "classroom app renewal", "antivirus renewal", "drive storage topup", "broadband extra data", "annual caller ID plan", "family cloud storage",
])
INDIA_EXPENSE["household"].extend([
    "steel wool", "plastic mug", "soap box", "kitchen towel", "door mat", "napkin pack",
    "vessel scrub", "sponge wipe", "drain cover", "shoe rack hook", "cloth hanger", "curtain ring",
    "room freshener", "phenyl", "hand broom", "stool",
])
INDIA_EXPENSE["health"].extend([
    "multivitamin tablets", "BP checkup", "X-ray fee", "scan fee", "ointment", "bandage roll",
    "saline wash", "doctor review fee", "nutrition powder", "cough syrup", "ENT consultation", "physio tape", "eye checkup",
])
INDIA_EXPENSE["personal_care"].extend([
    "hair oil", "shaving foam", "trimmer service", "lip balm", "nail cutter", "comb",
    "body wash", "face cream", "hair serum", "detan pack", "face towel", "hair clips", "sanitizer bottle",
])
INDIA_EXPENSE["education"].extend([
    "record notebook", "practical fees", "lab coat", "model exam fee", "library deposit", "private tuition",
    "school shoes polish", "geometry box", "student ID reprint", "question bank", "certificate attestation", "project chart paper",
])
INDIA_EXPENSE["work"].extend([
    "A4 sheet bundle", "visiting card print", "spiral binding", "brown cover", "stapler pins", "ink bottle",
    "shipping carton", "bubble wrap", "sim recharge for work phone", "file folder", "ledger book", "sign board print", "pen drive",
])
INDIA_EXPENSE["entertainment"].extend([
    "match snacks", "carnival entry", "amusement ride ticket", "comedy show ticket", "gaming center card", "aquarium ticket",
    "book exhibition entry", "children park ticket", "board game cafe", "music event pass", "planetarium ticket",
])
INDIA_EXPENSE["travel"].extend([
    "cab to airport", "railway retiring room", "interstate bus booking", "hotel breakfast add-on", "travel pouch",
    "adapter plug", "airport trolley fee", "tour guide tip", "hotel laundry", "resort advance", "travel medicine kit",
])
INDIA_EXPENSE["vehicle"].extend([
    "clutch cable", "brake shoe", "seat cover wash", "seat belt clip", "wiper blade", "number plate frame",
    "radiator coolant", "spark plug", "battery water", "chain sprocket", "puncture patch", "silencer weld", "seat polish", "mirror replacement",
])
INDIA_EXPENSE["shopping"].extend([
    "school bag", "dupatta", "tiffin bag", "kitchen stool", "curtain rod", "shoe rack", "pillow cover", "travel pouch",
    "spectacle frame", "door curtain", "ladies handbag", "water jug", "mobile stand", "mixer jar", "storage box",
])
INDIA_EXPENSE["other"].extend([
    "house rent", "advance token", "bank charge", "ATM fee", "community fund", "wedding envelope",
    "charity contribution", "festive bonus", "license fee", "municipal penalty", "society notice fine", "lucky draw coupon",
    "vehicle document xerox", "apartment guest pass",
])

GLOBAL_EXPENSE["groceries"].extend(["spinach", "blueberries", "greek yogurt", "couscous", "hummus", "mushrooms", "pumpkin seeds", "sparkling water", "pesto", "wrap bread"])
GLOBAL_EXPENSE["transport"].extend(["bus transfer", "parking garage", "regional rail fare", "train seat reservation", "scooter unlock", "bridge toll", "airport shuttle"])
GLOBAL_EXPENSE["dining"].extend(["taco plate", "espresso tonic", "noodle soup", "bakery lunch", "burger combo", "crepe", "salad bowl"])
GLOBAL_EXPENSE["bills_utilities"].extend(["electric bill", "water sewer bill", "building maintenance", "router rental", "recycling fee", "gas bill"])
GLOBAL_EXPENSE["recharge_subscription"].extend(["phone topup", "news subscription", "podcast premium", "backup storage", "fitness app plan"])
GLOBAL_EXPENSE["household"].extend(["trash bags", "dish soap", "microfiber cloth", "drawer liners", "paper towels", "vacuum bags"])
GLOBAL_EXPENSE["health"].extend(["urgent care copay", "pain tablets", "saline spray", "vitamin D", "therapy copay"])
GLOBAL_EXPENSE["personal_care"].extend(["conditioner", "hand cream", "face cleanser", "sunscreen", "hair wax"])
GLOBAL_EXPENSE["education"].extend(["course certificate fee", "printed reader", "study pass", "class materials", "online workshop"])
GLOBAL_EXPENSE["work"].extend(["mailing envelope", "file boxes", "desk pad", "shipping tape", "label sheets"])
GLOBAL_EXPENSE["entertainment"].extend(["theater balcony ticket", "concert merch", "streaming bundle", "comic fair pass", "sports ticket"])
GLOBAL_EXPENSE["travel"].extend(["carry-on fee", "seat selection", "locker rental", "travel insurance", "city pass"])
GLOBAL_EXPENSE["vehicle"].extend(["car wash token", "oil top-off", "windshield fluid", "garage fee", "battery jump service"])
GLOBAL_EXPENSE["shopping"].extend(["sneakers", "duffel bag", "phone tripod", "sweater", "desk organizer"])
GLOBAL_EXPENSE["other"].extend(["tips jar", "donation kiosk", "rent payment", "club locker fee", "late fee"])

INDIA_BUY += [
    "sambar powder", "rasam powder", "pepper", "jeera", "cashew", "almonds", "paper plates", "vessel scrubber",
    "hand towels", "pressure cooker whistle", "stapler pins", "A4 sheets", "chart paper", "whiteboard duster",
    "school socks", "sports bottle", "travel pouch", "mask pack", "multivitamin", "eyedrops", "cough syrup",
    "body wash", "hair oil", "shampoo sachet", "biscuit packet", "rusk", "murukku", "mixture packet",
    "dhoop sticks", "pooja flowers", "battery cells", "torch light", "LED bulb", "fan capacitor",
    "water bottle cap", "shoe polish", "nail cutter", "cloth clips", "bucket mug set", "dust pan",
    "tea dust", "sugar", "salt", "tamarind", "rice bran oil", "curd chilli", "pickle jar",
    "ponni rice", "basmati rice", "atta", "maida", "besan", "semiya", "rava", "papad",
    "curtain hooks", "extension wire", "safety pins", "rubber bands", "notepad", "pen pack",
    "bindi packet", "hair clips", "broom stick", "wet wipes", "dettol", "phenyl bottle",
]

GLOBAL_BUY += [
    "dish soap", "paper towels", "granola bars", "yogurt cups", "pasta sauce", "mushrooms", "spinach",
    "scented candles", "AA batteries", "flashlight", "duct tape", "mailers", "command hooks",
    "blanket", "desk organizer", "laptop sleeve", "shoe insoles", "sunscreen", "deodorant",
    "razor cartridges", "coffee beans", "tea infuser", "measuring cups", "silicone spatula",
    "laundry basket", "notebook", "pens", "screen wipes", "bike pump", "water filter",
]

INDIA_TODOS += [
    "renew Aadhaar address", "collect ration card xerox", "pay tuition fees", "call milk vendor", "book gas stove service",
    "submit courier claim", "buy medicine for amma", "recharge metro card", "check water motor", "renew SIM KYC",
    "submit PAN copy", "print travel ticket", "call school office", "book temple hall", "check EB complaint status",
    "collect ironed clothes", "follow up on passport", "book courier pickup", "renew tenant agreement", "pay RO service bill",
    "send invoice reminder", "update bank nominee", "get xerox set", "clean inverter area", "fix bathroom latch",
    "renew health insurance", "collect tailor blouse", "call bike mechanic", "submit reimbursement bill", "buy pooja items",
    "book pest service", "pick up lab report", "check LPG subsidy", "pay apartment dues", "collect parcel from gate",
    "book driving class", "scan school circular", "top up FASTag", "ask plumber for estimate", "return borrowed vessel",
    "check gas leak complaint", "upload KYC document", "renew exam registration", "get locker key copy", "close old wallet card",
]

INDIA_TODO_NOUNS += [
    "temple hall booking", "Aadhaar update", "PAN copy", "tenant agreement", "school fee slip",
    "bike RC renewal", "FASTag topup", "RO service", "locker key copy", "gas booking",
    "UPI refund", "tailor delivery", "bike wash", "annual checkup", "milk account balance",
    "library fine", "water motor issue", "electricity payment", "ration restock", "property lease",
]

GLOBAL_TODOS += [
    "renew renters permit", "schedule HVAC check", "email tax preparer", "return library books", "book dentist follow-up",
    "call internet provider", "submit parking appeal", "renew storage access", "check attic leak", "collect repaired bike",
    "send gallery RSVP", "update train card", "pick up prescription", "pay school lunch fee", "arrange moving boxes",
    "renew gym membership", "call recycling office", "replace smoke alarm battery", "book ferry trip", "submit tenant form",
    "order heating oil", "book passport photo", "call appliance repair", "collect mail package",
]

GLOBAL_TODO_NOUNS += [
    "transit pass", "heating bill", "mailroom parcel", "building key fob", "storage invoice",
    "bike tune-up", "museum pass", "daycare form", "passport photo", "roof repair",
]

INDIA_LEDGER_REASONS += [
    "tea kadai bill", "auto share", "canteen snacks", "hostel room key deposit", "train snack bill", "wedding gift cover",
    "trip advance", "puja items", "ice cream split", "tailor amount", "internet recharge split", "milk packet share",
    "movie parking", "doctor consultation split", "photocopy amount", "college fee advance", "grocery token", "station food bill",
    "school notebook share", "tiffin parcel", "water bottle crate", "sweet box split", "generator diesel share", "temple hundi pool",
    "garland payment", "travel bag advance", "festival lights", "book fair books", "repair token", "bus change shortage",
]

GLOBAL_LEDGER_REASONS += [
    "hostel kitchen groceries", "movie night snacks", "parking garage fee", "city pass", "brunch coffee",
    "shared taxi", "locker deposit", "studio snacks", "museum cafe bill", "printer refill",
    "photo booth", "train card topup", "camping fuel", "market haul", "bicycle tube",
]

SINGLE_DATE_OPTIONS += [
    ("this afternoon", "2026-05-05"), ("this noon", "2026-05-05"), ("tonight", "2026-05-05"), ("last evening", "2026-05-04"),
    ("last tuesday", "2026-04-28"), ("last thursday", "2026-04-30"), ("next friday", "2026-05-15"), ("next saturday", "2026-05-16"),
    ("may 1st", "2026-05-01"), ("may 2", "2026-05-02"), ("may 3", "2026-05-03"), ("may 4", "2026-05-04"),
    ("may 6", "2026-05-06"), ("may 7", "2026-05-07"), ("on 1 may", "2026-05-01"), ("on 9 may", "2026-05-09"),
    ("week beginning", "2026-05-04"), ("week close", "2026-05-10"), ("month start", "2026-05-01"), ("month end", "2026-05-31"),
    ("two days ago", "2026-05-03"), ("three days ago", "2026-05-02"), ("this weekend", "2026-05-09"), ("coming monday", "2026-05-11"),
]

RANGE_OPTIONS.update({
    "last tuesday": ("2026-04-28", "2026-04-28"),
    "last thursday": ("2026-04-30", "2026-04-30"),
    "monday to friday": ("2026-05-04", "2026-05-08"),
    "first half of may": ("2026-05-01", "2026-05-15"),
    "second half of april": ("2026-04-16", "2026-04-30"),
    "last 3 days": ("2026-05-03", "2026-05-05"),
    "past 2 weeks": ("2026-04-22", "2026-05-05"),
    "past month": ("2026-04-06", "2026-05-05"),
    "from april 1 to april 15": ("2026-04-01", "2026-04-15"),
    "from april 16 to april 30": ("2026-04-16", "2026-04-30"),
    "from may 1 to may 5": ("2026-05-01", "2026-05-05"),
    "from may 6 to may 10": ("2026-05-06", "2026-05-10"),
    "last business week": ("2026-04-27", "2026-05-01"),
    "week before last": ("2026-04-20", "2026-04-26"),
    "april first week": ("2026-04-01", "2026-04-07"),
    "april second week": ("2026-04-08", "2026-04-14"),
    "april third week": ("2026-04-15", "2026-04-21"),
    "april fourth week": ("2026-04-22", "2026-04-30"),
    "this financial quarter": ("2026-04-01", "2026-06-30"),
    "this financial year": ("2026-04-01", "2027-03-31"),
    "last 30 days": ("2026-04-06", "2026-05-05"),
    "last 60 days": ("2026-03-07", "2026-05-05"),
    "quarter to date": ("2026-04-01", "2026-05-05"),
    "year to date": ("2026-01-01", "2026-05-05"),
})


def _extend_unique(target, values):
    seen = set(target)
    for value in values:
        if value not in seen:
            target.append(value)
            seen.add(value)


# Expansion pass 2: broaden by coverage dimensions, not just raw count.

_extend_unique(INDIA_NAMES, [
    "Aaradhya", "Aarav", "Aarohi", "Aayush", "Abdul", "Abha", "Abhishek", "Aditi", "Adnan", "Aishwarya",
    "Akanksha", "Alok", "Aman", "Amina", "Aniket", "Ankita", "Anmol", "Ansh", "Anusha", "Armaan",
    "Arnav", "Arpita", "Arshad", "Arvind", "Asmita", "Ayub", "Badri", "Bhargav", "Bhavana", "Bimal",
    "Bipasha", "Chaitanya", "Chandan", "Chetan", "Daivik", "Damini", "Darshana", "Debashish", "Debolina", "Deeksha",
    "Devansh", "Devika", "Dharmesh", "Diksha", "Dinesh", "Ekta", "Farhan", "Gargi", "Gaurav", "Geeta",
    "Govind", "Gurpreet", "Hafsa", "Harleen", "Harpreet", "Harshita", "Himanshu", "Hrithik", "Ila", "Irfana",
    "Jagdish", "Jasleen", "Jatin", "Jhanvi", "Kajal", "Kamal", "Kanishka", "Kapil", "Karan", "Karishma",
    "Khushi", "Komal", "Kunal", "Kusum", "Manav", "Manisha", "Mansi", "Mayank", "Meher", "Mohit",
    "Monika", "Mukesh", "Muskaan", "Naina", "Nakul", "Namrata", "Neel", "Neha", "Nikita", "Nitin",
    "Palak", "Pankaj", "Pooja", "Pratik", "Preeti", "Rachana", "Rahul", "Rakesh", "Ria", "Ritika",
    "Rohan", "Saanvi", "Saba", "Sahil", "Sakshi", "Salman", "Sameer", "Sana", "Sandeep", "Sapna",
    "Shalini", "Shanaya", "Shivam", "Shreya", "Simran", "Sonal", "Soumya", "Srishti", "Sujit", "Sunaina",
    "Sunil", "Tanmay", "Tanya", "Tarini", "Tejas", "Trisha", "Urvashi", "Vaibhav", "Vandana", "Vedant",
    "Vidit", "Yash", "Yashika", "Zubin", "bahu", "bhabhi", "bhaiya", "dada", "dadi", "jiju",
    "nani", "nana", "tauji", "taiji", "foofi", "khalu", "khala", "bua", "massi", "veer",
    "didi", "bhabho", "papa", "mummy", "nanad", "devar", "jeth", "jethani", "saas", "sasur",
])

_extend_unique(GLOBAL_NAMES, [
    "Aiko", "Akira", "Amira", "Anton", "Aya", "Bao", "Beatriz", "Cairo", "Chiara", "Dmitri",
    "Elio", "Enzo", "Farid", "Fatou", "Gianna", "Hana", "Idris", "Inga", "Jamal", "Jin",
    "Kaito", "Karim", "Leandro", "Lin", "Mina", "Nia", "Noa", "Omar", "Pavel", "Rina",
    "Sami", "Sora", "Tariq", "Thiago", "Yuna", "Zuri", "Amadou", "Dalia", "Khadija", "Lucia",
    "Mateo", "Nikos", "Priam", "Ren", "Soraya", "Tari", "Yelena", "Zoya", "Amina", "Bastien",
    "Cosmo", "Elara", "Farah", "Giulio", "Hiro", "Ilias", "Jovana", "Klara", "Lior", "Mika",
    "Noura", "Otto", "Petra", "Rami", "Safa", "Tibor", "Ugo", "Violeta", "Yusuf", "Ziad",
])

_INDIA_HOME_SUBJECTS = [
    "mixie jar", "ceiling light", "balcony drain", "shoe rack", "kitchen shelf", "RO filter", "water drum", "TV remote",
    "geyser switch", "door latch", "study table", "cloth stand", "mosquito screen", "rice container", "fridge tray", "washing area",
]
_INDIA_HOME_ISSUES = [
    "cleaning plan", "repair note", "replacement idea", "price check", "service reminder", "noise check", "measurement", "restock note",
]
_extend_unique(INDIA_NOTE_TOPICS, [f"{a} {b}" for a in _INDIA_HOME_SUBJECTS for b in _INDIA_HOME_ISSUES])

_INDIA_FINANCE_SUBJECTS = [
    "Aadhaar xerox", "PAN copy", "rent receipt", "school fees", "medical bill", "FASTag balance", "UPI limit", "bank passbook",
    "postpaid bill", "insurance premium", "loan EMI", "reimbursement file", "gas subsidy", "property tax", "maintenance receipt",
]
_INDIA_FINANCE_ACTIONS = [
    "follow-up", "status note", "submission checklist", "due reminder", "proof copy", "pending issue", "payment confirmation", "renewal note",
]
_extend_unique(INDIA_NOTE_TOPICS, [f"{a} {b}" for a in _INDIA_FINANCE_SUBJECTS for b in _INDIA_FINANCE_ACTIONS])

_GLOBAL_HOME_SUBJECTS = [
    "garage shelf", "window blind", "air vent", "laundry corner", "bike rack", "mailbox key", "dish rack", "closet rail",
    "heater knob", "garden hose", "storage crate", "desk cable", "hallway light", "attic ladder", "sink filter",
]
_GLOBAL_HOME_ISSUES = [
    "cleanup note", "repair idea", "size check", "replacement plan", "cost note", "service reminder", "storage note", "test note",
]
_extend_unique(GLOBAL_NOTE_TOPICS, [f"{a} {b}" for a in _GLOBAL_HOME_SUBJECTS for b in _GLOBAL_HOME_ISSUES])

_INDIA_GROCERY_BRANDS = ["Aashirvaad", "Tata Sampann", "24 Mantra", "MTR", "Anil", "Priya", "Amul", "Nandini", "Patanjali", "Fortune"]
_INDIA_GROCERY_PRODUCTS = ["atta", "salt", "toor dal", "urad dal", "besan", "rava", "ghee", "turmeric powder", "chilli powder", "jeera"]
_extend_unique(INDIA_EXPENSE["groceries"], [f"{b} {p}" for b in _INDIA_GROCERY_BRANDS for p in _INDIA_GROCERY_PRODUCTS])

_INDIA_HOUSEHOLD_BRANDS = ["Harpic", "Lizol", "Vim", "Scotch-Brite", "Exo", "Comfort", "Ariel", "Pril"]
_INDIA_HOUSEHOLD_PRODUCTS = ["toilet cleaner", "floor cleaner", "dish wash", "scrub pad", "fabric conditioner", "liquid detergent", "glass cleaner"]
_extend_unique(INDIA_EXPENSE["household"], [f"{b} {p}" for b in _INDIA_HOUSEHOLD_BRANDS for p in _INDIA_HOUSEHOLD_PRODUCTS])

_INDIA_PERSONAL_CARE_BRANDS = ["Clinic Plus", "Dove", "Lux", "Pears", "Patanjali", "Nivea", "Ponds", "Gillette", "Parachute", "Himalaya"]
_INDIA_PERSONAL_CARE_PRODUCTS = ["soap", "shampoo", "face wash", "body lotion", "hair oil", "sunscreen", "razor", "hand wash"]
_extend_unique(INDIA_EXPENSE["personal_care"], [f"{b} {p}" for b in _INDIA_PERSONAL_CARE_BRANDS for p in _INDIA_PERSONAL_CARE_PRODUCTS])

_INDIA_RECHARGE_PROVIDERS = ["Jio", "Airtel", "Vi", "BSNL", "Hotstar", "Netflix", "Prime", "Spotify", "Google One"]
_INDIA_RECHARGE_TYPES = ["topup", "monthly plan", "data booster", "family pack", "annual recharge", "storage plan", "OTT renewal"]
_extend_unique(INDIA_EXPENSE["recharge_subscription"], [f"{p} {t}" for p in _INDIA_RECHARGE_PROVIDERS for t in _INDIA_RECHARGE_TYPES])

_INDIA_HEALTH_CONTEXTS = ["blood sugar test", "thyroid test", "vitamin B12 test", "dental filling", "BP medicine", "arthritis gel", "cough tablet", "scan review"]
_extend_unique(INDIA_EXPENSE["health"], _INDIA_HEALTH_CONTEXTS)

_INDIA_EDU_CONTEXTS = ["semester fee", "coaching center fee", "project printout", "lab record", "exam application", "school transport fee", "hostel fine", "ID reissue"]
_extend_unique(INDIA_EXPENSE["education"], _INDIA_EDU_CONTEXTS)

_INDIA_WORK_CONTEXTS = ["invoice print", "courier packet", "shipping pouch", "marker refill", "laser print", "file separator", "barcode sticker", "desk calendar"]
_extend_unique(INDIA_EXPENSE["work"], _INDIA_WORK_CONTEXTS)

_INDIA_ENT_CONTEXTS = ["multiplex snacks", "OTT rental", "stadium parking", "amusement park pass", "comedy night ticket", "live music cover", "kids play zone"]
_extend_unique(INDIA_EXPENSE["entertainment"], _INDIA_ENT_CONTEXTS)

_INDIA_TRAVEL_CONTEXTS = ["window seat charge", "tour bus fee", "resort tax", "hotel kettle deposit", "train blanket charge", "travel pouch zipper", "rain cover"]
_extend_unique(INDIA_EXPENSE["travel"], _INDIA_TRAVEL_CONTEXTS)

_INDIA_VEHICLE_CONTEXTS = ["bike tube", "scooter wash", "helmet strap", "pollution certificate", "battery replacement", "service labor", "petrol bunk air fill"]
_extend_unique(INDIA_EXPENSE["vehicle"], _INDIA_VEHICLE_CONTEXTS)

_INDIA_SHOPPING_CONTEXTS = ["kurta", "legging", "sports shoes", "backpack", "wallet", "tiffin carrier", "study lamp", "folding chair", "curtain tie", "travel bottle"]
_extend_unique(INDIA_EXPENSE["shopping"], _INDIA_SHOPPING_CONTEXTS)

_INDIA_OTHER_CONTEXTS = ["creche fee", "home tutor advance", "security deposit", "festival seer contribution", "building penalty", "admission advance", "tuition balance", "helper advance"]
_extend_unique(INDIA_EXPENSE["other"], _INDIA_OTHER_CONTEXTS)

_GLOBAL_GROCERY_BRANDS = ["Trader Joe's", "Whole Foods", "Tesco", "Aldi", "Lidl", "Waitrose"]
_GLOBAL_GROCERY_PRODUCTS = ["oats", "greek yogurt", "hummus", "olive oil", "pasta sauce", "sparkling water", "granola", "mushrooms"]
_extend_unique(GLOBAL_EXPENSE["groceries"], [f"{b} {p}" for b in _GLOBAL_GROCERY_BRANDS for p in _GLOBAL_GROCERY_PRODUCTS])

_GLOBAL_HOUSEHOLD_CONTEXTS = ["dishwashing liquid", "paper towel roll", "laundry softener", "vacuum filter", "surface spray", "bathroom cleaner", "trash liner", "drawer organizer"]
_extend_unique(GLOBAL_EXPENSE["household"], _GLOBAL_HOUSEHOLD_CONTEXTS)

_GLOBAL_PERSONAL_CARE_CONTEXTS = ["beard oil", "moisturizer", "lip balm", "shower gel", "face scrub", "hair conditioner", "electric razor head"]
_extend_unique(GLOBAL_EXPENSE["personal_care"], _GLOBAL_PERSONAL_CARE_CONTEXTS)

_GLOBAL_RECHARGE_CONTEXTS = ["phone monthly plan", "streaming bundle", "cloud storage", "news subscription", "fitness app", "backup plan", "family pass"]
_extend_unique(GLOBAL_EXPENSE["recharge_subscription"], _GLOBAL_RECHARGE_CONTEXTS)

_GLOBAL_TRAVEL_CONTEXTS = ["museum city pass", "seat reservation", "travel pillow cover", "airport locker", "railcard renewal", "hostel linen fee", "carry-on tag"]
_extend_unique(GLOBAL_EXPENSE["travel"], _GLOBAL_TRAVEL_CONTEXTS)

_GLOBAL_VEHICLE_CONTEXTS = ["parking receipt", "garage service", "battery charge", "winter tire swap", "bike lock cable", "fuel additive", "inspection fee"]
_extend_unique(GLOBAL_EXPENSE["vehicle"], _GLOBAL_VEHICLE_CONTEXTS)

_extend_unique(INDIA_BUY, INDIA_EXPENSE["groceries"])
_extend_unique(INDIA_BUY, INDIA_EXPENSE["household"])
_extend_unique(INDIA_BUY, INDIA_EXPENSE["personal_care"])
_extend_unique(INDIA_BUY, INDIA_EXPENSE["shopping"])
# v2 cleanup: do not extend INDIA_BUY with INDIA_EXPENSE["work"] /
# ["education"]. Those pools contain fees and services (school building fund,
# certificate attestation, cowork day pass, etc.) that are not buy-list items
# and were leaking into multi-entry buy rows.

_extend_unique(GLOBAL_BUY, GLOBAL_EXPENSE["groceries"])
_extend_unique(GLOBAL_BUY, GLOBAL_EXPENSE["household"])
_extend_unique(GLOBAL_BUY, GLOBAL_EXPENSE["shopping"])
_extend_unique(GLOBAL_BUY, GLOBAL_EXPENSE["work"])

_TODO_VERBS = ["pay", "renew", "book", "call", "submit", "collect", "check", "send", "visit", "schedule", "fix", "top up", "print", "scan", "update"]
_TODO_OBJECTS_INDIA = [
    "electricity bill", "water tax", "broadband bill", "school form", "bank KYC", "passport copy", "tailor order", "bike service",
    "medical bill", "gas booking", "property tax", "parking renewal", "milk account", "exam application", "courier receipt", "insurance premium",
    "train ticket", "plumber estimate", "Aadhaar copy", "PAN update", "maintenance due", "RO service", "lab report", "festival shopping list",
]
_extend_unique(INDIA_TODOS, [f"{v} {o}" for v in _TODO_VERBS for o in _TODO_OBJECTS_INDIA])

_TODO_OBJECTS_GLOBAL = [
    "utility bill", "parking permit", "laundry pickup", "bike repair", "library return", "boiler service", "renters permit",
    "storage invoice", "mail package", "heating bill", "garden waste pickup", "museum pass", "passport photo", "tenant form",
]
_extend_unique(GLOBAL_TODOS, [f"{v} {o}" for v in _TODO_VERBS for o in _TODO_OBJECTS_GLOBAL])

_extend_unique(INDIA_TODO_NOUNS, [
    "electricity receipt", "bank statement", "school notebook set", "festival travel plan", "bike repair token", "doctor prescription",
    "Aadhaar copy", "rent agreement", "gas subsidy form", "medical reimbursement", "parking sticker", "internet complaint",
    "loan closure", "train booking", "tailor pickup", "insurance paper", "hostel payment", "milk account slip",
])
_extend_unique(GLOBAL_TODO_NOUNS, [
    "utility receipt", "tenant key", "parking sticker", "museum invoice", "passport renewal", "locker code",
    "garden permit", "boiler invoice", "mail pickup", "storage key",
])

# Todo expansion pass focused specifically on parse_query/todo uniqueness.
_TODO_VERBS_EXTRA_INDIA = [
    "follow up on", "remind", "clear", "settle", "close", "recheck", "prepare", "arrange", "confirm", "download",
    "upload", "forward", "share", "message", "meet", "compare", "renew online", "visit office for", "ask about", "resolve",
    "track", "collect from", "submit online", "call back about", "verify", "complete", "review", "register for", "apply for", "finish",
]
_TODO_OBJECTS_INDIA_EXTRA = [
    "Aadhaar correction", "PAN card linking", "voter ID copy", "ration card issue", "driving licence renewal", "FASTag statement",
    "metro pass recharge", "bus pass renewal", "gas subsidy complaint", "bank nominee update", "post office KYC", "loan closure letter",
    "medical reimbursement form", "hospital bill copy", "pharmacy refill", "blood report", "school fee receipt", "college bonafide",
    "hostel payment slip", "tuition fee transfer", "property document xerox", "rent agreement scan", "maintenance receipt",
    "electricity complaint", "water tanker booking", "RO service booking", "inverter battery check", "UPS AMC", "scooter insurance",
    "bike pollution certificate", "car service estimate", "helmet visor replacement", "tailor blouse pickup", "spectacle pickup",
    "courier tracking", "parcel complaint", "milk card renewal", "newspaper bill", "maid bonus", "festival train booking",
    "temple hall booking", "wedding hall advance", "travel reimbursement", "office ID reissue", "salary slip copy",
    "passport appointment", "visa photo print", "document binding", "hall ticket print", "lab manual submission",
    "school van fee", "creche fee", "doctor follow-up", "x-ray collection", "scan review", "gas stove repair",
    "plumber visit", "electrician visit", "pest control booking", "water motor repair", "ceiling fan repair", "Wi-Fi complaint",
]
_extend_unique(INDIA_TODOS, [f"{v} {o}" for v in _TODO_VERBS_EXTRA_INDIA for o in _TODO_OBJECTS_INDIA_EXTRA])

_TODO_NOUN_PREFIXES_INDIA = [
    "pending", "urgent", "family", "office", "bank", "school", "travel", "medical", "bike", "house",
    "festival", "hostel", "property", "document", "service",
]
_TODO_NOUNS_EXTRA_INDIA = [
    "Aadhaar update", "PAN correction", "passport appointment", "loan document", "rent receipt", "gas subsidy follow-up",
    "electricity complaint", "water tax proof", "parking permit", "school van fee", "college fee slip", "medical insurance claim",
    "bike insurance", "scooter pollution certificate", "Wi-Fi complaint", "RO service", "inverter AMC", "maintenance receipt",
    "temple hall token", "festival booking", "tailor pickup", "spectacle order", "courier proof", "parcel issue",
    "pharmacy refill", "doctor report", "blood report", "x-ray copy", "exam fee slip", "hall ticket",
    "property paper", "tenant form", "passport xerox", "bank nominee", "FASTag topup", "metro card recharge",
]
_extend_unique(INDIA_TODO_NOUNS, [f"{p} {n}" for p in _TODO_NOUN_PREFIXES_INDIA for n in _TODO_NOUNS_EXTRA_INDIA])

_TODO_VERBS_EXTRA_GLOBAL = [
    "follow up on", "remind", "close", "resolve", "confirm", "download", "upload", "forward", "share", "meet",
    "prepare", "arrange", "review", "register for", "apply for", "track", "verify", "complete", "call back about", "compare",
]
_TODO_OBJECTS_GLOBAL_EXTRA = [
    "renters insurance", "passport appointment", "parking appeal", "utility statement", "internet outage", "HVAC service",
    "building permit", "storage invoice", "mailroom package", "laundry card", "bike registration", "boiler estimate",
    "transit card", "garden waste pickup", "school lunch account", "dental invoice", "library renewal", "tenant portal issue",
    "lease document", "roof repair quote", "snow tire swap", "museum reservation", "gallery RSVP", "ferry booking",
    "studio key", "appliance repair", "locker access", "daycare form", "heating oil booking", "parking sticker",
    "mail forwarding", "package return", "recycling pass", "maintenance request", "water bill copy", "insurance proof",
]
_extend_unique(GLOBAL_TODOS, [f"{v} {o}" for v in _TODO_VERBS_EXTRA_GLOBAL for o in _TODO_OBJECTS_GLOBAL_EXTRA])

_TODO_NOUN_PREFIXES_GLOBAL = ["pending", "urgent", "house", "travel", "medical", "school", "building", "tenant", "bike", "office"]
_TODO_NOUNS_EXTRA_GLOBAL = [
    "passport renewal", "parking permit", "utility invoice", "tenant form", "mailroom package", "storage access",
    "boiler service", "heating bill", "transit pass", "bike registration", "garden permit", "locker key",
    "museum pass", "ferry booking", "roof repair", "insurance proof", "appliance estimate", "school lunch account",
]
_extend_unique(GLOBAL_TODO_NOUNS, [f"{p} {n}" for p in _TODO_NOUN_PREFIXES_GLOBAL for n in _TODO_NOUNS_EXTRA_GLOBAL])

_INDIA_LEDGER_CONTEXTS = [
    "canteen lunch", "cab split", "fuel share", "grocery basket", "mess bill", "trip advance", "wedding expense",
    "movie snacks", "ticket booking", "mobile recharge", "tea powder", "fruit purchase", "water can", "breakfast parcel",
    "hostel rent", "security advance", "tailor balance", "medicine bill", "school supplies", "pooja flowers", "parking fee",
]
_INDIA_LEDGER_SUFFIXES = ["share", "split", "advance", "bill", "amount", "payment", "balance"]
_extend_unique(INDIA_LEDGER_REASONS, [f"{c} {s}" for c in _INDIA_LEDGER_CONTEXTS for s in _INDIA_LEDGER_SUFFIXES])

_GLOBAL_LEDGER_CONTEXTS = [
    "brunch", "museum tickets", "parking garage", "hostel groceries", "locker deposit", "bike repair", "coffee run",
    "train fare", "laundry card", "studio supplies", "movie pass", "food market", "travel snacks", "printing",
]
_extend_unique(GLOBAL_LEDGER_REASONS, [f"{c} split" for c in _GLOBAL_LEDGER_CONTEXTS] + [f"{c} advance" for c in _GLOBAL_LEDGER_CONTEXTS])

_MORE_DATE_LABELS = [
    ("tmrw", "2026-05-06"), ("tdy", "2026-05-05"), ("yday", "2026-05-04"), ("last wk", "2026-04-27"),
    ("this wk", "2026-05-04"), ("current wk", "2026-05-04"), ("1 may", "2026-05-01"), ("9 may", "2026-05-09"),
    ("morn", "2026-05-05"), ("eve", "2026-05-05"), ("night", "2026-05-05"), ("wknd", "2026-05-09"),
]
_extend_unique(SINGLE_DATE_OPTIONS, _MORE_DATE_LABELS)

RANGE_OPTIONS.update({
    "this wk": ("2026-05-04", "2026-05-10"),
    "last wk": ("2026-04-27", "2026-05-03"),
    "current wk": ("2026-05-04", "2026-05-10"),
    "past week": ("2026-04-29", "2026-05-05"),
    "past fortnight": ("2026-04-22", "2026-05-05"),
    "current quarter": ("2026-04-01", "2026-06-30"),
    "current financial year": ("2026-04-01", "2027-03-31"),
    "april month": ("2026-04-01", "2026-04-30"),
    "may month": ("2026-05-01", "2026-05-31"),
    "january month": ("2026-01-01", "2026-01-31"),
    "till today": ("2026-05-01", "2026-05-05"),
    "month end": ("2026-05-25", "2026-05-31"),
})

# Tanglish / Tamil-in-English expansion for India-first usage.

_TANGLISH_GROCERIES = [
    "kothamalli", "puthina", "karuvepilai", "kadugu", "jeeragam", "sombu", "milagu", "manjal podi",
    "milagai podi", "sambar podi", "rasam podi", "perungayam", "vendhayam", "ulutham paruppu",
    "thuvaram paruppu", "paasi paruppu", "kadalai maavu", "arisi maavu", "ravai", "aval",
    "thengai", "vellam", "inji", "poondu", "murungakkai", "vengayam", "thakkali", "pachai milagai",
    "malli thool", "garam masala packet", "idli maavu", "dosa maavu", "curd milagai", "vadagam",
    "appalam", "pickle bottle", "nei", "nallennai", "groundnut mittai", "mixture packet",
    "murukku", "rusk packet", "tea dust", "filter kaapi powder", "ponni arisi", "seeraga samba arisi",
    "basmati arisi", "maida maavu", "atta maavu", "corn flour", "beetroot", "beans", "vendakkai",
    "pudalangai", "suraikkai", "kathirikai", "chow chow", "poosanikkai", "kovakkai", "malli ilai", "pudhina ilai",
]
_extend_unique(INDIA_EXPENSE["groceries"], _TANGLISH_GROCERIES)
_extend_unique(INDIA_BUY, _TANGLISH_GROCERIES)

# 2026-05-09: pure-Tanglish buy items observed in user dogfood logs that have
# no clean English equivalent. Adding them so the next fine-tune sees these
# exact items in INDIA_BUY → model learns to keep them as item_text without
# attempting to translate or split them. User confirmed they will keep using
# Tanglish for buy in this lifetime.
_TANGLISH_BUY_ONLY = [
    # turmeric / spice variants
    "Manjal",                 # bare turmeric (root or ground, no `podi`)
    "kasthuri methi",         # dried fenugreek leaves (kasuri methi)
    "kasthuri manjal",        # wild turmeric (cosmetic use)
    "Gaza gasa",              # poppy seeds (kasakasa / khus khus)
    "vetrilai",               # betel leaves
    "paaku",                  # areca nut
    "elakkai",                # cardamom
    "lavangam",               # cloves
    "pattai",                 # cinnamon
    "annasi pazham",          # pineapple
    "mavuli pazham",          # ripe banana
    "kothamalli verai",       # coriander root
    "inji garlic paste",
    "karupatti",              # palm jaggery
    "panangkalkandu",         # palm sugar candy
    # clothing items (Tanglish + brand mixes)
    "killer nighty",          # nightgown (Killer is the brand)
    "kili pachai saree",      # parrot-green saree
    "rama nighty",            # red nightgown
    "cotton nighty",
    "rayon kurta",
    "silk saree",
    "nylon saree",
    "salwar set",
    "veshti",                 # men's traditional wrap
    "thundu",                 # men's shoulder cloth
    "pavadai",                # girls' skirt
    "jadai ribbon",           # hair ribbon
    "thali kayiru",           # mangalsutra thread
    # kitchenware Tanglish
    "kal urai",               # mortar
    "ammi",                   # grinding stone
    "thosai kal",             # dosa pan
    "kuzhambu satti",         # curry pot
    "panniyaram chatti",      # paniyaram pan
    "ulakkai",                # pestle
    "kuduvai",                # pot
    # snacks / sweets Tanglish
    "muruku",
    "thattai",
    "sevai",
    "mysorepak",
    "athirasam",
    "boondhi laddu",
    "ribbon pakoda",
    "thenkuzhal",
    "mixture",
    "milk peda",
    "halwa packet",
    # daily-use / personal Tanglish
    "vasanai soap",           # fragrant soap
    "kungumam",               # vermillion
    "sandhanam",              # sandalwood paste
    "vibhuti packet",         # holy ash
    "agarbathi pack",
    "sambrani cup",
    # bare quantity-style entries the user types
    "uluntha parupu",         # alternate spelling of ulutham paruppu
    "thuvam paruppu",         # alternate spelling of thuvaram paruppu
    "paasi parupu",           # alternate spelling of paasi paruppu
]
_extend_unique(INDIA_BUY, _TANGLISH_BUY_ONLY)

# 2026-05-09 (later): second Tanglish round — gap analysis showed buy lane
# Tanglish noun coverage was thin beyond groceries. Adding ~100 more items
# across categories users actually buy (vegetables, dals, snacks, dairy,
# meat/fish, ready-mixes). Each item is real Tamil-script-in-English-letters
# vocabulary the user might type without translation.
_TANGLISH_BUY_PHASE2 = [
    # Vegetables (deeper)
    "chinna vengayam", "periya vengayam", "veluthulli", "elumichai",
    "kothavarai", "vazhakkai", "vazhaipoo", "vazhaithandu", "kovakkai",
    "manathakkali", "agathi keerai", "siru keerai", "mulaikeerai",
    "pasalai keerai", "araikeerai", "ponnanganni keerai", "kalyana murungai",
    "kothamalli verai", "kothamalli kattu",
    "naatu thakkali", "country tomato", "ooty potato", "karunai kizhangu",
    "chenai kizhangu", "chembu", "yam kizhangu",
    # Pulses/grains (deeper)
    "kollu", "ragi", "varagu", "samai", "thinai", "kuthiravali",
    "panivaragu", "kambu", "cholam", "kambu maavu", "ragi maavu",
    "kambu cholam mix", "thuvaram dal", "kollu maavu",
    # Snacks
    "muthusaaram", "kara sev", "ribbon pakoda", "thattai", "masal vadai",
    "ulundha vadai", "medhu vadai", "paruppu vadai", "boli", "adhirasam",
    "manoharam", "halwa", "kovai halwa", "thirunelveli halwa",
    "mysorepak", "bombay halwa", "cake rusk", "mixture pack",
    "coconut burfi", "kalkandu", "thaen kuzhal",
    # Dairy
    "thayir", "moru", "ghee dabba", "venna", "vellai venna",
    "panneer", "neyu", "more milagai",
    # Meat/fish (Tanglish)
    "kozhi", "naatu kozhi", "broiler kozhi", "aatu kari", "pannri kari",
    "meen", "vanjiram meen", "saala meen", "nethili meen", "viral meen",
    "nandu", "eral", "kanavai", "kalmeen",
    # Ready-mix / instant
    "rasam mix", "sambar mix", "idli mix", "dosa mix",
    "vatha kuzhambu mix", "puli kuzhambu mix", "pongal mix",
    "payasam mix", "paal kova", "kheer mix",
    # Festival items
    "manjal kayiru", "thoranam", "mukkanai mavu", "kolam podi",
    "vibhuti pottu", "chandanam pottu", "kungumam pottu",
    "deepam ennai", "deepam wick", "samikku flowers",
    # Common everyday items
    "soda salt", "kal uppu", "podi uppu", "indu uppu",   # different salt types
    "puli", "naatu puli", "vellam", "panai vellam",
    "thirumathi rice", "ponni boiled", "ponni raw",
]
_extend_unique(INDIA_BUY, _TANGLISH_BUY_PHASE2)

# 2026-05-09: brand-product compounds. Real Indian buy lists carry
# brand+product naming (`Amul ghee`, `MTR sambar mix`, `Sakthi rasam podi`)
# which the model has thin training coverage on. Items have NO size/quantity
# baked in (quantity_piece_for_item adds those separately) — just brand +
# product so they compose naturally with existing quantity logic.
_BRAND_PRODUCT_COMPOUNDS = [
    # Dairy
    "Amul ghee", "Amul butter", "Amul curd", "Amul cheese slice",
    "Amul masala buttermilk", "Aavin ghee", "Aavin curd", "Aavin milk",
    "Nandini ghee", "Nandini curd", "Nandini milk", "Nandini paneer",
    "Mother Dairy ghee", "Mother Dairy paneer", "Mother Dairy yogurt",
    "Heritage curd", "Heritage milk", "Heritage paneer",
    "Britannia cheese cubes", "Britannia paneer", "Country Delight ghee",
    # Spice / podi brands
    "Aachi sambar podi", "Aachi rasam podi", "Aachi chicken masala",
    "Aachi biryani masala", "Aachi vatha kuzhambu podi",
    "Sakthi sambar podi", "Sakthi rasam podi", "Sakthi chicken masala",
    "Sakthi turmeric powder", "Sakthi chilli powder",
    "MTR sambar mix", "MTR rasam mix", "MTR rava idli mix", "MTR dosa mix",
    "MTR bisi bele bath powder", "MTR pongal mix",
    "Eastern sambar powder", "Eastern rasam powder", "Eastern garam masala",
    "Eastern chicken masala", "Eastern fish masala",
    "Suhana garam masala", "Catch chaat masala", "Catch dhaniya powder",
    "MDH chunky chat masala", "MDH garam masala", "Everest chicken masala",
    "Everest garam masala", "Everest tandoori masala",
    "Ramdev kashmiri mirch", "Ramdev chana masala",
    # Oils
    "Idhayam gingelly oil", "Postman oil", "Nutralite spread",
    "Saffola oil", "Saffola gold", "Fortune sunflower oil",
    "Fortune mustard oil", "Sundrop oil", "Dabur badam oil",
    "Parachute coconut oil", "Coconut oil tin",
    # Atta / flour
    "Aashirvaad atta", "Aashirvaad multigrain atta", "Pillsbury atta",
    "Ananda atta", "Patanjali atta", "Anand chakki atta",
    "24 Mantra atta", "Daawat besan", "Tata Sampann besan",
    # Rice
    "India Gate basmati", "Daawat basmati", "Fortune basmati rice",
    "Lal Qilla basmati", "Sungold rice", "Ponni rice",
    "Sona masoori rice", "1121 basmati", "1509 basmati",
    # Dal
    "Tata Sampann toor dal", "Tata Sampann moong dal", "Tata Sampann chana dal",
    "Patanjali toor dal", "24 Mantra toor dal", "Organic Tattva moong dal",
    "Tata Sampann urad dal", "Patanjali masoor dal",
    # Snacks
    "Lays magic masala", "Lays american style", "Kurkure masala munch",
    "Haldiram bhujia", "Haldiram aloo bhujia", "Haldiram namkeen",
    "Bikano bhujia", "Britannia good day", "Britannia marie gold",
    "Britannia bourbon", "Britannia 50-50", "Parle G", "Parle hide and seek",
    "Parle Monaco", "Sunfeast dark fantasy", "Sunfeast bounce",
    "Cadbury dairy milk", "Cadbury silk", "Cadbury 5 star",
    "Nestle kitkat", "Nestle munch", "Nestle bar one",
    # Beverages
    "Boost", "Bournvita", "Horlicks", "Complan", "Pediasure",
    "Tata Tea premium", "Tata Tea gold", "Brooke Bond red label",
    "Brooke Bond taj mahal", "Tata coffee", "Bru gold coffee",
    "Bru instant coffee", "Nescafe classic", "Nescafe sunrise",
    # Soaps / personal
    "Mysore Sandal soap", "Mysore Sandal shampoo",
    "Cinthol soap", "Cinthol confidence", "Cinthol cologne",
    "Liril soap", "Pears soap", "Pears facewash",
    "Dove soap", "Dove shampoo", "Dove conditioner",
    "Lux soap", "Hamam soap", "Margo neem soap",
    "Medimix soap", "Medimix hair oil", "Medimix hand wash",
    "Patanjali soap", "Patanjali shampoo", "Patanjali kesh kanti",
    "Himalaya face wash", "Himalaya neem face pack",
    # Detergents
    "Surf Excel matic", "Surf Excel quick wash",
    "Tide plus", "Tide bar", "Ariel matic",
    "Henko stain champion", "Rin bar", "Wheel powder",
    "Nirma washing powder", "Ezee liquid",
    # Household / cleaning
    "Vim dishwash gel", "Vim bar", "Pril dish wash",
    "Colin glass cleaner", "Lizol floor cleaner",
    "Harpic toilet cleaner", "Phenol bottle",
    "Odonil air freshener", "Hit insect spray",
    "All Out refill", "Good Knight refill", "Mortein liquid",
    # Toothpaste
    "Colgate strong teeth", "Colgate maxfresh", "Colgate vedshakti",
    "Pepsodent germi check", "Pepsodent salt power",
    "Sensodyne fresh mint", "Closeup red", "Meswak toothpaste",
    "Anchor white toothpaste", "Patanjali dant kanti",
    "Dabur red toothpaste",
    # Baby
    "Pampers premium care", "Mamy Poko pants",
    "Cerelac wheat apple", "Lactogen 1", "Nestle Nan Pro",
    # Others
    "Maggi noodles", "Yippee noodles", "Top Ramen",
    "Knorr soup", "MTR ready meal", "iD batter",
    "iD malabar paratha", "Mom's magic instant food",
]
_extend_unique(INDIA_BUY, _BRAND_PRODUCT_COMPOUNDS)
# Brand-product compounds also belong in expense groceries (people log
# them as expenses too, not just buy lists).
_extend_unique(INDIA_EXPENSE["groceries"], _BRAND_PRODUCT_COMPOUNDS[:80])  # dairy + spice + oil + atta + rice + dal
_extend_unique(INDIA_EXPENSE["personal_care"], _BRAND_PRODUCT_COMPOUNDS[120:160])  # soaps section
_extend_unique(INDIA_EXPENSE["household"], _BRAND_PRODUCT_COMPOUNDS[160:180])  # detergents + cleaning

_TANGLISH_HOUSEHOLD = [
    "paai", "clip", "vessel scrub", "detergent powder", "bucket mug", "door mat",
    "ennai", "agarbathi packet", "sambrani", "match box", "mosquito bat", "mosquito coil",
    "phenyl", "harpic", "vim bar", "soap", "stand", "dustbin cover",
    "floor mop", "thodappam", "basket", "sombu", "plate set", "gas lighter",
]
_extend_unique(INDIA_EXPENSE["household"], _TANGLISH_HOUSEHOLD)
_extend_unique(INDIA_BUY, _TANGLISH_HOUSEHOLD)

_TANGLISH_PERSONAL = [
    "parachute", "clinic plus shampoo", "lux soap", "dove soap", "face wash", "powder box",
    "comb", "hair clip", "shaving razor", "sanitary pad", "hand wash refill", "toothpaste",
    "body lotion", "sunscreen", "beard trimmer blade", "lip balm", "nail cutter",
]
_extend_unique(INDIA_EXPENSE["personal_care"], _TANGLISH_PERSONAL)
_extend_unique(INDIA_BUY, _TANGLISH_PERSONAL)

# v2 cleanup: _TANGLISH_TRANSPORT / _TANGLISH_DINING / _TANGLISH_VEHICLE removed.
# Their entries were almost all "<English noun> kasu", which no real Tanglish
# user writes. Stripping "kasu" left only English; the underlying English items
# already exist in INDIA_EXPENSE["transport"] / ["dining"] / ["vehicle"].

_TANGLISH_NOTES = [
    "EB bill katanum note", "hostel ku poganum note", "amma medicine vanganum", "kothamalli rate note",
    "veetu saaman list", "mixer jar repair note", "water can booking note", "tailor kitte poi vanganum",
    "gas booking panna reminder", "passport xerox edukanum", "bike service panna note", "milk account balance note",
    "rent receipt anupanum", "property tax katanum", "school fees katanum", "wifi complaint pannanum",
    "RO service panna note", "inverter battery pakanum", "temple ku poganum note", "festival shopping pannanum",
]
_extend_unique(INDIA_NOTE_TOPICS, _TANGLISH_NOTES)

_TANGLISH_TODOS = [
    "EB bill katanum", "hostel ku poganum", "amma ku medicine vanganum", "gas booking pannanum",
    "passport xerox edukanum", "bike service pannanum", "tailor kitte poi vanganum", "rent receipt anupanum",
    "school fees katanum", "property tax katanum", "milk account settle pannanum", "wifi complaint pannanum",
    "RO service book pannanum", "inverter battery check pannanum", "parcel collect pannanum", "Aadhaar xerox scan pannanum",
    "PAN copy upload pannanum", "metro card recharge pannanum", "FASTag topup pannanum", "gas subsidy check pannanum",
    "exam hall ticket print pannanum", "hostel fees katanum", "newspaper kasu kudukanum", "maid salary kudukanum",
    "spectacles collect pannanum", "bank ku poganum", "tailor balance kudukanum", "temple hall book pannanum",
    "doctor follow-up ku poganum", "lab report collect pannanum", "water can order pannanum", "plumber ah koopudnum",
    "electrician ah koopudnum", "driving licence renew pannanum", "train ticket book pannanum", "Aadhaar update pannanum",
    "school office ku poganum", "college form submit pannanum", "hostel reimbursement anupanum", "UPI screenshot anupanum",
    "bike insurance renew pannanum", "scooter pollution certificate edukanum", "temple ku pooganum", "festival ku vessels vanganum",
    "parcel return pannanum", "medical claim submit pannanum", "gas stove service book pannanum", "milk vendor ku kasu kudukanum",
]
_extend_unique(INDIA_TODOS, _TANGLISH_TODOS)

_TANGLISH_TODO_NOUNS = [
    "EB bill", "hostel fees", "passport xerox", "gas booking", "rent receipt", "milk account", "property tax",
    "school fees", "tailor balance", "bike service", "Aadhaar update", "PAN copy", "Wi-Fi complaint", "RO service",
    "inverter battery", "metro recharge", "FASTag topup", "exam hall ticket", "lab report", "doctor follow-up",
    "maid salary", "newspaper kasu", "water can booking", "spectacles order", "parcel collection", "temple hall booking",
]
_extend_unique(INDIA_TODO_NOUNS, _TANGLISH_TODO_NOUNS)
_extend_unique(INDIA_TODO_NOUNS, [f"pending {x}" for x in _TANGLISH_TODO_NOUNS])
_extend_unique(INDIA_TODO_NOUNS, [f"urgent {x}" for x in _TANGLISH_TODO_NOUNS])
_extend_unique(INDIA_TODO_NOUNS, [f"family {x}" for x in _TANGLISH_TODO_NOUNS])

# v2 cleanup: _TANGLISH_LEDGER removed for the same reason as the other "kasu"
# pools above. Also: the v2 generator does not import INDIA_LEDGER_REASONS at
# all (ledger writes emit `note: null`), so this list had no live consumers.

_TANGLISH_SINGLE_DATES = [
    ("iniku", "2026-05-05"),
    ("nethu", "2026-05-04"),
    ("naliku", "2026-05-06"),
    ("kalila", "2026-05-05"),
    ("sayangalam", "2026-05-05"),
    ("pona sunday", "2026-05-03"),
    ("pona friday", "2026-05-01"),
    ("intha friday", "2026-05-08"),
    ("intha sunday", "2026-05-10"),
    ("vara monday", "2026-05-11"),
    ("vara wednesday", "2026-05-06"),
]
_extend_unique(SINGLE_DATE_OPTIONS, _TANGLISH_SINGLE_DATES)

RANGE_OPTIONS.update({
    "indha masam": ("2026-05-01", "2026-05-31"),
    "pona masam": ("2026-04-01", "2026-04-30"),
    "indha varam": ("2026-05-04", "2026-05-10"),
    "pona varam": ("2026-04-27", "2026-05-03"),
    "iniku": ("2026-05-05", "2026-05-05"),
    "nethu": ("2026-05-04", "2026-05-04"),
    "naliku": ("2026-05-06", "2026-05-06"),
    "indha varusam": ("2026-05-01", "2027-04-30"),
    "pona varusam": ("2024-05-01", "2025-04-30")
})

# v2: keys that the v2 generator must filter OUT of query date pools.
# These remain available for todo-write Pattern B usage only.
TANGLISH_SINGLE_DATE_KEYS = {
    "iniku", "nethu", "naliku",
    "kalila", "sayangalam",
    "pona sunday", "pona friday",
    "intha friday", "intha sunday",
    "vara monday", "vara wednesday",
}
TANGLISH_RANGE_KEYS = {
    "indha masam",  "pona masam",
    "indha varam", "pona varam",
    "iniku", "nethu", "naliku",
    "indha varusam","pona varusam"
}


# ---------------------------------------------------------------------------
# Phase 3 expansion (v2 review session) — roughly doubles the major pools
# with curated, real, India-/global-relevant additions. All extends route
# through `_extend_unique` so accidental duplicates with the earlier blocks
# above are dropped silently.
# ---------------------------------------------------------------------------

# --- INDIA_NAMES (target: ~462 -> ~660) ---
_PH3_INDIA_NAMES_NEW = [
    "Aanandhi", "Aathmika", "Adwitha", "Aishwarya", "Alagumeena", "Alagappan", "Amirthavalli",
    "Anirudhan", "Annapoorani", "Aparna", "Apoorva", "Arumugam", "Aswath", "Athithi", "Avantika",
    "Bharathi", "Bhavadharini", "Bhavya", "Brindha", "Buvaneshwari", "Chirantan", "Chitralekha",
    "Devasena", "Devyani", "Dhanalakshmi", "Dhanya", "Dharshini", "Dharmaraj", "Dhayalan",
    "Dhinesh", "Dhivya", "Dhruv", "Dhyana", "Eashwar", "Ezhilmaran", "Geetha", "Gowtham",
    "Gurusamy", "Haripriya", "Harshitha", "Hemamalini", "Hemanth", "Hridaya", "Inbavalli",
    "Indhirajith", "Iniyavan", "Iqbal", "Ishita", "Ishwar", "Jagatheeshwari", "Jaichand",
    "Jaisree", "Janani", "Janardhan", "Jaya", "Jayachitra", "Jayaganesh", "Jayaraj", "Jeevitha",
    "Jegath", "Jenisha", "Jhanvi", "Jothilakshmi", "Kaliappan", "Kalpana", "Kamala", "Kamaraj",
    "Kamatchi", "Kannan", "Kannappan", "Karunakaran", "Kasthuri", "Kavya", "Keerthi", "Kishan",
    "Krithika", "Kumari", "Kuppammal", "Lakshmanan", "Lavanya", "Madhumitha", "Mahalingam",
    "Mahija", "Maithreyi", "Manimegalai", "Manjula", "Maragatham", "Mariamma", "Marudhachalam",
    "Mathangi", "Mayilsamy", "Meenakshi", "Meghana", "Murali", "Muthamil", "Muthazhagi",
    "Naachiyaar", "Nachimuthu", "Nagamani", "Nagarathinam", "Nakshatra", "Nallamani",
    "Nallathambi", "Nandagopal", "Nandhakumar", "Narayanan", "Navinkumar", "Nirupa", "Nithya",
    "Niveditha", "Padmavathi", "Palanichamy", "Palanisamy", "Palanivel", "Pankajam", "Parvathi",
    "Pavithran", "Pazhaniammal", "Periyasamy", "Perumal", "Ponmani", "Poongodi", "Poorani",
    "Pournami", "Prabakaran", "Pradeepa", "Pragathi", "Pranesh", "Prashanthi", "Prema",
    "Premkumar", "Pushpa", "Raghavan", "Raghu", "Rajagopal", "Rajalingam", "Rajamani",
    "Rajaraman", "Rajaratnam", "Rajendran", "Rajeswaran", "Rajeswari", "Rakesh", "Ramamoorthy",
    "Raman", "Ramanan", "Ramani", "Ramprasath", "Ranganathan", "Ranjitha", "Ravichandran",
    "Renuka", "Revanth", "Sadhasivam", "Sahasra", "Sakshi", "Sambasivam", "Sangavi", "Sarayu",
    "Saroja", "Sashikumar", "Sathiyaraj", "Sathyamoorthy", "Sathyapriya", "Sekar",
    "Selvanayaki", "Selvaraj", "Senthamarai", "Sevanthi", "Shanmuga", "Shanthi", "Sharanya",
    "Sharath", "Shashank", "Shekar", "Shenbagam", "Shilpa", "Shivani", "Shobana", "Shradha",
    "Shreya", "Shyamala", "Sivakami", "Sivakumar", "Sivapriya", "Sivaramakrishnan",
    "Sivasankaran", "Soundarya", "Sreedevi", "Srinivasan", "Subbiah", "Subramani",
    "Subramanian", "Sudarshan", "Sudhakar", "Sukanya", "Sumathi", "Sundaram", "Sundari",
    "Suriya", "Susheela", "Swathi", "Tamilarasi", "Tamilarasu", "Tamilselvan", "Thamarai",
    "Thamilini", "Thangamani", "Thangapandian", "Thangaraju", "Thangavel", "Thanikai",
    "Tharani", "Tharanidhi", "Thavamani", "Thirumalai", "Thirumavalavan", "Thiyagu",
    "Tholkappian", "Vairamuthu", "Vaishali", "Valarmathi", "Vanaja", "Vasagan", "Vasantha",
    "Vasudevan", "Vembu", "Venkata", "Venkatesan", "Venkateswaran", "Vetriarasan", "Vidya",
    "Vijay", "Vijayalakshmi", "Vijayan", "Vinayagam", "Vivek", "Yamini", "Yuvasri",
    # Kinship / household forms users often write in casual notes
    "kanavar", "manaivi", "kozhandai", "thaaipathi", "veetukkari", "athimber", "anni",
    "marumakan", "kuzhandai", "thangai", "machinan", "machaan", "machini", "kaakai",
    "chithappa veetu kuzhandai", "amma veetu thatha", "appa veetu paati",
]
_extend_unique(INDIA_NAMES, _PH3_INDIA_NAMES_NEW)


# --- GLOBAL_NAMES (target: ~170 -> ~320) ---
_PH3_GLOBAL_NAMES_NEW = [
    "Adelaide", "Adriana", "Aiden", "Alessandro", "Aleksandra", "Alexei", "Aliyah", "Alma",
    "Amir", "Amos", "Anaya", "Anders", "Andreas", "Angelo", "Annabel", "Antoine", "Aria",
    "Arden", "Arie", "Aurora", "Axel", "Bartholomew", "Beatrice", "Bellamy", "Bennett",
    "Bram", "Briar", "Brielle", "Brigitte", "Calliope", "Camden", "Carmen", "Caspian",
    "Catalina", "Cecilia", "Celeste", "Chiara", "Cillian", "Clara", "Cleo", "Clemence",
    "Cyrus", "Dalia", "Darcy", "Davina", "Dax", "Dean", "Demetra", "Desmond", "Dimitri",
    "Dorian", "Dylan", "Eliana", "Eliza", "Emery", "Emilio", "Emir", "Enzo", "Esme",
    "Estelle", "Evangeline", "Everett", "Ezra", "Fabian", "Fenella", "Florence", "Floyd",
    "Francesca", "Frederick", "Garrett", "Genevieve", "Giada", "Gianna", "Giselle",
    "Gracelyn", "Greta", "Grayson", "Halima", "Hamish", "Hannelore", "Heath", "Henrik",
    "Hilde", "Holland", "Idris", "Ilya", "Imani", "Inara", "Indira", "Ines", "Iona", "Iris",
    "Isaiah", "Isolde", "Ivor", "Jamal", "Jasmine", "Jeremiah", "Joanna", "Joaquin",
    "Jocelyn", "Joelle", "Joseph", "Josephine", "Josiah", "Jovan", "Juniper", "Justus",
    "Kalindi", "Karis", "Karol", "Katarina", "Kelsey", "Kenji", "Kerensa", "Kian", "Klara",
    "Lachlan", "Lakshya", "Lara", "Layla", "Leandro", "Leila", "Leo", "Leonid", "Lila",
    "Linnea", "Liora", "Logan", "Lorelei", "Lorenzo", "Luella", "Lukas", "Lyra", "Mads",
    "Magdalena", "Malachi", "Marcellus", "Margaux", "Marguerite", "Marianne", "Marisol",
    "Marlowe", "Mathilde", "Matthias", "Maya", "Maximilian", "Mei", "Mercy", "Micah",
    "Mikael", "Milena", "Mira", "Mireille", "Mirabel", "Mirela", "Misha", "Moira",
    "Murdoch", "Nathaniel", "Nellie", "Nessa", "Nikita", "Nima", "Niko", "Nora", "Octavia",
    "Odessa", "Olek", "Oona", "Orla", "Oskar", "Otto", "Pablo", "Petra", "Philomena",
    "Quinn", "Ramon", "Raphael", "Ravenna", "Rebecca", "Reuben", "Roan", "Romilly",
    "Roosevelt", "Rosa", "Rumi", "Saoirse", "Sebastien", "Selene", "Senna", "Seraphine",
    "Severin", "Shay", "Sigrid", "Simone", "Solomon", "Sonia", "Soraya", "Sven", "Tadeo",
    "Tamsin", "Tariq", "Tatum", "Theodora", "Thiago", "Thora", "Tiana", "Toby", "Tomas",
    "Tristan", "Ulrik", "Valentina", "Vesper", "Wilhelmina", "Xander", "Yael", "Yann",
    "Yusuf", "Zephyr", "Zola",
]
_extend_unique(GLOBAL_NAMES, _PH3_GLOBAL_NAMES_NEW)


# --- INDIA_NOTE_TOPICS (target: ~385 -> ~585) ---
_PH3_INDIA_NOTE_TOPICS_NEW = [
    "chimney service note", "lift maintenance dues", "society watchman holiday",
    "iron box repair", "blender warranty card", "kettle whistle issue", "rice shed cover",
    "drying line repair", "geyser thermostat", "shoe rack glue", "ATM card pin reset",
    "PF balance check", "EPF UAN reminder", "passport address change", "voter list correction",
    "ration card add member", "police clearance check", "RTO appointment", "license endorsement",
    "vehicle ownership transfer", "gas connection transfer", "hospital follow-up note",
    "vaccination batch number", "diet log day 1", "morning walk distance", "BP tablet schedule",
    "yoga class fee", "cycling group route", "carpool schedule", "trip itinerary day 2",
    "Rameshwaram travel route", "Madurai temple darshan", "Kanchipuram silk sari order",
    "festival calendar TN", "Pongal market list", "Diwali sweets order", "Aadi sale shortlist",
    "Kartigai deepam plan", "school vibhuti packet", "puja items list", "wedding invitation track",
    "wedding catering quote", "wedding photographer slot", "marriage hall checklist",
    "engagement guest list", "vegetable vendor weekly", "exam reminder day 1",
    "scholarship form draft", "scholarship deadline", "research paper draft",
    "thesis correction", "internship application", "campus placement", "hostel Wi-Fi outage",
    "PG room rent receipt", "PG broker contact", "rental agreement renewal",
    "house warming list", "house rent advance", "bike pollution date", "scooter petrol log",
    "monthly fuel average", "EMI auto debit reminder", "credit card statement check",
    "cashback claim", "GPay refund", "PhonePe failed payment", "UPI handle update",
    "bank locker payment", "fixed deposit auto renewal", "PPF top-up", "tax filing draft",
    "ITR acknowledgment", "TDS certificate", "section 80C list", "investment journal",
    "sip review", "stock watchlist", "mutual fund kyc", "NSC redemption",
    "post office RD", "school anniversary", "annual day costume", "sports day list",
    "PTA meeting note", "exam schedule day 1", "diary stickers list", "bookmark design",
    "uniform stitching", "shoe size update", "kid haircut reminder", "kid medical history",
    "child vaccination next due", "creche payment", "baby formula switch",
    "diaper brand compare", "naming ceremony list", "cradle ceremony list",
    "ear piercing slot", "first birthday plan", "first feast plan", "amma medicine list",
    "appa hospital prep", "father annual checkup", "mother insurance renewal",
    "grandfather death anniversary", "death certificate copy", "succession certificate draft",
    "old documents review", "family album sort", "old phone backup",
    "WhatsApp media cleanup", "google photos archive", "drive cleanup", "sim recharge auto",
    "Jio fiber complaint", "Airtel xstream issue", "ACT broadband renewal",
    "set top box restart", "DTH plan compare", "Hotstar plan switch", "Netflix family plan",
    "Audible credit balance", "Kindle library list", "library overdue book",
    "second hand book sell", "toy donation", "old clothes donation", "shoe donation list",
    "blanket donation drive", "blood donation date", "eye donation pledge",
    "covid vaccine certificate", "yellow fever certificate", "tetanus shot due",
    "dental cleaning slot", "dentist x-ray", "orthodontist follow up",
    "spectacle prescription", "contact lens order", "physio session", "joint pain log",
    "knee xray copy", "lab report follow up", "ECG scan note", "blood test fasting",
    "vitamin level check", "thyroid TSH", "cholesterol panel", "BP morning reading",
    "diabetes log breakfast", "insulin reminder", "amma sugar reading", "appa BP reading",
    "weight target April", "step count target", "running shoe replacement",
    "yoga mat replacement", "cycle tube replacement", "fitness tracker charging",
    "sleep log Monday", "screen time review", "office trip itinerary",
    "client meeting notes", "vendor email draft", "office laptop issue", "VPN renewal",
    "office Wi-Fi password", "team standup notes", "design review feedback",
    "code review questions", "1:1 agenda", "promotion case draft",
    "skip level meeting", "company offsite", "office snacks list",
    "open enrollment benefits", "form 16 download", "PF withdrawal form",
    "travel reimbursement claim", "office gift exchange", "diwali bonus tracker",
    "appraisal notes", "team lunch venue", "work anniversary gift idea",
    "fish market schedule", "chicken delivery order", "mutton order Sunday",
    "egg packet order", "ghee bottle reorder", "tea dust premium",
    "agarbathi premium pack", "sambrani natural pack", "soan papdi gift box",
    "chocolate gift box list", "kerala parippu pradaman", "homemade ghee batch",
    "pickle batch summer", "vatha kuzhambu spice ratio", "rasam powder homemade ratio",
    "sambar powder mix", "chutney podi recipe", "filter coffee ratio note",
    "milk boiling thumb rule", "curd setting tip", "homemade icecream batch",
    "kids snack box week", "tiffin box shopping", "roti maker brand compare",
    "kanji rice ratio", "tamarind concentrate jar", "drumstick supplier list",
    "vegetable monthly contract", "milk vendor switch note", "newspaper switch note",
    "internet plan compare", "mobile plan compare", "credit card switch list",
    "bank account move", "bank locker visit", "bank ATM card reissue",
]
_extend_unique(INDIA_NOTE_TOPICS, _PH3_INDIA_NOTE_TOPICS_NEW)


# --- GLOBAL_NOTE_TOPICS (target: ~180 -> ~330) ---
_PH3_GLOBAL_NOTE_TOPICS_NEW = [
    "farmers market route", "weekend hike loop", "trail running notes",
    "kayak rental quote", "art class supplies", "pottery glaze ratios",
    "pottery firing schedule", "bookbinding kit", "leather wallet repair",
    "linen sheet fold", "duvet cover swap", "winter coat dry clean",
    "fur coat storage", "bike chain wax", "ski wax routine", "snow shovel storage",
    "summer tire swap", "tire pressure log", "car wash subscription",
    "valet parking note", "taxi receipt photo", "bus route detour memo",
    "metro card auto reload", "city bike membership", "subway card balance",
    "scooter rental account", "package delivery box", "front door bell battery",
    "garage door opener", "ring doorbell battery", "smart lock guest code",
    "guest wifi password", "router firmware update", "smart bulb scene",
    "thermostat schedule", "dishwasher rinse aid", "fridge water filter",
    "ice maker tray", "garbage disposal jam", "compost bin liner",
    "yard waste pickup", "leaf blower battery", "lawn mower oil",
    "garden seedling list", "tomato variety log", "herb planter shade",
    "succulent watering schedule", "cat litter brand", "dog grooming slot",
    "vet vaccination dose", "pet boarding rate", "fish tank cleaning",
    "aquarium plant note", "hamster cage refill", "bird feeder seed mix",
    "tea house list", "cold brew ratio", "espresso shot grind", "barista class slot",
    "wine pairing flight", "cocktail menu draft", "homebrew batch",
    "kombucha SCOBY", "sourdough hydration", "starter feeding schedule",
    "bread loaf log", "knife sharpening date", "cutting board oil",
    "cast iron seasoning", "wok seasoning batch", "pizza oven temperature",
    "sushi vinegar ratio", "weeknight meal prep", "smoothie packs",
    "freezer label list", "spice grinder cleaning", "mason jar inventory",
    "gym membership renewal", "personal training session", "running shoe rotation",
    "marathon training week", "race bib pickup", "yoga studio drop in",
    "pilates reformer slot", "barre class card", "boxing gloves replace",
    "swim cap reorder", "tide chart winter", "snowfall forecast",
    "winter coat tag", "winter tire tag", "boot heel repair",
    "shoe repair cobbler", "leather jacket waterproof", "passport renewal slot",
    "TSA precheck renewal", "global entry interview", "frequent flyer transfer",
    "hotel points balance", "bnb cleaning fee", "campsite reservation",
    "national park pass", "fishing license renewal", "hunting permit renewal",
    "kayak storage shed", "tent pole repair", "sleeping bag wash",
    "hiking boot reproof", "trail map cache", "GPS firmware",
    "headlamp battery", "first aid kit refill", "trail mix recipe",
    "camping food list", "climbing gym membership", "harness expiration",
    "rope retire date", "summer reading list", "winter reading list",
    "library hold queue", "ebook hold pickup", "audiobook credit",
    "podcast subscription", "newsletter cleanup", "email rules update",
    "calendar block focus", "weekly review note", "monthly review",
    "quarter goals", "annual review draft", "OKR draft",
    "company annual report", "stock vesting note", "RSU release date",
    "401k contribution", "HSA balance check", "FSA receipts",
    "open enrollment plan", "dental insurance card", "vision plan card",
    "primary care appointment", "specialist referral", "blood draw fasting",
    "physical therapy slot", "massage gift card", "studio class card",
    "ferry timing note", "cabin rental list", "skiing trip plan",
    "snowboard wax",
]
_extend_unique(GLOBAL_NOTE_TOPICS, _PH3_GLOBAL_NOTE_TOPICS_NEW)


# --- INDIA_EXPENSE per group (each group ~doubled or +30-50%) ---
INDIA_EXPENSE["groceries"].extend([
    "vellam puli", "karuppatti", "naatu sakkarai", "panangkalkandu", "pal kova",
    "thirattipal", "pottukadalai", "verkadalai", "muthuchola", "ulundhamavu",
    "milagai vatral", "manatakkali vatral", "sundakkai vatral", "kothavarangai dry",
    "puli paste", "elumichai pickle", "narthangai pickle", "perandai thuvaiyal",
    "agasthi keerai", "ponnanganni keerai", "manathakkali keerai", "araikeerai",
    "sirukeerai", "mulaikeerai", "thandukeerai", "vendhaya keerai",
    "puliyodharai mix", "kuzhambu podi", "kara kuzhambu mix", "araithu vitta sambar mix",
    "milagai thool", "kothu kari masala", "biriyani masala", "chicken masala",
    "mutton masala", "fish masala", "chettinad masala", "andhra masala",
    "kollu paruppu", "horse gram flour", "ragi semiya", "millet semiya",
    "ponni rice", "kuruvai arisi", "sona masuri", "samba arisi", "boiled rice",
    "raw rice", "sago packet", "kerala matta rice", "broken wheat",
    "barnyard millet", "kodo millet", "little millet flour",
])
INDIA_EXPENSE["transport"].extend([
    "tnstc ticket", "deluxe AC bus", "Volvo intercity", "sleeper express bus",
    "shared cab evening", "ola bike", "uber moto", "Rapido bike taxi",
    "metro pink line", "EMU local fare", "MMTS fare", "double decker bus",
    "school van fare", "college bus monthly", "office shuttle pass",
    "boat ride", "ECR toll", "GST toll", "vehicle towing fee",
    "monthly two wheeler park", "subway escalator card", "luggage scan fee",
    "cab cancellation fee", "ride surge fare", "cab hatchback rental",
    "cab sedan day rental", "cargo auto fare", "tempo trip fare",
    "MTC bus monthly pass", "intercity sleeper berth",
])
INDIA_EXPENSE["dining"].extend([
    "ginger rice plate", "kothu chappathi parcel", "podi dosa", "ghee podi dosa",
    "paniyaram half plate", "puttu kadalai parcel", "appam stew",
    "carrot halwa hot", "gulab jamun pair", "rasmalai single", "jangiri jalebi",
    "mysore pak", "Iyengar bakery cake", "Adyar Ananda Bhavan thaali",
    "Sangeetha veg meals", "Aramane biryani", "Thalapakatti biryani parcel",
    "Buhari biryani", "Anjappar dinner", "Dindigul biryani", "MTR meal",
    "Komala mini meals", "kerala parotta beef chukka", "Pondicherry french coffee",
    "Marina beach sundal pack", "kothu parotta egg", "filter coffee strong",
    "rava idli sambar", "kal dosa kara chutney", "ven pongal ghee",
])
INDIA_EXPENSE["bills_utilities"].extend([
    "TNEB bill quarterly", "BSNL fiber bill", "Jio fiber annual",
    "ACT broadband bill", "Tikona bill", "DTH set top box upgrade",
    "tata sky annual", "Sun direct annual", "newspaper monthly",
    "milk monthly bill", "egg vendor bill", "vegetable monthly",
    "house tax half year", "professional tax", "lift maintenance levy",
    "watchman tip", "sweeper monthly", "milkman tip", "newspaperboy tip",
    "RO membrane replacement", "geyser AMC", "AC service bill",
    "fan capacitor replacement", "tube light bulk pack", "watchman bonus diwali",
    "festival bonus maid",
])
INDIA_EXPENSE["recharge_subscription"].extend([
    "Disney Hotstar mobile", "ZEE5 family", "SonyLIV premium", "ALTBalaji",
    "MX Player Gold", "Voot Select", "JioSaavn Pro", "Wynk Music",
    "Hungama Music", "Audible India", "Storytel India", "Pratilipi premium",
    "Kuku FM annual", "ShareChat plus", "DailyHunt premium",
    "TheKen subscription", "TOI plus", "ET prime", "Mint premium",
    "Practo plus", "1mg subscription", "Cult.fit Live", "HealthifyMe coach",
    "BYJU's monthly", "Vedantu pro", "Unacademy plus", "PhysicsWallah PW skills",
    "Coursera India plan", "edX one year", "MapMyIndia plus",
])
INDIA_EXPENSE["household"].extend([
    "rangoli stencil", "kolam podi pack", "manjapodi packet", "vibhuti packet",
    "sandalwood paste tube", "kumkumam packet", "lehyam packet", "samrani brick",
    "karpooram tin", "lemongrass oil", "eucalyptus oil", "wick cotton thread",
    "lamp oil bottle", "achaar bottle large", "stainless steel tiffin",
    "copper bottle", "silver glass set", "iron tawa large", "appa kuzhi pan",
    "paniyaram pan", "idli plate", "dosa plate", "modak mould", "kadhai",
    "cooker gasket", "whistle replacement", "mixie jar gasket", "mixie blade",
    "rolling pin wood", "chappathi plate", "tortilla press", "lemon squeezer",
    "mortar pestle stone", "coconut scraper", "rasam dabra", "filter coffee dabra",
    "ladle long handle", "pickle ladle", "buttermilk churner", "spice box wooden",
    "spice box steel", "cane basket", "dustpan brush", "incense oil",
])
INDIA_EXPENSE["health"].extend([
    "Vicks bottle", "Iodex tube", "Volini gel", "Moov spray", "Krocin tablet strip",
    "Saridon strip", "Disprin packet", "Pudin Hara liquid", "Eno bottle",
    "Digene tablets", "Combiflam strip", "Dolo 650 strip", "Calpol drops",
    "Sinarest tablet", "Otrivin nasal spray", "Cyclopam tablet",
    "ORS sachet pack", "Electral powder", "Pediasure tin", "Horlicks tin",
    "Bournvita tin", "Ensure powder", "Protinex pack", "Glucon-D bottle",
    "Boost tin", "Complan tin", "Revital capsules", "shelcal tablets",
    "neurobion forte strip", "B12 injection", "iron syrup", "calcium syrup",
    "vitamin D3 sachet", "thyronorm tablet", "metformin strip", "telma tablet",
])
INDIA_EXPENSE["personal_care"].extend([
    "kumkumadi tailam", "navara oil", "brahmi oil", "kasi rasam oil",
    "mehendi cone", "Henna powder", "alvera gel pump", "ubtan pack",
    "multani mitti pack", "rose water bottle", "neem face wash",
    "turmeric face wash", "saffron cream", "kohl stick", "sandalwood soap",
    "Mysore sandal soap", "Medimix soap", "Margo soap", "Hamam soap",
    "Cinthol soap", "Nirma soap", "Santoor soap", "Patanjali toothpaste",
    "Babool toothpaste", "Vicco vajradanti", "Sensodyne tube",
    "Colgate strong teeth", "Pepsodent express", "Closeup gel",
    "tongue cleaner steel", "earbuds cotton 100", "shaving gel tube",
    "aftershave bottle", "trimmer charger", "razor blade pack",
    "facial razor pack", "wax strips", "veet cream", "fairness cream small",
    "lipgloss tube", "kajal pencil", "talcum powder large",
])
INDIA_EXPENSE["education"].extend([
    "exam pad", "compass box", "geometric kit", "color pencils 24",
    "sketch pen 12", "crayon big box", "wax crayons", "highlighter set",
    "scale steel 30cm", "protractor 180", "set squares pair", "erasers pack",
    "sharpener pack", "stapler small", "punch machine", "file rack",
    "answer sheet pack", "exam writing paper", "graph book", "drawing book A4",
    "lab manual physics", "lab manual chemistry", "observation note",
    "school diary", "homework planner", "subject notebook 100p",
    "long notebook 200p", "math practice book", "english reader",
    "tamil reader", "social book guide", "olympiad workbook",
    "math olympiad fee", "science olympiad fee", "spelling bee fee",
    "model exam fee tuition",
])
INDIA_EXPENSE["work"].extend([
    "office stamp", "rubber stamp ink", "carbon paper", "cellotape large",
    "double-sided tape", "post-it sticky", "binder clip large", "paper weight",
    "letterhead bundle", "envelope small", "envelope large",
    "courier envelope", "speed post receipt", "registered post fee",
    "GST invoice book", "delivery challan book", "voucher book",
    "cash bill book", "kyc form", "annexure form", "audit folder",
    "files cardboard", "lever arch file", "presentation folder",
    "name card holder", "pen drive 32GB", "pen drive 64GB",
    "external hard disk 1TB", "wireless mouse", "USB hub", "card reader",
    "monitor cleaning kit", "laptop bag", "cable organizer",
])
INDIA_EXPENSE["entertainment"].extend([
    "movie ticket multiplex", "movie ticket single screen", "play ticket",
    "drama show", "music concert pass", "kutcheri season ticket",
    "Margazhi season pass", "carnatic concert", "qawwali ticket",
    "ghazal night", "stand up comedy", "mimicry show", "dance program",
    "bharatanatyam arangetram", "school anniversary ticket",
    "sports stadium ticket", "cricket match ticket", "kabaddi match ticket",
    "marina kite festival", "Saaral fun park", "VGP universal kingdom",
    "Queens Land park", "MGM Dizzee World", "wonderla day pass",
    "snow world pass", "trampoline park", "go kart fee", "laser tag",
    "bowling lane", "billiards hour",
])
INDIA_EXPENSE["travel"].extend([
    "AC bus berth", "non-AC sleeper", "SETC online booking", "SRTC ticket",
    "RedBus convenience fee", "MakeMyTrip booking", "Yatra hotel",
    "Goibibo cab", "Cleartrip cancellation", "IRCTC tatkal fee",
    "rail food order", "airport food court", "domestic flight Indigo",
    "spicejet bag fee", "vistara meal", "airport lounge",
    "boarding pass print", "hotel laundry bill", "hotel mini bar",
    "checkout late fee", "tourist taxi day", "guide tip", "monument entry",
    "boat ride lake", "houseboat backwater", "trekking permit",
    "homestay rent", "dormitory bed", "international SIM card",
])
INDIA_EXPENSE["vehicle"].extend([
    "petrol bunk topup", "diesel litre", "oil change full", "engine flush",
    "coolant top up", "wiper fluid", "battery jumper service",
    "puncture car tubeless", "puncture cycle tube", "AC gas refill car",
    "denting painting estimate", "headlight bulb", "tail light", "fuse pack",
    "horn replacement", "speedometer cable", "clutch plate", "brake pad",
    "tire alignment", "wheel balancing", "nitrogen fill", "rim repair",
    "tire change car", "tire change bike", "RC book renewal",
    "puc certificate", "insurance pickup", "bike polish", "interior shampoo",
    "underbody wash", "rust treatment", "paint touch up", "side stand spring",
])
INDIA_EXPENSE["shopping"].extend([
    "saree blouse stitching", "silk saree dry clean", "shirt button stitching",
    "trouser hemming", "kurta tailoring", "kids dress stitch",
    "uniform sewing", "pillow cover stitch", "curtain hemming",
    "sofa cover order", "mattress cover", "leather strap repair",
    "watch battery", "watch strap", "spectacle frame repair",
    "spectacle lens", "contact lens box", "phone screen guard",
    "phone case", "earphone replacement", "bluetooth headset", "power bank",
    "USB cable type C", "lightning cable", "smartwatch strap",
    "festival saree gift", "wedding saree gift", "school bag kid",
    "lunch bag insulated", "umbrella foldable", "raincoat full body",
    "swim cap goggles", "yoga mat thick", "exercise band", "kettlebell 4kg",
    "dumbbell pair 2kg", "cycling helmet", "bike pump foot", "cycle horn",
])
INDIA_EXPENSE["other"].extend([
    "donation temple hundi", "gurdwara langar contribution",
    "church charity donation", "NGO online donation", "old age home contribution",
    "orphanage donation", "PM cares donation", "marriage gift envelope",
    "first birthday return gift", "naming ceremony gift", "60th birthday gift",
    "70th birthday gift", "house warming gift", "engagement gift",
    "neighbor wedding gift", "office colleague farewell gift",
    "joining bouquet", "card and chocolate", "raksha bandhan return gift",
    "diwali sweets to neighbors", "pongal gift hamper", "client gift hamper",
    "vendor diwali gift", "ground breaking pooja", "gruhapravesam pooja kit",
    "satyanarayana pooja", "ayudha pooja kit", "saraswati pooja",
    "navarathri golu items", "kalasha pot", "homam ghee", "homam wood",
    "dakshina envelope",
])


# --- GLOBAL_EXPENSE per group (~doubled) ---
GLOBAL_EXPENSE["groceries"].extend([
    "rye bread", "ciabatta loaf", "baguette", "pretzels", "bagel cream cheese",
    "almond butter jar", "peanut butter natural", "apple butter jar",
    "maple syrup small", "honey local", "olive oil cold pressed",
    "balsamic vinegar", "white wine vinegar", "soy sauce low sodium",
    "fish sauce", "miso paste", "tahini jar", "kalamata olives",
    "feta crumbles", "mozzarella ball", "ricotta tub", "cottage cheese",
    "cream cheese block", "sour cream", "whipping cream pint", "ghee jar",
    "smoked salmon pack", "anchovy tin", "tuna can in oil", "sardines tin",
    "kale bunch", "arugula bag", "radicchio head", "fennel bulb",
    "leek bunch", "watercress", "endive heads", "shallots mesh",
    "swiss chard", "bok choy", "tatsoi", "rapini", "sun choke",
    "chestnuts mesh", "dragon fruit", "passion fruit", "rye crackers",
    "rice cakes", "trail mix bag", "porridge oats", "berry jam",
    "marmalade jar", "almond milk", "soy milk vanilla",
])
GLOBAL_EXPENSE["transport"].extend([
    "uber x", "uber pool", "lyft shared", "via shared ride",
    "subway monthly", "metro card load", "regional rail",
    "amtrak weekend", "MTA express bus", "ferry monthly",
    "bike share annual", "scooter share unlock", "carpool gas split",
    "long distance train", "tram ticket", "tram day pass",
])
GLOBAL_EXPENSE["dining"].extend([
    "sourdough sandwich", "club sandwich", "ramen bowl", "pho bowl",
    "pad thai", "burrito bowl", "burrito wrap", "taco trio",
    "fish and chips", "kebab plate", "shawarma wrap", "falafel plate",
    "pizza slice", "pasta primavera", "salad bowl", "smoothie large",
])
GLOBAL_EXPENSE["bills_utilities"].extend([
    "natural gas bill", "trash pickup", "recycling fee", "snow removal monthly",
    "lawn care monthly", "pest control quarterly", "pool service",
    "cable bundle", "satellite dish", "VOIP phone", "home alarm monitoring",
    "doorbell camera plan", "yard waste pickup",
])
GLOBAL_EXPENSE["recharge_subscription"].extend([
    "Spotify premium individual", "YouTube TV", "ESPN+", "Apple TV+",
    "Apple One bundle", "Adobe Creative Cloud", "Microsoft 365 family",
    "Google One 200GB", "Dropbox plus", "Notion plus", "Substack subscription",
    "Patreon contribution", "Twitch sub gift", "Eero Plus",
])
GLOBAL_EXPENSE["household"].extend([
    "kitchen sponges pack", "microfiber cloths", "swiffer pads",
    "Ziploc gallon bags", "parchment paper roll", "aluminum foil heavy",
    "paper towel value pack", "trash bags 13gal", "trash bags lawn",
    "Brita filter pack", "PUR filter pack", "humidifier filter",
    "vacuum bags", "robot vac bin liner", "stainless cleaner spray",
    "dishwasher detergent pods", "fabric softener", "stain remover spray",
    "carpet cleaner concentrate", "drain unclog liquid",
])
GLOBAL_EXPENSE["health"].extend([
    "Tylenol bottle", "Advil tablets", "Aleve tablets", "DayQuil bottle",
    "NyQuil bottle", "Mucinex tablets", "Pepto bottle", "Tums roll",
    "Benadryl pack", "Zyrtec tablets", "Flonase spray",
    "antibiotic ointment tube", "bandage variety pack", "sterile gauze roll",
    "antiseptic wipes",
])
GLOBAL_EXPENSE["personal_care"].extend([
    "razor cartridges 4-pack", "shaving cream tube", "after shave splash",
    "hair gel", "hair pomade", "beard oil", "hand cream tube",
    "foot cream", "cuticle oil", "nail polish remover", "nail polish bottle",
    "deodorant solid", "antiperspirant spray", "body wash large",
    "exfoliating scrub", "salt scrub jar", "lip scrub", "facial mist",
])
GLOBAL_EXPENSE["education"].extend([
    "online course enrollment", "Coursera plus annual", "edX subscription",
    "MasterClass annual", "Skillshare annual", "Udemy course bundle",
    "Duolingo plus", "Babbel subscription", "writing course fee",
    "art workshop", "photography workshop", "cooking class", "music lesson",
])
GLOBAL_EXPENSE["work"].extend([
    "USB-C hub", "monitor stand", "ergonomic mouse", "mechanical keyboard",
    "laptop stand", "noise cancelling headphones", "webcam HD", "ring light",
    "boom mic arm", "desk pad XXL", "cable tray", "monitor arm",
    "footrest", "wrist rest pair", "standing desk converter",
])
GLOBAL_EXPENSE["entertainment"].extend([
    "concert ticket lawn", "comedy club cover", "trivia night entry",
    "escape room booking", "axe throwing slot", "bowling shoe rental",
    "mini golf round", "arcade card", "pinball arcade", "drive-in ticket",
    "theater playbill", "ballet ticket", "opera nosebleed", "symphony ticket",
])
GLOBAL_EXPENSE["travel"].extend([
    "TSA PreCheck renewal", "Global Entry interview", "passport renewal fee",
    "visa application fee", "ESTA fee", "ETA Canada", "lounge day pass",
    "rental car insurance", "tolls EZ pass", "parking airport long",
    "parking airport short", "shuttle to airport", "porter tip",
    "international SIM", "travel insurance trip", "hotel resort fee",
    "hotel parking", "cruise gratuity",
])
GLOBAL_EXPENSE["vehicle"].extend([
    "synthetic oil change", "tire rotation", "brake fluid flush",
    "transmission fluid", "wiper blades pair", "headlight bulb LED",
    "tire mount and balance", "alignment check", "battery replacement",
    "alternator service", "fuel filter", "cabin air filter",
    "engine air filter", "spark plug set", "serpentine belt",
    "timing belt service", "AC recharge", "windshield repair",
])
GLOBAL_EXPENSE["shopping"].extend([
    "throw pillows", "duvet cover queen", "bath mat set", "shower curtain",
    "kitchen rug", "wall mirror", "framed art", "houseplant pot",
    "indoor plant", "outdoor plant", "garden gloves", "garden trowel",
    "yoga block pair", "resistance bands", "kettlebell",
])
GLOBAL_EXPENSE["other"].extend([
    "PO box rental", "wire transfer fee", "bank wire", "stamp roll",
    "passport photo", "notary fee", "lawyer consult fee", "accountant fee",
    "donation animal shelter", "donation food bank", "donation library",
    "online tip jar", "GoFundMe contribution", "crowdfunded gift",
    "wedding gift envelope",
])


# --- INDIA_BUY direct (target: ~546 -> ~700) ---
_PH3_INDIA_BUY_NEW = [
    "kollu paruppu pack", "horse gram pack", "sundal pack ready",
    "ragi malt powder", "millets multipack", "amaranth packet",
    "barnyard millet", "kodo millet", "little millet rice",
    "little millet flour", "kambu maavu", "varagu rice pack",
    "samai rice pack", "thinai pack", "panivaragu pack", "sago pack",
    "puffed lotus seeds", "coconut milk powder", "tamarind paste tube",
    "garlic ginger paste", "curry leaves frozen", "moringa leaves dried",
    "nilgiri tea", "filter coffee decoction", "instant coffee jar",
    "darjeeling tea pack", "assam tea black", "spearmint leaves",
    "lemon grass dried", "vanilla extract", "saffron strands",
    "cardamom whole", "cloves whole", "star anise", "fennel seed",
    "fenugreek seed", "ajwain pack", "kasuri methi", "amchur powder",
    "kala namak", "rock salt", "sea salt", "pink salt",
    "buttermilk masala", "rasam masala packet", "vatha kuzhambu mix",
    "kara kuzhambu mix", "puli kuzhambu mix", "milagu rasam mix",
    "thakkali rasam mix", "more kuzhambu mix", "instant pongal mix",
    "instant upma mix", "instant rava idli", "ready dosa batter",
    "ready idli batter", "ready chutney", "ready sambar",
    "fresh paneer block", "tofu block", "soya chunks", "soya granules",
    "wheat germ", "oat bran", "chia seeds", "flax seeds",
    "pumpkin seeds", "sunflower seeds", "mixed seeds pack",
    "trail mix pack", "almond pack", "cashew pack", "raisins black",
    "raisins golden", "dried figs", "dried dates", "anjeer pack",
    "dry coconut wedges", "khopra ball", "jaggery cubes", "palm sugar",
    "honey raw", "honey forest", "ghee cow", "ghee buffalo",
    "groundnut oil cold pressed", "coconut oil cold pressed",
    "sesame oil pure", "mustard oil", "rice bran oil", "sunflower oil",
    "vegetable oil pouch", "olive oil pomace", "instant mango pickle",
    "lime pickle bottle", "garlic pickle bottle", "tomato pickle bottle",
    "mixed pickle bottle", "vegetable cleaner", "fruit wash",
    "kitchen tongs", "ladle slotted", "ladle solid", "ladle rice",
    "rolling board", "chappathi cloth", "tiffin steel three tier",
    "tiffin steel single", "ice tray", "ice cube bag",
    "freezer bag pack", "vacuum food bag", "cling wrap roll",
    "kitchen towel cotton", "tea towel", "table mat set",
    "dining chair cushion", "candle pillar", "diya brass",
    "lamp stand brass", "kuthu vilakku large", "puja thali set",
    "incense stick pack", "agarbathi flora", "agarbathi sandal",
    "camphor box", "rangoli mat", "betel leaves", "betel nut",
    "puffed rice puja", "cotton wick long", "lamp oil bottle",
    "honey small bottle", "rosewater small", "almonds salted",
    "cashews fried", "groundnut chikki", "til chikki", "halwa cubes",
    "milk pedha box", "thirupathi laddu",
]
_extend_unique(INDIA_BUY, _PH3_INDIA_BUY_NEW)


# --- GLOBAL_BUY (target: ~156 -> ~256) ---
_PH3_GLOBAL_BUY_NEW = [
    "english muffins", "everything bagels", "rye crackers", "rice cakes",
    "wasabi peas", "trail mix bag", "granola jar", "muesli pack",
    "porridge oats", "instant oatmeal sachets", "berry jam", "lemon curd",
    "marmalade jar", "almond milk", "oat milk barista", "soy milk vanilla",
    "rice milk", "coconut milk drink", "kefir bottle", "yogurt drink",
    "greek yogurt large", "skyr yogurt", "labneh tub", "queso fresco",
    "manchego wedge", "gouda wedge", "brie wheel", "camembert wheel",
    "blue cheese", "smoked cheddar", "halloumi block", "olive tapenade",
    "pesto basil", "harissa paste", "sriracha bottle", "kewpie mayo",
    "wasabi paste", "panko crumbs", "sushi rice", "rice vinegar",
    "mirin bottle", "sake cooking", "seaweed sheets", "tofu silken",
    "edamame frozen", "kimchi jar", "sauerkraut jar", "pickled onions",
    "capers jar", "anchovy paste", "tomato paste tube", "tomato passata",
    "canned tomatoes", "marinara sauce", "alfredo sauce", "ranch dressing",
    "blue cheese dressing", "caesar dressing", "italian dressing",
    "balsamic glaze", "sherry vinegar", "champagne vinegar",
    "apple cider vinegar", "decaf coffee beans", "espresso beans",
    "matcha powder", "chai latte mix", "hot cocoa packets",
    "marshmallows mini", "graham crackers", "chocolate chips",
    "white chocolate chips", "almond extract", "baking soda box",
    "baking powder can", "yeast packets", "active dry yeast",
    "instant yeast jar", "self-rising flour", "bread flour",
    "whole wheat flour", "rye flour", "buckwheat flour", "almond flour",
    "coconut flour", "oat flour", "gluten free flour blend",
    "powdered sugar", "brown sugar light", "brown sugar dark",
    "demerara sugar", "turbinado sugar", "stevia packets",
    "monk fruit sweetener", "agave nectar", "maple sugar", "vanilla beans",
    "saffron threads",
]
_extend_unique(GLOBAL_BUY, _PH3_GLOBAL_BUY_NEW)


# --- INDIA_TODOS (target: ~2356 -> ~2500, modest +150 per user) ---
_PH3_INDIA_TODOS_NEW = [
    "renew Aadhaar biometric", "fix Aadhaar address", "submit ration card photo",
    "follow up gas subsidy refund", "verify EPF claim status", "update PAN address",
    "link PAN with Aadhaar", "raise UPI dispute", "claim train ticket refund",
    "raise IRCTC complaint", "pickup parcel from post office",
    "pickup courier from neighbor", "drop courier at center",
    "drop saree for fall stitching", "fit new contact lenses",
    "update gas connection KYC", "update bank KYC", "update mutual fund KYC",
    "renew PPF account", "convert savings to FD", "withdraw from FD",
    "redeem post office NSC", "verify electricity bill change",
    "raise EB complaint", "fix water leak in tank", "service iron box",
    "service mixie", "service grinder", "fix kitchen exhaust",
    "service AC indoor", "service AC outdoor", "service split AC compressor",
    "service refrigerator gasket", "fix microwave door",
    "service washing machine drain", "schedule pest control termite",
    "schedule pest control cockroach", "schedule pest control rats",
    "deep clean kitchen counter", "remove stains from terrace",
    "fix terrace water seepage", "paint balcony", "paint pooja room",
    "paint kitchen", "fix bathroom tile crack", "service geyser element",
    "schedule water tank cleaning", "schedule sump cleaning",
    "schedule borewell motor service", "fix balcony grill rust",
    "fix bedroom curtain rod", "rehang curtains", "rotate mattress",
    "wash sofa cover", "drop saree for embroidery",
    "buy gift for amma birthday", "buy gift for appa birthday",
    "buy gift for sister anniversary", "buy gift for nephew first birthday",
    "book wedding hall", "advance for wedding hall", "follow up with caterer",
    "shortlist photographer", "book mehendi artist", "book bridal makeup",
    "book wedding car", "book temple priest", "consult astrologer",
    "match horoscope", "draft wedding invite", "print wedding invite",
    "share wedding invite digital", "shop wedding garlands",
    "shop wedding sweets boxes", "buy mangalasutra", "renew car insurance",
    "renew bike insurance", "renew health insurance", "renew term life",
    "claim medical reimbursement", "follow up with HR for tax",
    "submit Form 16", "claim HRA", "submit rent agreement",
    "submit LTA proof", "submit children school fee proof",
    "submit medical insurance proof", "verify ITR refund",
    "raise ITR rectification", "follow up with CA on returns",
    "schedule eye checkup", "schedule annual blood panel",
    "schedule diabetes review", "schedule cardio checkup",
    "follow up with neurologist", "renew international license",
    "schedule visa appointment", "submit visa documents",
    "pickup visa stamp", "drop kid at coaching", "pickup kid from coaching",
    "pay tuition fee", "pay creche fee", "pay sports fee",
    "pay music class fee", "buy sports kit", "buy school uniform",
    "stitch school uniform", "buy school shoes", "label school books",
    "cover school books", "fill school diary", "attend PTA meeting",
    "follow up with class teacher", "fill scholarship form",
    "submit scholarship documents", "tour college campus",
    "compare school options", "visit school open day",
    "pay annual fee", "pay van fee", "schedule kid haircut",
    "service iron box belt", "fix doorbell switch", "tighten loose taps",
    "drain washbasin", "clean kitchen chimney filter",
    "polish brass items", "wash silver items", "freshen incense holder",
    "refill water purifier salt", "buffer hospital documents",
    "scan hospital bills", "upload reimbursement documents",
    "renew domain name", "renew SSL certificate", "rotate router admin password",
    "audit DNS records", "backup family photos cloud",
    "download bank statement quarterly", "tally credit card bills",
    "settle relative loan", "send festival sweets neighbor",
]
_extend_unique(INDIA_TODOS, _PH3_INDIA_TODOS_NEW)


# --- INDIA_TODO_NOUNS (target: ~676 -> ~780, +100) ---
_PH3_INDIA_TODO_NOUNS_NEW = [
    "tax filing", "ITR draft", "form 16 download", "rent agreement copy",
    "LTA proof", "HRA proof", "medical bill bundle", "school fee receipt",
    "uniform stitching", "shoe polish kit", "sports day kit",
    "annual function dress", "exam pad", "exam stationery",
    "PTA reminder", "loan closure letter", "credit card dispute",
    "phone EMI", "laptop EMI", "fridge EMI", "AC EMI", "scooter EMI",
    "car EMI", "house EMI", "personal loan EMI", "education loan EMI",
    "FD maturity", "RD maturity", "PPF deposit", "NPS contribution",
    "tax saver deposit", "section 80C investment", "ELSS SIP",
    "equity SIP", "mutual fund switch", "mutual fund redeem",
    "FD breakup", "loan top up", "house tax", "water tax",
    "professional tax", "society dues", "lift maintenance",
    "watchman bonus", "diwali bonus maid", "festival bonus driver",
    "kid summer camp", "kid coaching", "kid music class",
    "kid swim class", "kid drawing class", "kid karate class",
    "kid sports class", "kid skating class", "kid yoga class",
    "appa scan review", "amma scan review", "appa BP review",
    "amma sugar review", "father insurance renewal", "mother insurance renewal",
    "thatha medicine box", "paati medicine box", "anniversary celebration",
    "sister wedding", "brother wedding", "cousin wedding",
    "uncle birthday", "aunty birthday", "grandparent visit",
    "house warming visit", "naming ceremony visit", "first feast visit",
    "first birthday visit", "puberty function", "engagement function",
    "betrothal function", "kids haircut", "wife saree gift",
    "husband shirt gift", "kids toy gift", "amma saree", "appa shirt",
    "groceries weekly", "groceries monthly", "vegetables daily",
    "milk daily", "newspaper daily", "drinking water can",
    "broadband recharge", "mobile recharge", "DTH recharge",
    "OTT renewal", "domain renewal", "SSL certificate renewal",
    "festival sweets gift", "neighbor wedding gift", "office colleague gift",
    "client diwali gift",
]
_extend_unique(INDIA_TODO_NOUNS, _PH3_INDIA_TODO_NOUNS_NEW)


# --- GLOBAL_TODOS (target: ~968 -> ~1090, +120) ---
_PH3_GLOBAL_TODOS_NEW = [
    "cancel subscription", "schedule chimney cleaning", "schedule HVAC service",
    "schedule gutter cleaning", "schedule lawn aeration",
    "schedule deck staining", "schedule mulch delivery",
    "schedule snow plowing", "schedule oil burner service",
    "schedule water softener service", "schedule septic pumping",
    "buy snow shovel", "buy ice melt bags", "buy weather strips",
    "buy storm windows", "buy dehumidifier", "buy humidifier filter",
    "buy air filter HVAC", "buy water filter", "buy fridge filter",
    "buy carbon monoxide detector", "buy smoke detector battery",
    "renew home warranty", "renew car warranty", "renew rental insurance",
    "renew umbrella insurance", "renew flood insurance", "renew health insurance",
    "schedule mammogram", "schedule colonoscopy",
    "schedule skin cancer screening", "schedule dental cleaning",
    "schedule eye exam", "schedule kid pediatrician",
    "schedule kid dentist", "schedule kid orthodontist",
    "schedule pet annual checkup", "schedule pet teeth cleaning",
    "schedule pet grooming", "schedule pet boarding", "buy pet food brand",
    "buy pet medication", "buy pet treats", "renew pet license",
    "update pet microchip", "renew driver license",
    "schedule eye exam DMV", "schedule REAL ID", "renew TSA precheck",
    "renew global entry", "renew passport book",
    "schedule visa interview", "renew NEXUS card",
    "update emergency contact", "update beneficiary",
    "review will", "update will", "update power of attorney",
    "schedule estate review", "schedule retirement review",
    "review 401k allocation", "max out 401k", "max out IRA",
    "open Roth IRA", "rollover 401k", "review HSA balance",
    "review FSA balance", "submit FSA receipts",
    "submit dependent care receipts", "schedule kids haircut",
    "schedule barber", "drop dry cleaning", "pickup dry cleaning",
    "drop shoes for repair", "pickup shoes from cobbler",
    "drop watch for repair", "pickup watch", "drop jewelry for cleaning",
    "drop coat for tailoring", "schedule tailor fitting",
    "buy birthday gift", "buy anniversary gift", "buy mothers day gift",
    "buy fathers day gift", "buy holiday gifts", "buy hostess gift",
    "wrap gifts", "ship gifts", "send thank you cards",
    "send birthday cards", "send anniversary cards",
    "send sympathy cards", "send wedding cards", "RSVP to wedding",
    "RSVP to dinner", "schedule lunch with friend",
    "schedule coffee with mentor", "schedule call with sister",
    "schedule call with brother", "video call parents",
    "video call grandparents", "schedule networking call",
    "respond to recruiter", "schedule interview",
    "follow up after interview", "send thank you email interview",
    "negotiate salary offer", "review offer letter", "sign offer letter",
    "submit background check", "submit i-9 documents",
    "submit references", "schedule first day onboarding",
    "complete benefits enrollment", "request office equipment",
    "set up direct deposit", "schedule chimney sweep",
    "schedule deep clean", "schedule pressure wash",
    "schedule roof inspection",
]
_extend_unique(GLOBAL_TODOS, _PH3_GLOBAL_TODOS_NEW)


# --- GLOBAL_TODO_NOUNS (target: ~209 -> ~290, +80) ---
_PH3_GLOBAL_TODO_NOUNS_NEW = [
    "annual checkup", "physical exam", "eye exam", "dental cleaning",
    "skin screening", "mammogram", "colonoscopy", "blood draw",
    "urinalysis", "vaccination", "flu shot", "tetanus booster",
    "covid booster", "kid pediatric appointment", "kid orthodontist",
    "kid dental appointment", "pet vet visit", "pet grooming",
    "pet boarding", "pet food brand", "vehicle inspection",
    "emissions test", "tire rotation", "oil change", "wiper blades",
    "registration renewal", "driver license renewal", "passport renewal",
    "TSA precheck", "global entry", "REAL ID", "voter registration",
    "voter ID", "social security card", "birth certificate copy",
    "marriage certificate copy", "tax return draft", "1099 forms",
    "W2 forms", "estimated taxes", "401k contribution", "IRA contribution",
    "HSA contribution", "FSA receipts", "investment review",
    "portfolio rebalance", "credit report check", "credit score check",
    "credit card balance", "mortgage payment", "rent payment",
    "utility bill", "internet bill", "phone bill",
    "streaming subscription", "gym membership", "club membership",
    "coworking subscription", "subscription audit", "monthly budget",
    "weekly menu plan", "grocery list", "meal prep", "pantry inventory",
    "freezer inventory", "fridge clean out", "spice cabinet refresh",
    "pantry restock", "kitchen utility audit", "garage organization",
    "closet decluttering", "donation drop off", "thrift store run",
    "yard sale prep", "backyard cleanup", "garden bed prep",
    "compost turn", "lawn fertilizer", "tree pruning", "hedge trimming",
    "deck inspection", "roof inspection", "gutter clean",
    "chimney sweep", "fireplace inspection",
]
_extend_unique(GLOBAL_TODO_NOUNS, _PH3_GLOBAL_TODO_NOUNS_NEW)


# --- Tanglish corpora additions ---
# Note: the v2 generator routes Tanglish item words into INDIA_EXPENSE /
# INDIA_BUY at module-load time via the existing extends. We mirror that
# pattern for the new entries below so they're available to writes that
# embed Tamil item names inside English frames (Pattern A).

_PH3_TANGLISH_GROCERIES_NEW = [
    "vellam puli", "karuppatti", "naatu sakkarai", "panangkalkandu",
    "pal kova", "thirattipal", "pottukadalai", "verkadalai", "muthuchola",
    "milagai vatral", "manatakkali vatral", "sundakkai vatral",
    "kothavarangai dry", "puli paste", "narthangai pickle",
    "perandai thuvaiyal", "agasthi keerai", "ponnanganni keerai",
    "manathakkali keerai", "araikeerai", "sirukeerai", "mulaikeerai",
    "thandukeerai", "vendhaya keerai", "puliyodharai mix",
    "kuzhambu podi", "kara kuzhambu mix", "araithu vitta sambar mix",
    "kothu kari masala", "biriyani masala", "chettinad masala",
    "andhra masala", "kollu paruppu", "horse gram flour",
    "ragi semiya", "millet semiya", "ponni rice", "kuruvai arisi",
    "sona masuri", "samba arisi", "boiled rice", "raw rice",
    "kerala matta rice", "broken wheat", "barnyard millet",
    "kodo millet", "little millet flour", "kambu maavu",
    "varagu rice", "samai rice", "thinai pack",
]
_extend_unique(INDIA_EXPENSE["groceries"], _PH3_TANGLISH_GROCERIES_NEW)
_extend_unique(INDIA_BUY, _PH3_TANGLISH_GROCERIES_NEW)

_PH3_TANGLISH_HOUSEHOLD_NEW = [
    "thuni sabakaai", "vali", "moodi", "silver pot", "kuthu vilakku",
    "petromax", "kavasam", "parai", "kal urel", "ural",
    "peetam", "pettie", "thazhai", "muram", "ulai",
    "thattu", "vannam", "deepam stand", "kumkum tin",
    "saathagal", "salavai stick", "kolam mat",
    "rangoli stencil", "samrani brick", "karpooram tin",
]
_extend_unique(INDIA_EXPENSE["household"], _PH3_TANGLISH_HOUSEHOLD_NEW)
_extend_unique(INDIA_BUY, _PH3_TANGLISH_HOUSEHOLD_NEW)

_PH3_TANGLISH_PERSONAL_NEW = [
    "kumkumadi tailam", "navara oil", "brahmi taila", "kayam soap",
    "Mysore sandal soap", "Margo neem soap", "Medimix herbal",
    "Patanjali soap", "Hamam soap", "Cinthol classic",
    "Vicco vajradanti", "Lifebuoy total", "Patanjali shampoo",
    "Indulekha oil", "Kesh King", "Bajaj almond oil",
    "Parachute aftershower", "Nihar shanti amla", "Dabur amla oil",
    "Dhathri hair oil",
]
_extend_unique(INDIA_EXPENSE["personal_care"], _PH3_TANGLISH_PERSONAL_NEW)
_extend_unique(INDIA_BUY, _PH3_TANGLISH_PERSONAL_NEW)

_PH3_TANGLISH_NOTES_NEW = [
    "kollu rasam recipe note", "vetrilai paaku list", "veetu pooja items",
    "pongal samayal list", "deepavali sweets order",
    "amma kitta kaasu kudukanum note", "appa ku medicine reminder",
    "thangachi birthday gift", "akka anniversary plan",
    "veetu pulla wedding plan", "mottai maadi clean reminder",
    "neighbor borrowed vessel", "thaiyer manaivi recipe",
    "ammaikku wifi recharge", "thatha tablets list",
    "paati medicine list", "thanga nagai list", "puthusu vela apply",
    "karpooram refill", "agarbathi refill", "vibhuti packet refill",
    "kumkum refill", "rangoli stencil note", "pooja items shortlist",
    "kuthu vilakku oil refill",
]
_extend_unique(INDIA_NOTE_TOPICS, _PH3_TANGLISH_NOTES_NEW)

_PH3_TANGLISH_TODOS_NEW = [
    "amma medicine vaanganum", "appa ku call panna",
    "thangachi ku gift edukanum", "akka kitta kasu kudukanum",
    "thatha kitta poi pesa", "paati ku oil vaanganum",
    "sister kitta tho call panna", "brother ku message anuppanum",
    "amma veedu visit pannanum", "appa veedu visit pannanum",
    "office la file submit pannanum", "school la fees katanum",
    "college la form submit pannanum", "hostel la rent katanum",
    "shop la grocery list kudukanum", "kadai ku poi vaanganum",
    "vegetable kadai ku poganum", "milk kadai la account settle pannanum",
    "newspaper kasu kudukanum", "auto stand la pesa",
    "bank la kyc submit pannanum", "post office la parcel kudukanum",
    "passport office la appointment book panna",
    "RTO la papers submit pannanum", "EB office la complaint kudukanum",
    "TNEB online la bill kattanum", "BSNL la fiber complaint kudukanum",
    "Airtel la plan change pannanum", "Jio la recharge pannanum",
    "DTH la pack change pannanum", "broadband router restart pannanum",
    "Wi-Fi password change pannanum", "Aadhaar la address update panna",
    "PAN la name correction pannanum", "passport la address update panna",
    "voter ID la photo update panna", "ration card la member add panna",
    "driving licence la renew pannanum", "scooter ku PUC vaanganum",
    "bike ku service book panna", "car ku oil change panna",
    "amma ku scan review book panna", "appa ku BP review book panna",
    "kid ku tuition pay panna", "kid ku uniform stitch panna",
    "kid ku shoes vaanganum", "kid ku book label panna",
    "kid ku PTA poganum", "amma ku medicine refill panna",
    "appa ku medicine refill panna",
    "thaiyiru saree dry clean kudukanum",
    "wife ku saree gift vaanganum",
]
_extend_unique(INDIA_TODOS, _PH3_TANGLISH_TODOS_NEW)

_PH3_TANGLISH_TODO_NOUNS_NEW = [
    "amma medicine list", "appa medicine list", "thatha tablet box",
    "paati tablet box", "wife saree gift", "husband shirt gift",
    "kid school fee", "kid van fee", "kid coaching fee",
    "kid uniform stitching", "kid shoes update", "kid books cover",
    "diwali bonus maid", "festival bonus driver",
    "watchman tip diwali", "newspaperboy tip", "milkman tip",
    "veetu pooja items", "pongal samayal items",
    "deepavali sweets order", "neighbor borrowed vessel",
    "thanga nagai polish", "wedding hall booking",
    "wedding catering balance",
]
_extend_unique(INDIA_TODO_NOUNS, _PH3_TANGLISH_TODO_NOUNS_NEW)


# --- Brand × product seed expansions ---
# Each cross-product gets added to the relevant INDIA_EXPENSE bucket so the
# eligible item pool in writes / queries grows naturally without needing a
# new code path.

_PH3_INDIA_GROCERY_BRANDS_NEW = ["Idhayam", "Saffola", "Mother Dairy", "Heritage", "Britannia", "Parle"]
_PH3_INDIA_GROCERY_PRODUCTS_NEW = ["moong dal", "chana dal", "rice flour", "wheat flour", "semolina", "rasam powder"]
_extend_unique(
    INDIA_EXPENSE["groceries"],
    [f"{b} {p}" for b in _INDIA_GROCERY_BRANDS + _PH3_INDIA_GROCERY_BRANDS_NEW
     for p in _INDIA_GROCERY_PRODUCTS + _PH3_INDIA_GROCERY_PRODUCTS_NEW],
)

_PH3_INDIA_HOUSEHOLD_BRANDS_NEW = ["Surf Excel", "Tide", "Domex", "Colin", "Mr. Muscle"]
_PH3_INDIA_HOUSEHOLD_PRODUCTS_NEW = ["laundry powder", "stain remover", "drain cleaner", "antiseptic liquid"]
_extend_unique(
    INDIA_EXPENSE["household"],
    [f"{b} {p}" for b in _INDIA_HOUSEHOLD_BRANDS + _PH3_INDIA_HOUSEHOLD_BRANDS_NEW
     for p in _INDIA_HOUSEHOLD_PRODUCTS + _PH3_INDIA_HOUSEHOLD_PRODUCTS_NEW],
)

_PH3_INDIA_PERSONAL_CARE_BRANDS_NEW = ["Cinthol", "Hamam", "Mysore Sandal", "Medimix", "Margo"]
_PH3_INDIA_PERSONAL_CARE_PRODUCTS_NEW = ["deodorant", "talcum powder", "face cream", "lip balm"]
_extend_unique(
    INDIA_EXPENSE["personal_care"],
    [f"{b} {p}" for b in _INDIA_PERSONAL_CARE_BRANDS + _PH3_INDIA_PERSONAL_CARE_BRANDS_NEW
     for p in _INDIA_PERSONAL_CARE_PRODUCTS + _PH3_INDIA_PERSONAL_CARE_PRODUCTS_NEW],
)

_PH3_INDIA_RECHARGE_PROVIDERS_NEW = ["Disney+ Hotstar", "ZEE5", "SonyLIV", "JioSaavn"]
_PH3_INDIA_RECHARGE_TYPES_NEW = ["quarterly plan", "yearly plan", "premium upgrade"]
_extend_unique(
    INDIA_EXPENSE["recharge_subscription"],
    [f"{p} {t}" for p in _INDIA_RECHARGE_PROVIDERS + _PH3_INDIA_RECHARGE_PROVIDERS_NEW
     for t in _INDIA_RECHARGE_TYPES + _PH3_INDIA_RECHARGE_TYPES_NEW],
)

_PH3_INDIA_HEALTH_CONTEXTS_NEW = [
    "diabetes review", "cholesterol test", "ECG scan", "x-ray review",
    "MRI scan", "ultrasound scan", "physiotherapy session", "vaccination shot",
]
_extend_unique(INDIA_EXPENSE["health"], _PH3_INDIA_HEALTH_CONTEXTS_NEW)

_PH3_INDIA_EDU_CONTEXTS_NEW = [
    "library fine", "annual day fee", "sports day fee", "field trip fee",
    "annual function dress", "model exam fee", "olympiad fee",
    "tuition fee monthly",
]
_extend_unique(INDIA_EXPENSE["education"], _PH3_INDIA_EDU_CONTEXTS_NEW)


# Re-extend INDIA_BUY with grocery/household/personal_care/shopping pools so
# the new expense entries that are also valid buy items flow through.
# (work + education extends remain dropped per the v2 review session.)
_extend_unique(INDIA_BUY, INDIA_EXPENSE["groceries"])
_extend_unique(INDIA_BUY, INDIA_EXPENSE["household"])
_extend_unique(INDIA_BUY, INDIA_EXPENSE["personal_care"])
_extend_unique(INDIA_BUY, INDIA_EXPENSE["shopping"])


# --- Final dedup pass over the pools ---
# Per-group `INDIA_EXPENSE[X].extend(...)` and `GLOBAL_EXPENSE[X].extend(...)`
# calls above don't dedupe (unlike `_extend_unique`), so a small number of
# overlap entries can land. We also dedupe `INDIA_NAMES` / `GLOBAL_NAMES`
# because the original initial + first-expansion blocks contained a few
# pre-existing duplicates (e.g., "machan" / "machi" appeared twice).
def _dedup_inplace(target: list) -> None:
    seen: set = set()
    keep: list = []
    for v in target:
        if v not in seen:
            keep.append(v)
            seen.add(v)
    target[:] = keep


for _list in (
    INDIA_NAMES, GLOBAL_NAMES,
    INDIA_NOTE_TOPICS, GLOBAL_NOTE_TOPICS,
    INDIA_BUY, GLOBAL_BUY,
    INDIA_TODOS, INDIA_TODO_NOUNS,
    GLOBAL_TODOS, GLOBAL_TODO_NOUNS,
    INDIA_LEDGER_REASONS, GLOBAL_LEDGER_REASONS,
    SINGLE_DATE_OPTIONS,
):
    _dedup_inplace(_list)
for _group_dict in (INDIA_EXPENSE, GLOBAL_EXPENSE):
    for _items in _group_dict.values():
        _dedup_inplace(_items)
del _list, _group_dict, _items
