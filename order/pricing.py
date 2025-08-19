# Central pricing + calculation shared by templates and app

PRICING = {
    "business_cards": {
        "3.5x2": {"base": 10.00, "per_100": 8.00},
    },
    "flyers": {
        "8.5x11": {"base": 15.00, "per_100": 12.00},
        "5x7": {"base": 12.00, "per_100": 9.00},
    },
    "posters": {
        "18x24": {"base": 20.00, "per_10": 18.00},
        "24x36": {"base": 28.00, "per_10": 24.00},
    },
}

MODIFIERS = {
    "paper": {"standard": 0.0, "premium": 0.15, "ultra": 0.30},
    "color": {"full_color": 0.0, "bw": -0.10},
    "sides": {"single": 0.0, "double": 0.12},
    "turnaround": {"standard": 0.0, "rush": 0.25},
}

def calculate_price(product, size, quantity, options):
    table = PRICING.get(product, {})
    cfg = table.get(size)
    if not cfg:
        return 0.0

    price = cfg.get("base", 0.0)

    if "per_100" in cfg:
        steps = max(0, quantity // 100)
        price += steps * cfg["per_100"]
        if quantity % 100:
            price += cfg["per_100"] * 0.5
    elif "per_10" in cfg:
        steps = max(0, quantity // 10)
        price += steps * cfg["per_10"]
        if quantity % 10:
            price += cfg["per_10"] * 0.5

    mult = 1.0
    mult *= 1.0 + MODIFIERS["paper"][options.get("paper", "standard")]
    mult *= 1.0 + MODIFIERS["color"][options.get("color", "full_color")]
    mult *= 1.0 + MODIFIERS["sides"][options.get("sides", "single")]
    mult *= 1.0 + MODIFIERS["turnaround"][options.get("turnaround", "standard")]

    return round(price * mult, 2)
