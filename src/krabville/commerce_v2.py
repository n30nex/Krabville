from __future__ import annotations

import datetime as dt
import hashlib
import random
import re
import sqlite3
from collections.abc import Iterable
from typing import Any

from .db import dumps, loads


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _rng(*parts: object) -> random.Random:
    material = "|".join(str(part) for part in parts)
    return random.Random(int.from_bytes(hashlib.sha256(material.encode()).digest(), "big"))


def _goods(
    category: str,
    specialty: str,
    items: Iterable[tuple[str, int]],
    *,
    consumable: bool = False,
    perish_days: int = 0,
    durability: int = 100,
    need: str | None = None,
    restore: int = 0,
) -> list[tuple[Any, ...]]:
    return [
        (
            _slug(name), name, category, specialty, "each", price, int(consumable),
            perish_days, durability, need, restore, _slug(name),
        )
        for name, price in items
    ]


CATALOG: tuple[tuple[Any, ...], ...] = tuple(sum([
    _goods("fresh food", "grocery", [
        ("Apples", 399), ("Bananas", 279), ("Carrots", 349), ("Potatoes", 499),
        ("Tomatoes", 449), ("Lettuce", 399), ("Bread loaf", 429), ("Milk", 499),
        ("Eggs", 599), ("Cheddar", 749), ("Chicken", 1099), ("Tofu", 549),
        ("Fresh fish", 1299), ("Yogurt", 449), ("Butter", 699), ("Berries", 599),
        ("Oranges", 499), ("Mushrooms", 449), ("Soup kit", 899), ("Salad kit", 699),
    ], consumable=True, perish_days=4, need="hunger", restore=14),
    _goods("pantry", "grocery", [
        ("Rice", 799), ("Pasta", 449), ("Oats", 599), ("Flour", 649),
        ("Sugar", 449), ("Coffee", 1299), ("Tea", 799), ("Canned beans", 249),
        ("Canned soup", 329), ("Cooking oil", 1099), ("Peanut butter", 699),
        ("Crackers", 449), ("Cereal", 699), ("Tomato sauce", 349), ("Spices", 899),
        ("Emergency ration", 1199),
    ], consumable=True, perish_days=30, need="hunger", restore=10),
    _goods("prepared food", "cafe", [
        ("Hot breakfast", 1099), ("Lunch special", 1399), ("Soup and bread", 999),
        ("Coffee cup", 349), ("Tea cup", 299), ("Hot chocolate", 449),
        ("Sandwich", 899), ("Fresh pastry", 499), ("Family supper", 3499),
    ], consumable=True, perish_days=1, need="hunger", restore=20),
    _goods("hygiene", "pharmacy", [
        ("Soap", 399), ("Shampoo", 799), ("Toothpaste", 499), ("Toothbrush", 399),
        ("Deodorant", 649), ("Laundry detergent", 1299), ("Dish soap", 499),
        ("Toilet paper", 1199), ("Sanitary supplies", 899), ("Razor pack", 999),
        ("Hand sanitizer", 449), ("Skin lotion", 749),
    ], consumable=True, perish_days=60, need="hygiene", restore=18),
    _goods("medicine", "pharmacy", [
        ("First aid kit", 2499), ("Pain reliever", 899), ("Cold medicine", 1199),
        ("Allergy medicine", 1399), ("Bandages", 599), ("Thermometer", 1599),
        ("Vitamin bottle", 1099), ("Heat pack", 999), ("Ice pack", 799),
        ("Prescription refill", 1899),
    ], consumable=True, perish_days=90, need="health", restore=16),
    _goods("household", "general", [
        ("Light bulbs", 899), ("Batteries", 1299), ("Garbage bags", 999),
        ("Paper towels", 899), ("Cleaning spray", 699), ("Sponge pack", 399),
        ("Storage bin", 1499), ("Blanket", 3499), ("Pillow", 2499),
        ("Towel set", 2999), ("Cookware set", 6999), ("Dinnerware set", 4999),
        ("Kettle", 3499), ("Desk lamp", 2999), ("Extension cord", 1999),
    ], durability=80, need="comfort", restore=8),
    _goods("clothing", "outfitter", [
        ("Work shirt", 2999), ("Jeans", 4999), ("Rain jacket", 8999),
        ("Winter coat", 14999), ("Warm sweater", 5999), ("Boots", 10999),
        ("Running shoes", 8999), ("Socks", 1299), ("Gloves", 2499),
        ("Wool hat", 1999), ("Backpack", 5999), ("School uniform", 6999),
        ("Baby clothes", 3499), ("Formal outfit", 12999),
    ], durability=75, need="comfort", restore=7),
    _goods("outdoors", "outfitter", [
        ("Umbrella", 1999), ("Flashlight", 2499), ("Water bottle", 1999),
        ("Camping stove", 7999), ("Sleeping bag", 8999), ("Tent", 18999),
        ("Fishing rod", 7999), ("Life jacket", 6999), ("Binoculars", 9999),
        ("Bicycle helmet", 5999), ("Tool pouch", 3999), ("Trail map", 799),
    ], durability=82, need="safety", restore=9),
    _goods("hardware", "hardware", [
        ("Hammer", 2499), ("Screwdriver set", 3499), ("Pliers", 1999),
        ("Wrench set", 4999), ("Nails", 899), ("Screws", 899),
        ("Duct tape", 799), ("Wood glue", 999), ("Paint tin", 3999),
        ("Lumber bundle", 5999), ("Rope", 1999), ("Padlock", 2499),
        ("Multimeter", 6999), ("Soldering iron", 5999), ("Repair parts", 4499),
    ], durability=90, need="purpose", restore=7),
    _goods("electronics", "electronics", [
        ("Lagoon phone", 24999), ("Phone charger", 2499), ("Headphones", 5999),
        ("Tablet", 39999), ("Laptop", 89999), ("Portable radio", 10999),
        ("Alarm clock", 2999), ("Camera", 34999), ("USB drive", 1999),
        ("Power bank", 4999), ("Desk computer", 119999), ("Television", 69999),
    ], durability=88, need="fun", restore=10),
    _goods("books", "books", [
        ("Novel", 1899), ("Cookbook", 2499), ("Repair manual", 2999),
        ("School workbook", 1299), ("Picture book", 1499), ("Town history", 2999),
        ("Field guide", 2299), ("Notebook", 799), ("Sketchbook", 1299),
        ("Pen set", 599), ("Board game", 3999), ("Puzzle", 2499),
    ], durability=72, need="fun", restore=12),
    _goods("hobby", "hobby", [
        ("Paint set", 3999), ("Yarn bundle", 1499), ("Guitar", 19999),
        ("Garden seeds", 599), ("Model boat kit", 4999), ("Chess set", 3499),
        ("Soccer ball", 2999), ("Tennis racket", 6999), ("Baking kit", 2499),
        ("Fishing tackle", 2499), ("Craft paper", 999), ("Sewing kit", 2999),
    ], durability=70, need="fun", restore=15),
    _goods("childcare", "school", [
        ("Diapers", 2499), ("Baby formula", 2899), ("Baby bottle", 899),
        ("Stroller", 19999), ("Child car seat", 24999), ("Toy blocks", 2999),
        ("Stuffed toy", 1999), ("Lunch box", 1999), ("School supplies", 2499),
        ("Bicycle", 15999), ("Teen transit pass", 4499), ("Science kit", 3999),
    ], durability=70, need="care", restore=8),
    _goods("garden", "garden", [
        ("Potting soil", 899), ("Compost", 999), ("Plant pot", 1299),
        ("Garden shovel", 2499), ("Watering can", 1999), ("Tomato seedlings", 799),
        ("Herb seedlings", 699), ("Flower bulbs", 899), ("Fertilizer", 1299),
        ("Pruning shears", 2999),
    ], durability=65, need="purpose", restore=8),
    _goods("fresh food", "grocery", [
        ("Grapes", 599), ("Strawberries", 649), ("Cherries", 699),
        ("Watermelon", 899), ("Lemons", 449), ("Limes", 449), ("Corn", 499),
        ("Bell peppers", 599), ("Broccoli", 499), ("Garlic", 349),
        ("Onions", 399), ("Cabbage", 499), ("Cucumbers", 399),
        ("Beef steak", 1599), ("Bacon", 899), ("Fruit jam", 699),
        ("Honey", 899), ("Bagels", 599),
    ], consumable=True, perish_days=4, need="hunger", restore=14),
    _goods("snacks", "cafe", [
        ("Potato chips", 449), ("Chocolate bar", 349), ("Cookies", 499),
        ("Cake slice", 599), ("Granola bars", 649), ("Trail mix", 799),
        ("Soda", 299), ("Ice cream tub", 699), ("Popcorn", 399),
    ], consumable=True, perish_days=20, need="fun", restore=8),
    _goods("prepared food", "cafe", [
        ("Cafe latte", 499), ("Burger", 1199), ("Pizza", 1699),
        ("Sushi tray", 1899), ("Donuts", 699), ("French fries", 599),
        ("Ice cream cone", 499),
    ], consumable=True, perish_days=1, need="hunger", restore=18),
    _goods("furnishings", "general", [
        ("Dining chair", 6999), ("Side table", 8999), ("Bed frame", 24999),
        ("Wardrobe", 21999), ("Sofa", 34999), ("Floor lamp", 7999),
        ("Dresser", 18999), ("Houseplant", 2999), ("Picture frame", 2499),
        ("Standing mirror", 9999), ("Wall clock", 3999), ("Area rug", 12999),
        ("Candle", 899), ("Camping lantern", 4999), ("Broom", 2499),
        ("Mop", 2999), ("Bucket", 1999), ("Plunger", 1499),
        ("Tissue box", 399), ("Garbage can", 3999),
    ], durability=85, need="comfort", restore=10),
    _goods("accessories", "outfitter", [
        ("Scarf", 2499), ("Baseball cap", 2499), ("Sun hat", 2999),
        ("Shorts", 3499), ("Underwear", 1999), ("Necktie", 2999),
        ("Leather belt", 3999), ("Wristwatch", 7999), ("Ring", 12999),
        ("Necklace", 14999), ("Briefcase", 8999), ("Wallet", 3999),
        ("Rain boots", 7999), ("Sunglasses", 4999), ("Handbag", 8999),
    ], durability=78, need="comfort", restore=6),
    _goods("outdoors", "outfitter", [
        ("Compass", 2499), ("Multi-tool", 4999), ("Cooler", 6999),
        ("Camp frying pan", 3499), ("Tool box", 7999),
    ], durability=88, need="safety", restore=8),
    _goods("electronics", "electronics", [
        ("Home stereo", 24999), ("Walkie-talkie", 7999),
    ], durability=86, need="fun", restore=10),
    _goods("hobby", "hobby", [
        ("Basketball", 2999), ("Baseball set", 3499), ("Skateboard", 6999),
        ("Art palette", 2499), ("Crayon box", 999),
    ], durability=72, need="fun", restore=14),
    _goods("fresh food", "grocery", [
        ("Pears", 499), ("Blueberries", 649), ("Raspberries", 649),
        ("Peaches", 599), ("Plums", 549), ("Avocados", 699),
        ("Spinach", 449), ("Cauliflower", 599), ("Zucchini", 449),
        ("Celery", 399), ("Green beans", 499), ("Ground beef", 1199),
        ("Pork chops", 1299), ("Sausages", 999), ("Cream", 549),
    ], consumable=True, perish_days=4, need="hunger", restore=14),
    _goods("pantry", "grocery", [
        ("Lentils", 499), ("Chickpeas", 399), ("Quinoa", 899),
        ("Noodles", 399), ("Macaroni", 449), ("Brown sugar", 499),
        ("Maple syrup", 1299), ("Mustard", 399), ("Ketchup", 499),
        ("Mayonnaise", 599), ("Vinegar", 449), ("Salt", 299),
        ("Black pepper", 499), ("Canned tuna", 349), ("Canned corn", 299),
        ("Herbal tea", 849),
    ], consumable=True, perish_days=45, need="hunger", restore=10),
    _goods("hygiene", "pharmacy", [
        ("Conditioner", 799), ("Body wash", 699), ("Dental floss", 399),
        ("Mouthwash", 749), ("Hair brush", 899), ("Cotton swabs", 349),
        ("Sunscreen", 1099), ("Insect repellent", 999),
        ("Nail clippers", 599), ("Shaving cream", 649),
    ], consumable=True, perish_days=90, need="hygiene", restore=16),
    _goods("household", "general", [
        ("Vacuum cleaner", 12999), ("Clothes iron", 4999),
        ("Ironing board", 5999), ("Food containers", 2499),
        ("Mixing bowls", 2999), ("Frying pan", 3999),
        ("Saucepan", 4499), ("Baking tray", 2999),
        ("Coffee maker", 6999), ("Toaster", 4999),
        ("Microwave", 14999), ("Electric fan", 5999),
        ("Space heater", 8999), ("Curtains", 6999),
        ("Bed sheets", 4999), ("Duvet", 8999),
    ], durability=84, need="comfort", restore=9),
    _goods("clothing", "outfitter", [
        ("T-shirt", 1999), ("Dress shirt", 3999), ("Hoodie", 4999),
        ("Trousers", 4999), ("Sweatpants", 3999), ("Skirt", 4499),
        ("Summer dress", 6999), ("Pajamas", 3999), ("Swimsuit", 4499),
        ("Work boots", 11999), ("Slippers", 2999), ("Mittens", 2499),
        ("Rain pants", 5999), ("Thermal underwear", 3999),
        ("Blazer", 8999), ("Overalls", 6999), ("Apron", 2499),
        ("House robe", 4999), ("Sandals", 3999), ("Dress shoes", 8999),
    ], durability=76, need="comfort", restore=7),
    _goods("accessories", "outfitter", [
        ("Earrings", 4999), ("Bracelet", 5999), ("Hair ties", 799),
        ("Tote bag", 2999), ("Lunch bag", 2499), ("Card holder", 1999),
        ("Key ring", 999), ("Reading glasses", 5999),
    ], durability=78, need="comfort", restore=5),
    _goods("electronics", "electronics", [
        ("Smart speaker", 11999), ("Wi-Fi router", 9999),
        ("Printer", 19999), ("E-reader", 14999),
        ("Handheld game", 19999), ("Game console", 49999),
        ("Video game", 7999), ("Baby monitor", 12999),
    ], durability=86, need="fun", restore=10),
    _goods("books", "books", [
        ("Comic book", 999), ("Magazine", 799), ("Poetry book", 1799),
        ("Mystery novel", 1899), ("Romance novel", 1899),
        ("Science book", 2499), ("Puzzle book", 1299),
        ("Music book", 1999),
    ], durability=72, need="fun", restore=11),
    _goods("hobby", "hobby", [
        ("Playing cards", 999), ("Vinyl record", 2999),
        ("Knitting needles", 1499), ("Drum", 15999),
        ("Music keyboard", 24999), ("Microphone", 8999),
        ("Yoga mat", 3499), ("Dumbbells", 5999),
        ("Jump rope", 1499), ("Frisbee", 1499), ("Kite", 2499),
        ("Badminton set", 4999), ("Jigsaw puzzle", 2499),
        ("Clay set", 1999), ("Embroidery kit", 2499),
    ], durability=72, need="fun", restore=14),
    _goods("childcare", "school", [
        ("Crib", 24999), ("High chair", 12999), ("Pacifier", 599),
        ("Changing mat", 2999), ("Toddler cup", 899),
        ("Board book", 1299), ("Pencil case", 1499),
        ("Calculator", 2499), ("Art smock", 1999),
        ("Building bricks", 3999),
    ], durability=72, need="care", restore=8),
], []))


# Atlas positions are semantic, not catalog order. Several goods intentionally share the
# closest recognizable mini when the generated pack has no exact object.
ITEM_ASSET_INDEX = {
    "apples": 0,
    "bananas": 1,
    "carrots": 11,
    "potatoes": 12,
    "tomatoes": 13,
    "lettuce": 19,
    "bread-loaf": 21,
    "milk": 22,
    "eggs": 23,
    "cheddar": 24,
    "chicken": 28,
    "tofu": 24,
    "fresh-fish": 26,
    "yogurt": 25,
    "butter": 50,
    "berries": 5,
    "oranges": 2,
    "mushrooms": 18,
    "soup-kit": 62,
    "salad-kit": 63,
    "rice": 34,
    "pasta": 40,
    "oats": 39,
    "flour": 34,
    "sugar": 34,
    "coffee": 56,
    "tea": 58,
    "canned-beans": 41,
    "canned-soup": 42,
    "cooking-oil": 44,
    "peanut-butter": 32,
    "crackers": 54,
    "cereal": 38,
    "tomato-sauce": 47,
    "spices": 49,
    "emergency-ration": 38,
    "hot-breakfast": 39,
    "lunch-special": 65,
    "soup-and-bread": 62,
    "coffee-cup": 57,
    "tea-cup": 58,
    "hot-chocolate": 57,
    "sandwich": 59,
    "fresh-pastry": 55,
    "family-supper": 65,
    "soap": 72,
    "shampoo": 74,
    "toothpaste": 71,
    "toothbrush": 70,
    "deodorant": 75,
    "laundry-detergent": 100,
    "dish-soap": 99,
    "toilet-paper": 76,
    "sanitary-supplies": 79,
    "razor-pack": 78,
    "hand-sanitizer": 81,
    "skin-lotion": 73,
    "first-aid-kit": 87,
    "pain-reliever": 85,
    "cold-medicine": 86,
    "allergy-medicine": 96,
    "bandages": 88,
    "thermometer": 90,
    "vitamin-bottle": 97,
    "heat-pack": 89,
    "ice-pack": 92,
    "prescription-refill": 91,
    "light-bulbs": 107,
    "batteries": 110,
    "garbage-bags": 102,
    "paper-towels": 101,
    "cleaning-spray": 74,
    "sponge-pack": 98,
    "storage-bin": 119,
    "blanket": 155,
    "pillow": 114,
    "towel-set": 124,
    "cookware-set": 163,
    "dinnerware-set": 65,
    "kettle": 57,
    "desk-lamp": 117,
    "extension-cord": 111,
    "work-shirt": 131,
    "jeans": 132,
    "rain-jacket": 131,
    "winter-coat": 129,
    "warm-sweater": 130,
    "boots": 134,
    "running-shoes": 133,
    "socks": 151,
    "gloves": 128,
    "wool-hat": 126,
    "backpack": 138,
    "school-uniform": 130,
    "baby-clothes": 152,
    "formal-outfit": 144,
    "umbrella": 136,
    "flashlight": 157,
    "water-bottle": 161,
    "camping-stove": 162,
    "sleeping-bag": 155,
    "tent": 154,
    "fishing-rod": 164,
    "life-jacket": 152,
    "binoculars": 158,
    "bicycle-helmet": 140,
    "tool-pouch": 166,
    "trail-map": 159,
    "hammer": 168,
    "screwdriver-set": 169,
    "pliers": 171,
    "wrench-set": 170,
    "nails": 174,
    "screws": 175,
    "duct-tape": 173,
    "wood-glue": 99,
    "paint-tin": 187,
    "lumber-bundle": 172,
    "rope": 111,
    "padlock": 170,
    "multimeter": 176,
    "soldering-iron": 169,
    "repair-parts": 166,
    "lagoon-phone": 178,
    "phone-charger": 110,
    "headphones": 153,
    "tablet": 183,
    "laptop": 149,
    "portable-radio": 177,
    "alarm-clock": 123,
    "camera": 179,
    "usb-drive": 110,
    "power-bank": 110,
    "desk-computer": 177,
    "television": 177,
    "novel": 182,
    "cookbook": 183,
    "repair-manual": 183,
    "school-workbook": 183,
    "picture-book": 182,
    "town-history": 182,
    "field-guide": 183,
    "notebook": 185,
    "sketchbook": 185,
    "pen-set": 184,
    "board-game": 185,
    "puzzle": 187,
    "paint-set": 186,
    "yarn-bundle": 111,
    "guitar": 177,
    "garden-seeds": 119,
    "model-boat-kit": 160,
    "chess-set": 185,
    "soccer-ball": 189,
    "tennis-racket": 191,
    "baking-kit": 55,
    "fishing-tackle": 166,
    "craft-paper": 185,
    "sewing-kit": 171,
    "diapers": 79,
    "baby-formula": 22,
    "baby-bottle": 22,
    "stroller": 112,
    "child-car-seat": 112,
    "toy-blocks": 186,
    "stuffed-toy": 125,
    "lunch-box": 167,
    "school-supplies": 186,
    "bicycle": 192,
    "teen-transit-pass": 183,
    "science-kit": 166,
    "potting-soil": 34,
    "compost": 42,
    "plant-pot": 120,
    "garden-shovel": 168,
    "watering-can": 105,
    "tomato-seedlings": 119,
    "herb-seedlings": 120,
    "flower-bulbs": 107,
    "fertilizer": 34,
    "pruning-shears": 171,
    "grapes": 3,
    "strawberries": 4,
    "cherries": 6,
    "watermelon": 7,
    "lemons": 8,
    "limes": 9,
    "corn": 10,
    "bell-peppers": 14,
    "broccoli": 15,
    "garlic": 16,
    "onions": 17,
    "cabbage": 19,
    "cucumbers": 20,
    "beef-steak": 29,
    "bacon": 30,
    "fruit-jam": 31,
    "honey": 33,
    "bagels": 37,
    "potato-chips": 52,
    "chocolate-bar": 53,
    "cookies": 54,
    "cake-slice": 55,
    "granola-bars": 40,
    "trail-mix": 38,
    "soda": 67,
    "ice-cream-tub": 69,
    "popcorn": 38,
    "cafe-latte": 57,
    "burger": 60,
    "pizza": 61,
    "sushi-tray": 64,
    "donuts": 66,
    "french-fries": 68,
    "ice-cream-cone": 69,
    "dining-chair": 112,
    "side-table": 113,
    "bed-frame": 114,
    "wardrobe": 115,
    "sofa": 116,
    "floor-lamp": 117,
    "dresser": 118,
    "houseplant": 120,
    "picture-frame": 121,
    "standing-mirror": 122,
    "wall-clock": 123,
    "area-rug": 124,
    "candle": 108,
    "camping-lantern": 109,
    "broom": 103,
    "mop": 104,
    "bucket": 105,
    "plunger": 106,
    "tissue-box": 77,
    "garbage-can": 102,
    "scarf": 127,
    "baseball-cap": 140,
    "sun-hat": 141,
    "shorts": 142,
    "underwear": 143,
    "necktie": 144,
    "leather-belt": 145,
    "wristwatch": 146,
    "ring": 147,
    "necklace": 148,
    "briefcase": 149,
    "wallet": 150,
    "rain-boots": 135,
    "sunglasses": 137,
    "handbag": 139,
    "compass": 159,
    "multi-tool": 160,
    "cooler": 167,
    "camp-frying-pan": 163,
    "tool-box": 166,
    "home-stereo": 177,
    "walkie-talkie": 178,
    "basketball": 188,
    "baseball-set": 190,
    "skateboard": 192,
    "art-palette": 187,
    "crayon-box": 186,
}

ITEM_ASSET_ALIASES = {
    "pears": "apples", "blueberries": "berries", "raspberries": "berries",
    "peaches": "oranges", "plums": "cherries", "avocados": "limes",
    "spinach": "lettuce", "cauliflower": "broccoli", "zucchini": "cucumbers",
    "celery": "cucumbers", "green-beans": "broccoli",
    "ground-beef": "beef-steak", "pork-chops": "beef-steak", "sausages": "bacon",
    "cream": "milk", "lentils": "rice", "chickpeas": "canned-beans",
    "quinoa": "oats", "noodles": "pasta", "macaroni": "pasta",
    "brown-sugar": "sugar", "maple-syrup": "honey", "mustard": "tomato-sauce",
    "ketchup": "tomato-sauce", "mayonnaise": "yogurt", "vinegar": "cooking-oil",
    "salt": "spices", "black-pepper": "spices", "canned-tuna": "canned-soup",
    "canned-corn": "canned-beans", "herbal-tea": "tea",
    "conditioner": "shampoo", "body-wash": "soap", "dental-floss": "toothbrush",
    "mouthwash": "toothpaste", "hair-brush": "toothbrush", "cotton-swabs": "bandages",
    "sunscreen": "skin-lotion", "insect-repellent": "cleaning-spray",
    "nail-clippers": "pruning-shears", "shaving-cream": "skin-lotion",
    "vacuum-cleaner": "broom", "clothes-iron": "kettle", "ironing-board": "side-table",
    "food-containers": "storage-bin", "mixing-bowls": "dinnerware-set",
    "frying-pan": "camp-frying-pan", "saucepan": "cookware-set", "baking-tray": "cookware-set",
    "coffee-maker": "kettle", "toaster": "camping-stove", "microwave": "camping-stove",
    "electric-fan": "floor-lamp", "space-heater": "camping-stove", "curtains": "blanket",
    "bed-sheets": "blanket", "duvet": "blanket", "t-shirt": "work-shirt",
    "dress-shirt": "work-shirt", "hoodie": "warm-sweater", "trousers": "jeans",
    "sweatpants": "jeans", "skirt": "shorts", "summer-dress": "formal-outfit",
    "pajamas": "baby-clothes", "swimsuit": "shorts", "work-boots": "boots",
    "slippers": "running-shoes", "mittens": "gloves", "rain-pants": "jeans",
    "thermal-underwear": "underwear", "blazer": "formal-outfit", "overalls": "work-shirt",
    "apron": "work-shirt", "house-robe": "warm-sweater", "sandals": "running-shoes",
    "dress-shoes": "boots", "earrings": "ring", "bracelet": "wristwatch",
    "hair-ties": "necklace", "tote-bag": "handbag", "lunch-bag": "cooler",
    "card-holder": "wallet", "key-ring": "ring", "reading-glasses": "sunglasses",
    "smart-speaker": "home-stereo", "wi-fi-router": "portable-radio", "printer": "desk-computer",
    "e-reader": "tablet", "handheld-game": "lagoon-phone", "game-console": "television",
    "video-game": "usb-drive", "baby-monitor": "walkie-talkie", "comic-book": "picture-book",
    "magazine": "picture-book", "poetry-book": "novel", "mystery-novel": "novel",
    "romance-novel": "novel", "science-book": "field-guide", "puzzle-book": "school-workbook",
    "music-book": "notebook", "playing-cards": "board-game", "vinyl-record": "home-stereo",
    "knitting-needles": "sewing-kit", "drum": "guitar", "music-keyboard": "guitar",
    "microphone": "walkie-talkie", "yoga-mat": "area-rug", "dumbbells": "multi-tool",
    "jump-rope": "rope", "frisbee": "basketball", "kite": "toy-blocks",
    "badminton-set": "tennis-racket", "jigsaw-puzzle": "puzzle", "clay-set": "paint-set",
    "embroidery-kit": "sewing-kit", "crib": "bed-frame", "high-chair": "dining-chair",
    "pacifier": "baby-bottle", "changing-mat": "blanket", "toddler-cup": "baby-bottle",
    "board-book": "picture-book", "pencil-case": "school-supplies", "calculator": "science-kit",
    "art-smock": "school-uniform", "building-bricks": "toy-blocks",
}
ITEM_ASSET_INDEX.update({sku: ITEM_ASSET_INDEX[source] for sku, source in ITEM_ASSET_ALIASES.items()})


def item_asset_index(asset_key: str) -> int:
    return ITEM_ASSET_INDEX.get(asset_key, 195)


INTERIOR_VARIANTS = {
    "Anchor House": 0,
    "Rose House": 1,
    "Birch House": 2,
    "Lantern House": 3,
    "Post House": 4,
    "Willow House": 5,
    "Blue Kettle Cafe": 6,
    "Community House": 7,
    "Dockside Studio": 8,
    "Harbour Library": 9,
    "Harbour Works": 10,
    "Krabville Credit Union": 11,
    "Krabville School": 12,
    "Lagoon Health Centre": 13,
    "Lagoon General Store": 14,
    "Tideway Gardens": 15,
    "Cedar Cottage": 16,
    "Harbour Pharmacy": 17,
    "Tidepool House": 18,
    "Tideway Outfitters": 19,
    "Harbour Shelter": 20,
    "Maple Row House": 21,
    "Lagoon Ferry": 22,
    "North Dock Flat": 23,
    "Owen's Care Service": 24,
}


SHOP_DEFINITIONS = (
    ("lagoon-general-store", "Lagoon General Store", "general", "Post Office", "shop", 14),
    ("harbour-pharmacy", "Harbour Pharmacy", "pharmacy", "Lagoon Clinic", "shop", 17),
    ("tideway-outfitters", "Tideway Outfitters", "outfitter", "Ferry Dock", "shop", 19),
    ("lagoon-ferry", "Lagoon Ferry", "shipping", "Ferry Dock", "office", 22),
)

SPECIALTY_BUSINESSES = {
    "grocery": ("Lagoon General Store",),
    "cafe": ("Blue Kettle Cafe", "Lagoon General Store"),
    "pharmacy": ("Harbour Pharmacy", "Lagoon Health Centre"),
    "general": ("Lagoon General Store",),
    "outfitter": ("Tideway Outfitters",),
    "hardware": ("Harbour Works", "Lagoon General Store"),
    "electronics": ("Signal House", "Dockside Studio"),
    "books": ("Harbour Library", "Lagoon General Store"),
    "hobby": ("Dockside Studio", "Lagoon General Store"),
    "school": ("Krabville School", "Lagoon General Store"),
    "garden": ("Tideway Gardens", "Lagoon General Store"),
}


def _account_balance(connection: sqlite3.Connection, account_id: int) -> int:
    row = connection.execute(
        """
        SELECT a.opening_balance_cents + COALESCE(SUM(CASE WHEN t.status='posted' THEN e.amount_cents ELSE 0 END),0)
        FROM financial_accounts a LEFT JOIN transaction_entries e ON e.account_id=a.id
        LEFT JOIN financial_transactions t ON t.id=e.transaction_id
        WHERE a.id=? GROUP BY a.id
        """,
        (account_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def _ensure_shop(
    connection: sqlite3.Connection,
    slug: str,
    name: str,
    industry: str,
    location: str,
    property_type: str,
    interior_variant: int,
) -> int:
    business = connection.execute(
        "SELECT id FROM businesses WHERE slug=? OR name=? ORDER BY name=? DESC LIMIT 1",
        (slug, name, name),
    ).fetchone()
    if business:
        return int(business[0])
    property_id = int(connection.execute(
        """
        INSERT INTO properties(
          slug,name,property_type,address,exterior_key,interior_key,resident_capacity,
          business_capacity,market_value_cents,status,created_tick,map_location,interior_variant
        ) VALUES(?,?,?,?,?,'shop',0,12,32000000,'occupied',0,?,?) RETURNING id
        """,
        (f"property-{slug}", name, property_type, location, slug, location, interior_variant),
    ).fetchone()[0])
    business_id = int(connection.execute(
        """
        INSERT INTO businesses(slug,name,industry,property_id,status,valuation_cents,reputation,created_at)
        VALUES(?,?,?,?,'active',14500000,55,?) RETURNING id
        """,
        (slug, name, industry, property_id, _now()),
    ).fetchone()[0])
    connection.execute(
        "INSERT INTO financial_accounts(business_id,name,account_type,opening_balance_cents,opened_tick) VALUES(?,'Operating','business',2500000,0)",
        (business_id,),
    )
    return business_id


def seed_commerce(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO item_catalog(
          sku,name,category,specialty,unit,base_price_cents,consumable,perish_days,
          durability,need_key,need_restore,asset_key
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        CATALOG,
    )
    if not connection.execute("SELECT 1 FROM resident_identities WHERE generation_seed LIKE 'v2:%' LIMIT 1").fetchone():
        return
    connection.execute(
        """
        UPDATE properties SET
          name=COALESCE((
            SELECT r.home FROM property_occupancy po
            JOIN household_members hm ON hm.household_id=po.household_id
            JOIN residents r ON r.id=hm.resident_id
            WHERE po.property_id=properties.id AND po.ended_season_id IS NULL ORDER BY hm.id LIMIT 1
          ),name),
          map_location=COALESCE((
            SELECT r.home FROM property_occupancy po
            JOIN household_members hm ON hm.household_id=po.household_id
            JOIN residents r ON r.id=hm.resident_id
            WHERE po.property_id=properties.id AND po.ended_season_id IS NULL ORDER BY hm.id LIMIT 1
          ),NULLIF(map_location,''),address),
          interior_variant=CASE WHEN interior_variant=0 THEN id-1 ELSE interior_variant END
        WHERE property_type IN ('house','apartment')
        """
    )
    connection.execute(
        """
        UPDATE properties SET map_location=CASE WHEN map_location='' THEN address ELSE map_location END,
          interior_variant=CASE WHEN interior_variant=0 THEN id-1 ELSE interior_variant END
        WHERE property_type NOT IN ('house','apartment')
        """
    )
    for definition in SHOP_DEFINITIONS:
        _ensure_shop(connection, *definition)
    connection.execute(
        """
        INSERT OR IGNORE INTO properties(
          slug,name,property_type,address,exterior_key,interior_key,resident_capacity,
          business_capacity,market_value_cents,status,created_tick,map_location,interior_variant
        ) VALUES('harbour-shelter','Harbour Shelter','shelter','14 Safe Harbour Lane',
          'harbour-shelter','shelter',12,0,9800000,'available',0,'Harbour Shelter',20)
        """
    )
    connection.executemany(
        "UPDATE properties SET interior_variant=? WHERE name=?",
        ((variant, name) for name, variant in INTERIOR_VARIANTS.items()),
    )

    season = connection.execute("SELECT id,current_tick FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    season_id = int(season["id"]) if season else None
    tick = int(season["current_tick"]) if season else 0
    for resident in connection.execute(
        """
        SELECT r.id,l.current_stage FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.alive=1 AND l.current_stage IN ('teen','adult','senior') ORDER BY r.id
        """
    ):
        number = f"+1 226-555-{100 + int(resident['id']):04d}"
        connection.execute(
            "INSERT OR IGNORE INTO resident_phones(resident_id,phone_number,issued_season_id,issued_tick) VALUES(?,?,?,?)",
            (resident["id"], number, season_id, tick),
        )

    businesses = {str(row["name"]): int(row["id"]) for row in connection.execute("SELECT id,name FROM businesses WHERE status='active'")}
    for item in connection.execute("SELECT * FROM item_catalog WHERE active=1 ORDER BY id"):
        names = ["Lagoon General Store", *SPECIALTY_BUSINESSES.get(str(item["specialty"]), ())]
        for name in dict.fromkeys(names):
            business_id = businesses.get(name)
            if not business_id:
                continue
            specialist = name != "Lagoon General Store"
            target = 12 if specialist else 18
            price = max(25, round(int(item["base_price_cents"]) * (0.98 if specialist else 1.06)))
            connection.execute(
                """
                INSERT OR IGNORE INTO business_inventory(
                  business_id,item_id,quantity,price_cents,reorder_point,target_stock,last_restock_tick
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (business_id, item["id"], target, price, 3, target, tick),
            )

    starter_home = ("rice", "pasta", "oats", "canned-beans", "soap", "toothpaste", "toilet-paper", "laundry-detergent", "first-aid-kit", "blanket", "batteries")
    for household in connection.execute("SELECT id FROM households WHERE status='active'"):
        for sku in starter_home:
            item = connection.execute("SELECT id,consumable FROM item_catalog WHERE sku=?", (sku,)).fetchone()
            if item:
                connection.execute(
                    "INSERT OR IGNORE INTO household_inventory(household_id,item_id,quantity,acquired_tick) VALUES(?,?,?,0)",
                    (household["id"], item["id"], 4 if item["consumable"] else 1),
                )
    for phone in connection.execute("SELECT resident_id FROM resident_phones WHERE active=1"):
        for sku in ("lagoon-phone", "phone-charger", "water-bottle"):
            item = connection.execute("SELECT id FROM item_catalog WHERE sku=?", (sku,)).fetchone()
            if item:
                connection.execute(
                    "INSERT OR IGNORE INTO resident_inventory(resident_id,item_id,quantity,acquired_tick) VALUES(?,?,1,0)",
                    (phone["resident_id"], item["id"]),
                )
    for resident in connection.execute(
        """
        SELECT r.id,l.current_stage FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.alive=1 ORDER BY r.id
        """
    ):
        stage = str(resident["current_stage"])
        wardrobe = (
            ("baby-clothes", "blanket", "stuffed-toy")
            if stage == "baby"
            else ("school-uniform", "warm-sweater", "socks", "running-shoes", "rain-jacket", "backpack")
            if stage == "child"
            else ("work-shirt", "jeans", "socks", "running-shoes", "rain-jacket", "winter-coat", "backpack")
        )
        for sku in wardrobe:
            item = connection.execute("SELECT id FROM item_catalog WHERE sku=?", (sku,)).fetchone()
            if item:
                connection.execute(
                    "INSERT OR IGNORE INTO resident_inventory(resident_id,item_id,quantity,acquired_tick) VALUES(?,?,1,0)",
                    (resident["id"], item["id"]),
                )


def _post_purchase(
    connection: sqlite3.Connection,
    season_id: int,
    tick: int,
    day: int,
    buyer_account: int,
    business_id: int,
    item: sqlite3.Row,
    price: int,
    buyer_kind: str,
    buyer_id: int,
    sequence: int,
) -> bool:
    if _account_balance(connection, buyer_account) < price:
        return False
    seller = connection.execute(
        "SELECT id FROM financial_accounts WHERE business_id=? AND name='Operating' AND status='open'",
        (business_id,),
    ).fetchone()
    if not seller:
        return False
    key = f"purchase:{day}:{buyer_kind}:{buyer_id}:{item['id']}:{sequence}"
    transaction = connection.execute(
        "SELECT id FROM financial_transactions WHERE season_id=? AND external_key=?",
        (season_id, key),
    ).fetchone()
    if transaction:
        return False
    transaction_id = int(connection.execute(
        """
        INSERT INTO financial_transactions(season_id,tick,category,description,status,external_key,created_at,posted_at)
        VALUES(?,?,'retail_purchase',?,'posted',?,?,?) RETURNING id
        """,
        (season_id, tick, f"Purchase of {item['name']}", key, _now(), _now()),
    ).fetchone()[0])
    connection.executemany(
        "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
        ((transaction_id, buyer_account, -price, "retail purchase"), (transaction_id, int(seller[0]), price, "retail sale")),
    )
    connection.execute(
        "UPDATE business_inventory SET quantity=quantity-1 WHERE business_id=? AND item_id=? AND quantity>=1",
        (business_id, item["id"]),
    )
    table = "household_inventory" if buyer_kind == "household" else "resident_inventory"
    owner_column = "household_id" if buyer_kind == "household" else "resident_id"
    connection.execute(
        f"""
        INSERT INTO {table}({owner_column},item_id,quantity,acquired_tick) VALUES(?,?,1,?)
        ON CONFLICT({owner_column},item_id) DO UPDATE SET quantity=quantity+1,acquired_tick=excluded.acquired_tick
        """,
        (buyer_id, item["id"], tick),
    )
    connection.execute(
        """
        INSERT INTO inventory_movements(
          season_id,tick,item_id,quantity,movement_type,from_kind,from_id,to_kind,to_id,unit_price_cents,note,created_at
        ) VALUES(?,?,?,1,'purchase','business',?,?,?,?,'retail purchase',?)
        """,
        (season_id, tick, item["id"], business_id, buyer_kind, buyer_id, price, _now()),
    )
    return True


def _restock(connection: sqlite3.Connection, season_id: int, day: int, tick: int) -> int:
    count = 0
    for row in connection.execute(
        """
        SELECT bi.*,i.base_price_cents FROM business_inventory bi
        JOIN item_catalog i ON i.id=bi.item_id WHERE bi.quantity<=bi.reorder_point
        """
    ):
        amount = max(0, round(float(row["target_stock"]) - float(row["quantity"])))
        if amount <= 0:
            continue
        buyer = connection.execute(
            "SELECT id FROM financial_accounts WHERE business_id=? AND name='Operating' AND status='open'",
            (row["business_id"],),
        ).fetchone()
        supplier = connection.execute(
            """
            SELECT a.id FROM financial_accounts a JOIN businesses b ON b.id=a.business_id
            WHERE b.name='Lagoon Ferry' AND a.name='Operating' AND a.status='open'
            """
        ).fetchone()
        if not buyer or not supplier:
            continue
        wholesale = max(10, round(int(row["base_price_cents"]) * 0.62))
        delivered = min(amount, _account_balance(connection, int(buyer[0])) // wholesale)
        if delivered <= 0:
            continue
        shortage = max(0.0, 1 - float(row["quantity"]) / max(1.0, float(row["target_stock"])))
        noise = _rng(season_id, day, row["business_id"], row["item_id"]).uniform(-0.025, 0.035)
        price = max(25, round(int(row["base_price_cents"]) * (1 + shortage * 0.12 + noise)))
        transaction_id = int(connection.execute(
            """
            INSERT INTO financial_transactions(
              season_id,tick,category,description,status,external_key,created_at,posted_at
            ) VALUES(?,?,'wholesale_restock','Daily ferry stock delivery','posted',?,?,?) RETURNING id
            """,
            (season_id, tick, f"restock:{day}:{row['business_id']}:{row['item_id']}", _now(), _now()),
        ).fetchone()[0])
        total = delivered * wholesale
        connection.executemany(
            "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
            ((transaction_id, int(buyer[0]), -total, "wholesale stock"), (transaction_id, int(supplier[0]), total, "ferry delivery")),
        )
        connection.execute(
            "UPDATE business_inventory SET quantity=?,price_cents=?,last_restock_tick=? WHERE business_id=? AND item_id=?",
            (float(row["quantity"]) + delivered, price, tick, row["business_id"], row["item_id"]),
        )
        connection.execute(
            """
            INSERT INTO inventory_movements(
              season_id,tick,item_id,quantity,movement_type,from_kind,to_kind,to_id,unit_price_cents,note,created_at
            ) VALUES(?,?,?,?,'restock','ferry','business',?,?,'daily ferry delivery',?)
            """,
            (season_id, tick, row["item_id"], delivered, row["business_id"], wholesale, _now()),
        )
        count += 1
    return count


def _spoil_and_wear(connection: sqlite3.Connection, season_id: int, day: int, tick: int) -> dict[str, int]:
    result = {"spoiled": 0, "wornOut": 0}
    for table, owner_column, owner_kind in (
        ("resident_inventory", "resident_id", "resident"),
        ("household_inventory", "household_id", "household"),
    ):
        rows = list(connection.execute(
            f"""
            SELECT inv.{owner_column} owner_id,inv.item_id,inv.quantity,inv.condition_score,
                   inv.acquired_tick,i.perish_days,i.durability,i.consumable
            FROM {table} inv JOIN item_catalog i ON i.id=inv.item_id
            WHERE inv.quantity>0
            """
        ))
        for row in rows:
            if int(row["perish_days"]) and tick - int(row["acquired_tick"]) >= int(row["perish_days"]) * 288:
                quantity = max(0.25, round(float(row["quantity"]) * 0.35, 2))
                quantity = min(quantity, float(row["quantity"]))
                connection.execute(
                    f"UPDATE {table} SET quantity=MAX(0,quantity-?),acquired_tick=? WHERE {owner_column}=? AND item_id=?",
                    (quantity, tick, row["owner_id"], row["item_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO inventory_movements(
                      season_id,tick,item_id,quantity,movement_type,from_kind,from_id,to_kind,note,created_at
                    ) VALUES(?,?,?,?,'spoil',?,?,'waste','expired stock',?)
                    """,
                    (season_id, tick, row["item_id"], quantity, owner_kind, row["owner_id"], _now()),
                )
                result["spoiled"] += 1
            elif not int(row["consumable"]) and _rng(season_id, day, owner_kind, row["owner_id"], row["item_id"], "wear").random() < 0.18:
                loss = max(1, round((101 - int(row["durability"])) / 12))
                condition = max(0, int(row["condition_score"]) - loss)
                connection.execute(
                    f"UPDATE {table} SET condition_score=?,quantity=CASE WHEN ?=0 THEN MAX(0,quantity-1) ELSE quantity END WHERE {owner_column}=? AND item_id=?",
                    (100 if condition == 0 else condition, condition, row["owner_id"], row["item_id"]),
                )
                if condition == 0:
                    connection.execute(
                        """
                        INSERT INTO inventory_movements(
                          season_id,tick,item_id,quantity,movement_type,from_kind,from_id,to_kind,note,created_at
                        ) VALUES(?,?,?,1,'wear',?,?,'waste','worn out through ordinary use',?)
                        """,
                        (season_id, tick, row["item_id"], owner_kind, row["owner_id"], _now()),
                    )
                    result["wornOut"] += 1
    return result


def _consume_home_stock(connection: sqlite3.Connection, season_id: int, tick: int) -> int:
    consumed = 0
    for household in connection.execute(
        """
        SELECT h.id,COUNT(hm.resident_id) members FROM households h
        JOIN household_members hm ON hm.household_id=h.id AND hm.ended_season_id IS NULL
        JOIN resident_lifecycle l ON l.resident_id=hm.resident_id AND l.alive=1
        WHERE h.status='active' GROUP BY h.id
        """
    ):
        amount_left = max(1.0, float(household["members"]) * 0.65)
        rows = list(connection.execute(
            """
            SELECT hi.item_id,hi.quantity,i.name FROM household_inventory hi
            JOIN item_catalog i ON i.id=hi.item_id
            WHERE hi.household_id=? AND i.category IN ('fresh food','pantry','prepared food','snacks') AND hi.quantity>0
            ORDER BY i.perish_days,hi.acquired_tick,i.id
            """,
            (household["id"],),
        ))
        for row in rows:
            amount = min(float(row["quantity"]), amount_left)
            if amount <= 0:
                continue
            connection.execute(
                "UPDATE household_inventory SET quantity=quantity-? WHERE household_id=? AND item_id=?",
                (amount, household["id"], row["item_id"]),
            )
            connection.execute(
                """
                INSERT INTO inventory_movements(
                  season_id,tick,item_id,quantity,movement_type,from_kind,from_id,to_kind,note,created_at
                ) VALUES(?,?,?,?,'consume','household',?,'waste','meals and packed lunches',?)
                """,
                (season_id, tick, row["item_id"], amount, household["id"], _now()),
            )
            consumed += 1
            amount_left -= amount
            if amount_left <= 0:
                break
    return consumed


def _shopping_requirements(connection: sqlite3.Connection, household_id: int, season_id: int) -> list[str]:
    members = int(connection.execute(
        "SELECT COUNT(*) FROM household_members WHERE household_id=? AND ended_season_id IS NULL",
        (household_id,),
    ).fetchone()[0])
    requirements = [
        ("fresh food", max(4, members * 3)),
        ("pantry", max(5, members * 2)),
        ("snacks", max(2, members)),
        ("hygiene", 3),
        ("household", 2),
        ("furnishings", 2),
    ]
    if connection.execute(
        """
        SELECT 1 FROM household_members hm JOIN resident_lifecycle l ON l.resident_id=hm.resident_id
        WHERE hm.household_id=? AND hm.ended_season_id IS NULL AND l.current_stage IN ('baby','child') LIMIT 1
        """,
        (household_id,),
    ).fetchone():
        requirements.append(("childcare", 2))
    health = connection.execute(
        """
        SELECT MIN(n.satisfaction) FROM household_members hm JOIN resident_needs n ON n.resident_id=hm.resident_id
        WHERE hm.household_id=? AND hm.ended_season_id IS NULL AND n.season_id=? AND n.need_key='health'
        """,
        (household_id, season_id),
    ).fetchone()[0]
    if health is not None and int(health) < 55:
        requirements.append(("medicine", 2))
    missing = []
    for category, target in requirements:
        stock = float(connection.execute(
            """
            SELECT COALESCE(SUM(hi.quantity),0) FROM household_inventory hi
            JOIN item_catalog i ON i.id=hi.item_id WHERE hi.household_id=? AND i.category=?
            """,
            (household_id, category),
        ).fetchone()[0])
        if stock < target:
            missing.append(category)
    return missing


PERSONAL_NEED_CATEGORIES = {
    "hunger": ("prepared food", "snacks"),
    "hygiene": ("hygiene",),
    "health": ("medicine",),
    "comfort": ("clothing", "accessories", "household"),
    "safety": ("outdoors", "hardware"),
    "fun": ("hobby", "books", "electronics", "snacks"),
    "social": ("hobby", "accessories", "prepared food"),
    "belonging": ("hobby", "books", "accessories"),
    "privacy": ("electronics", "books", "outdoors"),
    "purpose": ("books", "hobby", "garden", "hardware"),
    "autonomy": ("electronics", "outdoors", "accessories"),
}

PERSONAL_CATEGORY_TARGETS = {
    "clothing": 7,
    "accessories": 3,
    "electronics": 3,
    "books": 3,
    "hobby": 3,
    "outdoors": 2,
    "hardware": 2,
    "garden": 2,
}


def _use_personal_goods(connection: sqlite3.Connection, season_id: int, tick: int) -> int:
    """Use one useful owned item per resident and feed its benefit back into needs."""

    used = 0
    for resident in connection.execute(
        """
        SELECT r.id FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
        ORDER BY r.id
        """
    ):
        need = connection.execute(
            """
            SELECT need_key,satisfaction FROM resident_needs
            WHERE season_id=? AND resident_id=? AND need_key NOT IN ('energy','financial_security')
            ORDER BY satisfaction,need_key LIMIT 1
            """,
            (season_id, resident["id"]),
        ).fetchone()
        if not need or int(need["satisfaction"]) >= 82:
            continue
        item = connection.execute(
            """
            SELECT i.id,i.name,i.need_key,i.need_restore,i.consumable,ri.quantity,ri.condition_score
            FROM resident_inventory ri JOIN item_catalog i ON i.id=ri.item_id
            WHERE ri.resident_id=? AND ri.quantity>0 AND i.need_key=? AND i.need_restore>0
            ORDER BY i.consumable DESC,i.need_restore DESC,ri.acquired_tick,i.id LIMIT 1
            """,
            (resident["id"], need["need_key"]),
        ).fetchone()
        if not item:
            continue
        restored = min(100, int(need["satisfaction"]) + int(item["need_restore"]))
        connection.execute(
            """
            UPDATE resident_needs SET satisfaction=?,trend=?,updated_tick=?
            WHERE season_id=? AND resident_id=? AND need_key=?
            """,
            (restored, restored - int(need["satisfaction"]), tick, season_id, resident["id"], need["need_key"]),
        )
        state = connection.execute(
            "SELECT needs_json FROM resident_state WHERE season_id=? AND resident_id=?",
            (season_id, resident["id"]),
        ).fetchone()
        if state:
            needs = loads(state["needs_json"], {})
            needs[str(need["need_key"])] = restored
            connection.execute(
                "UPDATE resident_state SET needs_json=? WHERE season_id=? AND resident_id=?",
                (dumps(needs), season_id, resident["id"]),
            )
        if int(item["consumable"]):
            connection.execute(
                "UPDATE resident_inventory SET quantity=MAX(0,quantity-1) WHERE resident_id=? AND item_id=?",
                (resident["id"], item["id"]),
            )
            connection.execute(
                """
                INSERT INTO inventory_movements(
                  season_id,tick,item_id,quantity,movement_type,from_kind,from_id,to_kind,note,created_at
                ) VALUES(?,?,?,1,'consume','resident',?,'waste',?,?)
                """,
                (season_id, tick, item["id"], resident["id"], f"Used {item['name']} for {need['need_key']}", _now()),
            )
        else:
            connection.execute(
                "UPDATE resident_inventory SET condition_score=MAX(1,condition_score-1) WHERE resident_id=? AND item_id=?",
                (resident["id"], item["id"]),
            )
        used += 1
    return used


def _shop_for_personal_needs(
    connection: sqlite3.Connection, season_id: int, day: int, tick: int
) -> int:
    purchases = 0
    placeholders = ",".join("?" for _ in PERSONAL_NEED_CATEGORIES)
    for resident in connection.execute(
        """
        SELECT r.id,a.id account_id FROM residents r
        JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
          AND l.current_stage IN ('teen','adult','senior')
        JOIN financial_accounts a ON a.resident_id=r.id
          AND a.name='Personal chequing' AND a.status='open'
        ORDER BY r.id
        """
    ):
        needs = list(connection.execute(
            f"""
            SELECT need_key,satisfaction FROM resident_needs
            WHERE season_id=? AND resident_id=? AND need_key IN ({placeholders})
            ORDER BY satisfaction,need_key
            """,
            (season_id, resident["id"], *PERSONAL_NEED_CATEGORIES),
        ))
        if not needs:
            continue
        lowest = int(needs[0]["satisfaction"])
        chooser = _rng(season_id, day, resident["id"], "personal-shopping")
        if chooser.random() > min(0.92, 0.28 + (100 - lowest) / 100):
            continue
        balance = _account_balance(connection, int(resident["account_id"]))
        spendable = max(0, balance - 25_000)
        if spendable < 299:
            continue
        bought = False
        for need in needs[:5]:
            for category in PERSONAL_NEED_CATEGORIES.get(str(need["need_key"]), ()):
                target = PERSONAL_CATEGORY_TARGETS.get(category)
                if target is not None:
                    owned = float(connection.execute(
                        """
                        SELECT COALESCE(SUM(ri.quantity),0) FROM resident_inventory ri
                        JOIN item_catalog i ON i.id=ri.item_id
                        WHERE ri.resident_id=? AND i.category=? AND ri.quantity>0
                        """,
                        (resident["id"], category),
                    ).fetchone()[0])
                    if owned >= target:
                        continue
                options = list(connection.execute(
                    """
                    SELECT i.*,bi.business_id,bi.price_cents,bi.quantity FROM item_catalog i
                    JOIN business_inventory bi ON bi.item_id=i.id
                    WHERE i.category=? AND bi.quantity>=1 AND bi.price_cents<=?
                      AND (i.consumable=1 OR NOT EXISTS (
                        SELECT 1 FROM resident_inventory ri
                        WHERE ri.resident_id=? AND ri.item_id=i.id AND ri.quantity>0
                      ))
                    ORDER BY bi.price_cents,i.id
                    """,
                    (category, min(spendable, max(2_500, balance // 8)), resident["id"]),
                ))
                if not options:
                    continue
                item = options[chooser.randrange(min(5, len(options)))]
                if _post_purchase(
                    connection, season_id, tick, day, int(resident["account_id"]),
                    int(item["business_id"]), item, int(item["price_cents"]),
                    "resident", int(resident["id"]), 100 + purchases,
                ):
                    purchases += 1
                    bought = True
                    break
            if bought:
                break
    return purchases


def _shop(connection: sqlite3.Connection, season_id: int, day: int, tick: int) -> tuple[int, list[tuple[int, str]]]:
    purchases = 0
    shortfalls: list[tuple[int, str]] = []
    for household in connection.execute("SELECT id FROM households WHERE status='active' ORDER BY id"):
        buyer = connection.execute(
            """
            SELECT r.id,a.id account_id FROM household_members hm
            JOIN residents r ON r.id=hm.resident_id
            JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1 AND l.current_stage IN ('adult','senior')
            JOIN financial_accounts a ON a.resident_id=r.id AND a.name='Personal chequing' AND a.status='open'
            WHERE hm.household_id=? AND hm.ended_season_id IS NULL
            ORDER BY hm.financially_responsible DESC,r.id LIMIT 1
            """,
            (household["id"],),
        ).fetchone()
        if not buyer:
            continue
        requirements = _shopping_requirements(connection, int(household["id"]), season_id)
        for sequence, category in enumerate(requirements[:4]):
            options = list(connection.execute(
                """
                SELECT i.*,bi.business_id,bi.price_cents,bi.quantity FROM item_catalog i
                JOIN business_inventory bi ON bi.item_id=i.id
                WHERE i.category=? AND bi.quantity>=1
                ORDER BY bi.price_cents,i.id
                """,
                (category,),
            ))
            if not options:
                shortfalls.append((int(household["id"]), category))
                continue
            affordable = [item for item in options if _account_balance(connection, int(buyer["account_id"])) >= int(item["price_cents"])]
            if not affordable:
                shortfalls.append((int(household["id"]), category))
                continue
            item = affordable[_rng(season_id, day, household["id"], category).randrange(min(3, len(affordable)))]
            if _post_purchase(
                connection, season_id, tick, day, int(buyer["account_id"]), int(item["business_id"]), item,
                int(item["price_cents"]), "household", int(household["id"]), sequence,
            ):
                purchases += 1
    purchases += _shop_for_personal_needs(connection, season_id, day, tick)
    return purchases, shortfalls


def _barter(connection: sqlite3.Connection, season_id: int, day: int, tick: int, shortfalls: list[tuple[int, str]]) -> int:
    completed = 0
    for recipient_household, category in shortfalls[:3]:
        needed = connection.execute(
            """
            SELECT hi.household_id,hi.item_id,hi.quantity,i.name,i.base_price_cents
            FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
            WHERE hi.household_id<>? AND i.category=? AND hi.quantity>=2
            ORDER BY hi.quantity DESC,i.id LIMIT 1
            """,
            (recipient_household, category),
        ).fetchone()
        if not needed:
            continue
        offered = connection.execute(
            """
            SELECT hi.item_id,hi.quantity,i.name,i.base_price_cents
            FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
            WHERE hi.household_id=? AND hi.quantity>=2 AND i.category<>?
            ORDER BY ABS(i.base_price_cents-?),hi.quantity DESC LIMIT 1
            """,
            (recipient_household, category, needed["base_price_cents"]),
        ).fetchone()
        if not offered:
            continue
        left = connection.execute(
            "SELECT resident_id FROM household_members WHERE household_id=? AND ended_season_id IS NULL ORDER BY financially_responsible DESC,id LIMIT 1",
            (recipient_household,),
        ).fetchone()
        right = connection.execute(
            "SELECT resident_id FROM household_members WHERE household_id=? AND ended_season_id IS NULL ORDER BY financially_responsible DESC,id LIMIT 1",
            (needed["household_id"],),
        ).fetchone()
        if not left or not right or left[0] == right[0]:
            continue
        summary = f"Traded {offered['name']} for {needed['name']}"
        barter_id = int(connection.execute(
            """
            INSERT INTO barter_transactions(season_id,tick,resident_a,resident_b,summary,status,created_at)
            VALUES(?,?,?,?,?,'completed',?) RETURNING id
            """,
            (season_id, tick, left[0], right[0], summary, _now()),
        ).fetchone()[0])
        connection.executemany(
            "INSERT INTO barter_lines(barter_id,from_resident_id,item_id,quantity) VALUES(?,?,?,1)",
            ((barter_id, left[0], offered["item_id"]), (barter_id, right[0], needed["item_id"])),
        )
        for from_household, to_household, item_id in (
            (recipient_household, needed["household_id"], offered["item_id"]),
            (needed["household_id"], recipient_household, needed["item_id"]),
        ):
            connection.execute("UPDATE household_inventory SET quantity=quantity-1 WHERE household_id=? AND item_id=?", (from_household, item_id))
            connection.execute(
                """
                INSERT INTO household_inventory(household_id,item_id,quantity,acquired_tick) VALUES(?,?,1,?)
                ON CONFLICT(household_id,item_id) DO UPDATE SET quantity=quantity+1,acquired_tick=excluded.acquired_tick
                """,
                (to_household, item_id, tick),
            )
            connection.execute(
                """
                INSERT INTO inventory_movements(
                  season_id,tick,item_id,quantity,movement_type,from_kind,from_id,to_kind,to_id,note,created_at
                ) VALUES(?,?,?,1,'barter','household',?,'household',?,?,?)
                """,
                (season_id, tick, item_id, from_household, to_household, summary, _now()),
            )
        low, high = sorted((int(left[0]), int(right[0])))
        connection.execute(
            """
            UPDATE relationships SET affinity=MIN(100,affinity+1),trust=MIN(100,trust+1),interactions=interactions+1,last_interaction_tick=?
            WHERE season_id=? AND resident_a=? AND resident_b=?
            """,
            (tick, season_id, low, high),
        )
        _record_call(connection, season_id, tick, int(left[0]), int(right[0]), "trade", summary, "Town Square", tick + 12)
        completed += 1
    return completed


def _record_call(
    connection: sqlite3.Connection,
    season_id: int,
    tick: int,
    caller_id: int,
    recipient_id: int,
    purpose: str,
    summary: str,
    location: str | None = None,
    due_tick: int | None = None,
) -> int:
    visibility = "private" if purpose in {"help", "care", "trade"} or _rng(season_id, tick, caller_id, recipient_id, "privacy").random() < 0.28 else "public"
    call_id = int(connection.execute(
        """
        INSERT INTO communications(
          season_id,tick,caller_resident_id,recipient_resident_id,channel,purpose,summary,
          visibility,status,duration_minutes,created_at
        ) VALUES(?,?,?,?,'call',?,?,?,'completed',?,?) RETURNING id
        """,
        (
            season_id, tick, caller_id, recipient_id, purpose, summary, visibility,
            _rng(season_id, tick, caller_id, recipient_id).randint(3, 22), _now(),
        ),
    ).fetchone()[0])
    if location and due_tick is not None and purpose in {"meetup", "help", "work", "care", "trade"}:
        for resident_id in (caller_id, recipient_id):
            goal_id = int(connection.execute(
                """
                INSERT INTO goals(season_id,resident_id,scope,description,status,progress,created_tick)
                VALUES(?,?,?,?,'active',0,?) RETURNING id
                """,
                (season_id, resident_id, "daily", summary, tick),
            ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO communication_commitments(communication_id,resident_id,goal_id,commitment_type,location,due_tick)
                VALUES(?,?,?,?,?,?)
                """,
                (call_id, resident_id, goal_id, purpose, location, due_tick),
            )
    return call_id


def run_phone_window(connection: sqlite3.Connection, season: sqlite3.Row, tick: int) -> dict[str, int]:
    seed_commerce(connection)
    season_id = int(season["id"])
    day = tick // 288
    slot = (tick % 288) // 48
    if connection.execute(
        "SELECT 1 FROM communications WHERE season_id=? AND tick=? LIMIT 1",
        (season_id, tick),
    ).fetchone():
        return {"calls": 0, "commitments": 0}
    eligible = list(connection.execute(
        """
        SELECT r.id,r.name,r.home,r.workplace,n.need_key,n.satisfaction
        FROM residents r JOIN resident_phones p ON p.resident_id=r.id AND p.active=1
        JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
        LEFT JOIN resident_needs n ON n.resident_id=r.id AND n.season_id=?
          AND n.need_key IN ('social','health','financial_security','belonging')
        ORDER BY r.id,n.satisfaction
        """,
        (season_id,),
    ))
    by_id: dict[int, sqlite3.Row] = {}
    for row in eligible:
        by_id.setdefault(int(row["id"]), row)
        if row["satisfaction"] is not None and int(row["satisfaction"]) < int(by_id[int(row["id"])]["satisfaction"] or 101):
            by_id[int(row["id"])] = row
    residents = list(by_id.values())
    if len(residents) < 2:
        return {"calls": 0, "commitments": 0}
    rng = _rng(season["seed_hex"], "phones", day, slot)
    callers = sorted(residents, key=lambda row: (int(row["satisfaction"] or 100), rng.random()))[: min(2, len(residents) // 2)]
    calls = commitments = 0
    for caller in callers:
        relation = connection.execute(
            """
            SELECT CASE WHEN rel.resident_a=? THEN rel.resident_b ELSE rel.resident_a END other_id
            FROM relationships rel JOIN resident_phones p
              ON p.resident_id=CASE WHEN rel.resident_a=? THEN rel.resident_b ELSE rel.resident_a END AND p.active=1
            WHERE rel.season_id=? AND (rel.resident_a=? OR rel.resident_b=?)
            ORDER BY (rel.trust+rel.affinity-rel.tension) DESC,other_id LIMIT 6
            """,
            (caller["id"], caller["id"], season_id, caller["id"], caller["id"]),
        ).fetchall()
        choices = [int(row[0]) for row in relation if int(row[0]) != int(caller["id"])]
        if not choices:
            choices = [int(row["id"]) for row in residents if int(row["id"]) != int(caller["id"])]
        recipient_id = rng.choice(choices)
        recipient = connection.execute("SELECT name,home,workplace FROM residents WHERE id=?", (recipient_id,)).fetchone()
        need = str(caller["need_key"] or "social")
        value = int(caller["satisfaction"] or 70)
        if need == "health" and value < 40:
            purpose, location = "help", str(caller["home"])
            summary = f"{caller['name']} called {recipient['name']} for practical help at home."
        elif need == "financial_security" and value < 50:
            purpose, location = "work", str(recipient["workplace"])
            summary = f"{caller['name']} and {recipient['name']} arranged time to tackle a work problem."
        elif need in {"social", "belonging"} and value < 55:
            purpose, location = "meetup", "Hobbs Cafe" if rng.random() < 0.5 else "Town Square"
            summary = f"{caller['name']} called {recipient['name']} and made plans to meet."
        else:
            purpose, location = "talk", None
            summary = f"{caller['name']} phoned {recipient['name']} for an ordinary catch-up."
        due = tick + rng.choice((8, 12, 18)) if location else None
        _record_call(connection, season_id, tick, int(caller["id"]), recipient_id, purpose, summary, location, due)
        calls += 1
        commitments += int(due is not None)
    return {"calls": calls, "commitments": commitments}


def claim_due_commitment(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int,
    tick: int,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT cc.*,c.summary FROM communication_commitments cc
        JOIN communications c ON c.id=cc.communication_id
        WHERE cc.resident_id=? AND c.season_id=? AND cc.status='pending' AND cc.due_tick<=?
        ORDER BY cc.due_tick,cc.id LIMIT 1
        """,
        (resident_id, season_id, tick),
    ).fetchone()
    if not row:
        return None
    connection.execute(
        "UPDATE communication_commitments SET status='completed',completed_tick=? WHERE id=?",
        (tick, row["id"]),
    )
    if row["goal_id"]:
        connection.execute(
            "UPDATE goals SET progress=MIN(100,progress+35),status=CASE WHEN progress+35>=100 THEN 'complete' ELSE status END WHERE id=?",
            (row["goal_id"],),
        )
    return {
        "type": str(row["commitment_type"]),
        "location": str(row["location"]),
        "summary": str(row["summary"]),
    }


def _snapshot_finances(connection: sqlite3.Connection, season_id: int, day: int, tick: int) -> int:
    count = 0
    for kind, table, owner_column in (
        ("resident", "residents", "resident_id"),
        ("household", "households", "household_id"),
        ("business", "businesses", "business_id"),
    ):
        for owner in connection.execute(f"SELECT id FROM {table}"):
            accounts = list(connection.execute(
                f"SELECT id,account_type FROM financial_accounts WHERE {owner_column}=? AND status='open'",
                (owner["id"],),
            ))
            cash = sum(_account_balance(connection, int(account["id"])) for account in accounts if account["account_type"] in {"cash", "chequing", "savings", "business"})
            debt = 0
            investments = 0
            if kind == "resident":
                debt = int(connection.execute(
                    """
                    SELECT COALESCE(SUM(d.outstanding_cents),0) FROM debts d
                    JOIN financial_accounts a ON a.id=d.borrower_account_id
                    WHERE a.resident_id=? AND d.status IN ('current','late','defaulted')
                    """,
                    (owner["id"],),
                ).fetchone()[0])
                investments = int(connection.execute(
                    """
                    SELECT COALESCE(SUM(i.market_value_cents),0) FROM investments i
                    JOIN financial_accounts a ON a.id=i.account_id WHERE a.resident_id=?
                    """,
                    (owner["id"],),
                ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO financial_snapshots(
                  season_id,day,tick,owner_kind,owner_id,cash_cents,debt_cents,investments_cents,net_worth_cents
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(season_id,day,owner_kind,owner_id) DO UPDATE SET
                  tick=excluded.tick,cash_cents=excluded.cash_cents,debt_cents=excluded.debt_cents,
                  investments_cents=excluded.investments_cents,net_worth_cents=excluded.net_worth_cents
                """,
                (season_id, day, tick, kind, owner["id"], cash, debt, investments, cash + investments - debt),
            )
            count += 1
    return count


def repair_dependent_finances(connection: sqlite3.Connection) -> int:
    """Reverse invalid personal debt created for babies and children by older builds."""

    season = connection.execute(
        "SELECT id,current_day,current_tick FROM seasons WHERE status IN ('running','paused') ORDER BY number DESC LIMIT 1"
    ).fetchone()
    if not season:
        return 0
    clearing = connection.execute(
        """
        SELECT a.id FROM financial_accounts a JOIN businesses b ON b.id=a.business_id
        WHERE b.name='Krabville Credit Union' AND a.name='Operating'
        """
    ).fetchone()
    if not clearing:
        return 0
    accounts = list(connection.execute(
        """
        SELECT DISTINCT a.id,a.resident_id,r.name FROM financial_accounts a
        JOIN residents r ON r.id=a.resident_id
        JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
        JOIN debts d ON d.borrower_account_id=a.id
        WHERE l.current_stage IN ('baby','child')
          AND d.status IN ('current','late','defaulted') AND d.outstanding_cents>0
        ORDER BY a.id
        """
    ))
    if not accounts:
        return 0
    corrected = 0
    connection.execute("BEGIN IMMEDIATE")
    try:
        for account in accounts:
            key = f"dependent-debt-correction:{account['id']}"
            transaction = connection.execute(
                "SELECT id FROM financial_transactions WHERE season_id=? AND external_key=?",
                (season["id"], key),
            ).fetchone()
            balance = _account_balance(connection, int(account["id"]))
            if not transaction and balance:
                transaction_id = int(connection.execute(
                    """
                    INSERT INTO financial_transactions(
                      season_id,tick,category,description,status,external_key,created_at,posted_at
                    ) VALUES(?,?,'dependent_debt_correction',?,'posted',?,?,?) RETURNING id
                    """,
                    (
                        season["id"], season["current_tick"],
                        f"Correct invalid dependent charges for {account['name']}",
                        key, _now(), _now(),
                    ),
                ).fetchone()[0])
                connection.executemany(
                    "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
                    (
                        (transaction_id, int(account["id"]), -balance, "dependent charge reversal"),
                        (transaction_id, int(clearing["id"]), balance, "dependent charge reversal offset"),
                    ),
                )
            connection.execute(
                """
                UPDATE debts SET status='forgiven',outstanding_cents=0,
                  closed_season_id=?,closed_tick=?
                WHERE borrower_account_id=? AND status IN ('current','late','defaulted')
                """,
                (season["id"], season["current_tick"], account["id"]),
            )
            connection.execute(
                """
                UPDATE financial_accounts SET status='closed',closed_season_id=?,closed_tick=?
                WHERE id=?
                """,
                (season["id"], season["current_tick"], account["id"]),
            )
            corrected += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    _snapshot_finances(
        connection, int(season["id"]), int(season["current_day"]), int(season["current_tick"])
    )
    return corrected


def _story_event(
    connection: sqlite3.Connection,
    season_id: int,
    day: int,
    tick: int,
    event_type: str,
    title: str,
    summary: str,
    subject_id: int | None = None,
    related_id: int | None = None,
    business_id: int | None = None,
    transaction_id: int | None = None,
    significance: int = 55,
    household_id: int | None = None,
    property_id: int | None = None,
) -> int:
    event_id = int(connection.execute(
        """
        INSERT INTO life_events(
          season_id,tick,event_type,subject_resident_id,related_resident_id,household_id,
          business_id,property_id,title,summary,outcome,severity,permanent,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?) RETURNING id
        """,
        (
            season_id, tick, event_type, subject_id, related_id, household_id,
            business_id, property_id,
            title, summary, event_type, significance, _now(),
        ),
    ).fetchone()[0])
    connection.execute(
        """
        INSERT INTO story_ledger(
          season_id,tick,day,entry_type,headline,summary,significance,visibility,
          life_event_id,transaction_id,created_at
        ) VALUES(?,?,?,?,?,?,?,'omniscient',?,?,?)
        """,
        (
            season_id, tick, day, event_type, title, summary, significance,
            None if transaction_id else event_id, transaction_id, _now(),
        ),
    )
    return event_id


def _business_life(connection: sqlite3.Connection, season_id: int, day: int, tick: int) -> dict[str, int]:
    result = {"started": 0, "hired": 0, "closed": 0}
    if connection.execute(
        "SELECT 1 FROM life_events WHERE season_id=? AND tick=? AND event_type LIKE 'business_%' LIMIT 1",
        (season_id, tick),
    ).fetchone():
        return result
    season = connection.execute("SELECT seed_hex FROM seasons WHERE id=?", (season_id,)).fetchone()
    rng = _rng(season["seed_hex"] if season else season_id, "business-life", day)

    candidates = []
    for row in connection.execute(
        """
        SELECT r.id,r.name,r.traits_json,a.id account_id FROM residents r
        JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1 AND l.current_stage IN ('adult','senior')
        JOIN financial_accounts a ON a.resident_id=r.id AND a.name='Personal chequing' AND a.status='open'
        LEFT JOIN business_owners own ON own.resident_id=r.id AND own.disposed_season_id IS NULL
        WHERE own.id IS NULL ORDER BY r.id
        """
    ):
        if _account_balance(connection, int(row["account_id"])) >= 150_000:
            candidates.append(row)
    active_count = int(connection.execute("SELECT COUNT(*) FROM businesses WHERE status IN ('forming','active','struggling')").fetchone()[0])
    if candidates and active_count < 24 and rng.random() < 0.34:
        founder = rng.choice(candidates)
        first = str(founder["name"]).split()[0]
        concepts = (("provisions", "Provisions", "shop", 14), ("repairs", "Repair Co-op", "shop", 10), ("studio", "Creative Studio", "office", 8), ("care", "Care Service", "office", 24))
        concept, suffix, property_type, interior_variant = rng.choice(concepts)
        slug = f"venture-s{season_id}-d{day}-{founder['id']}"
        name = f"{first}'s {suffix}"
        property_id = int(connection.execute(
            """
            INSERT INTO properties(
              slug,name,property_type,address,exterior_key,interior_key,resident_capacity,
              business_capacity,market_value_cents,status,created_season_id,created_tick,map_location,interior_variant
            ) VALUES(?,?,?,?,?,'shop',0,6,8500000,'occupied',?,?, 'Town Square',?) RETURNING id
            """,
            (f"property-{slug}", name, property_type, "Town Square", slug, season_id, tick, interior_variant),
        ).fetchone()[0])
        business_id = int(connection.execute(
            """
            INSERT INTO businesses(
              slug,name,industry,property_id,founder_resident_id,founded_season_id,founded_tick,
              status,valuation_cents,reputation,created_at
            ) VALUES(?,?,?,?,?,?,?,'active',7500000,45,?) RETURNING id
            """,
            (slug, name, concept, property_id, founder["id"], season_id, tick, _now()),
        ).fetchone()[0])
        connection.execute(
            "INSERT INTO business_owners(business_id,resident_id,ownership_basis_points,acquired_season_id,acquired_tick) VALUES(?,?,10000,?,?)",
            (business_id, founder["id"], season_id, tick),
        )
        business_account = int(connection.execute(
            "INSERT INTO financial_accounts(business_id,name,account_type,opening_balance_cents,opened_season_id,opened_tick) VALUES(?,'Operating','business',0,?,?) RETURNING id",
            (business_id, season_id, tick),
        ).fetchone()[0])
        capital = min(125_000, _account_balance(connection, int(founder["account_id"])) // 3)
        transaction_id = int(connection.execute(
            """
            INSERT INTO financial_transactions(
              season_id,tick,category,description,status,external_key,created_at,posted_at
            ) VALUES(?,?,'business_capital',?,'posted',?,?,?) RETURNING id
            """,
            (season_id, tick, f"Opening capital for {name}", f"venture:{slug}", _now(), _now()),
        ).fetchone()[0])
        connection.executemany(
            "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
            ((transaction_id, int(founder["account_id"]), -capital, "founder contribution"), (transaction_id, business_account, capital, "opening capital")),
        )
        connection.execute(
            "UPDATE employment SET status='resigned',ended_season_id=?,ended_tick=?,end_reason='started a business' WHERE resident_id=? AND status='active'",
            (season_id, tick, founder["id"]),
        )
        job_id = int(connection.execute(
            "INSERT INTO jobs(business_id,slug,title,category,hourly_wage_cents,weekly_hours,positions) VALUES(?,'owner-operator','Owner-operator','owner',2200,40,3) RETURNING id",
            (business_id,),
        ).fetchone()[0])
        connection.execute(
            "INSERT INTO employment(resident_id,job_id,status,hired_season_id,hired_tick,wage_cents,scheduled_minutes_per_day) VALUES(?,?,'active',?,?,2200,480)",
            (founder["id"], job_id, season_id, tick),
        )
        _story_event(
            connection, season_id, day, tick, "business_start", f"{name} opened",
            f"{founder['name']} invested personal savings and opened {name} at the Town Square.",
            int(founder["id"]), business_id=business_id, transaction_id=transaction_id, significance=68,
        )
        result["started"] = 1

    vacancy = connection.execute(
        """
        SELECT j.id,j.title,b.id business_id,b.name,SUM(j.positions)-COUNT(e.id) openings
        FROM jobs j JOIN businesses b ON b.id=j.business_id AND b.status='active'
        LEFT JOIN employment e ON e.job_id=j.id AND e.status='active'
        WHERE j.active=1 GROUP BY j.id HAVING openings>0 ORDER BY b.id,j.id LIMIT 1
        """
    ).fetchone()
    if vacancy:
        candidate = connection.execute(
            """
            SELECT r.id,r.name FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
            LEFT JOIN employment e ON e.resident_id=r.id
              AND e.status IN ('offered','active','leave','suspended')
            WHERE l.alive=1 AND l.current_stage IN ('teen','adult','senior') AND e.id IS NULL
            ORDER BY r.id LIMIT 1
            """
        ).fetchone()
        if candidate:
            job = connection.execute("SELECT hourly_wage_cents FROM jobs WHERE id=?", (vacancy["id"],)).fetchone()
            connection.execute(
                "INSERT INTO employment(resident_id,job_id,status,hired_season_id,hired_tick,wage_cents,scheduled_minutes_per_day) VALUES(?,?,'active',?,?,?,360)",
                (candidate["id"], vacancy["id"], season_id, tick, job["hourly_wage_cents"]),
            )
            _story_event(
                connection, season_id, day, tick, "business_hire", f"{candidate['name']} was hired",
                f"{vacancy['name']} hired {candidate['name']} as {vacancy['title']}.",
                int(candidate["id"]), business_id=int(vacancy["business_id"]), significance=48,
            )
            result["hired"] = 1

    for business in connection.execute("SELECT id,name,status FROM businesses WHERE status IN ('active','struggling') ORDER BY id"):
        account = connection.execute("SELECT id FROM financial_accounts WHERE business_id=? AND name='Operating'", (business["id"],)).fetchone()
        balance = _account_balance(connection, int(account[0])) if account else 0
        if business["status"] == "active" and balance < 10_000:
            connection.execute("UPDATE businesses SET status='struggling' WHERE id=?", (business["id"],))
        elif business["status"] == "struggling" and balance < 5_000 and day >= 2 and rng.random() < 0.35:
            connection.execute("UPDATE businesses SET status='closed',closed_season_id=?,closed_tick=? WHERE id=?", (season_id, tick, business["id"]))
            connection.execute(
                """
                UPDATE employment SET status='terminated',ended_season_id=?,ended_tick=?,end_reason='business closed'
                WHERE job_id IN (SELECT id FROM jobs WHERE business_id=?) AND status='active'
                """,
                (season_id, tick, business["id"]),
            )
            _story_event(
                connection, season_id, day, tick, "business_close", f"{business['name']} closed",
                f"Low cash and weak trade forced {business['name']} to close.",
                business_id=int(business["id"]), significance=72,
            )
            result["closed"] += 1
    return result


def _illicit_economy(connection: sqlite3.Connection, season_id: int, day: int, tick: int) -> dict[str, int]:
    result = {"thefts": 0, "scams": 0, "blackMarketTrades": 0}
    if connection.execute(
        "SELECT 1 FROM life_events WHERE season_id=? AND tick=? AND event_type IN ('theft','scam','black_market') LIMIT 1",
        (season_id, tick),
    ).fetchone():
        return result
    season = connection.execute("SELECT seed_hex FROM seasons WHERE id=?", (season_id,)).fetchone()
    rng = _rng(season["seed_hex"] if season else season_id, "illicit", day)
    if rng.random() >= 0.30:
        return result
    people = list(connection.execute(
        """
        SELECT r.id,r.name,r.traits_json,hm.household_id,a.id account_id
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1 AND l.current_stage IN ('teen','adult','senior')
        JOIN household_members hm ON hm.resident_id=r.id AND hm.ended_season_id IS NULL
        JOIN financial_accounts a ON a.resident_id=r.id AND a.name='Personal chequing' AND a.status='open'
        ORDER BY r.id
        """
    ))
    if len(people) < 2:
        return result
    people.sort(key=lambda row: int(re.search(r'"risk":(\d+)', str(row["traits_json"])).group(1)) if re.search(r'"risk":(\d+)', str(row["traits_json"])) else 0, reverse=True)
    actor = people[0]
    victim = rng.choice([person for person in people[1:] if person["household_id"] != actor["household_id"]] or people[1:])
    kind = rng.choice(("theft", "scam", "black_market"))
    transaction_id: int | None = None
    if kind == "scam":
        amount = min(_account_balance(connection, int(victim["account_id"])), rng.randint(2_000, 12_000))
        if amount < 500:
            return result
        transaction_id = int(connection.execute(
            """
            INSERT INTO financial_transactions(season_id,tick,category,description,status,external_key,created_at,posted_at)
            VALUES(?,?,'scam',?,'posted',?,?,?) RETURNING id
            """,
            (season_id, tick, f"Scam transfer involving {actor['name']} and {victim['name']}", f"scam:{season_id}:{day}", _now(), _now()),
        ).fetchone()[0])
        connection.executemany(
            "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
            ((transaction_id, int(victim["account_id"]), -amount, "scam loss"), (transaction_id, int(actor["account_id"]), amount, "scam proceeds")),
        )
        title = f"A money scam hit {victim['name']}"
        summary = f"{actor['name']} deceived {victim['name']} out of ${amount / 100:,.2f}; the damage is now part of both life ledgers."
        result["scams"] = 1
    else:
        stolen = connection.execute(
            """
            SELECT hi.item_id,i.name FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
            WHERE hi.household_id=? AND hi.quantity>=1 ORDER BY i.base_price_cents DESC LIMIT 1
            """,
            (victim["household_id"],),
        ).fetchone()
        offered = connection.execute(
            """
            SELECT hi.item_id,i.name FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
            WHERE hi.household_id=? AND hi.quantity>=1 ORDER BY i.base_price_cents LIMIT 1
            """,
            (actor["household_id"],),
        ).fetchone()
        if not stolen:
            return result
        connection.execute("UPDATE household_inventory SET quantity=quantity-1 WHERE household_id=? AND item_id=?", (victim["household_id"], stolen["item_id"]))
        connection.execute(
            """
            INSERT INTO household_inventory(household_id,item_id,quantity,acquired_tick) VALUES(?,?,1,?)
            ON CONFLICT(household_id,item_id) DO UPDATE SET quantity=quantity+1,acquired_tick=excluded.acquired_tick
            """,
            (actor["household_id"], stolen["item_id"], tick),
        )
        movement = "theft" if kind == "theft" else "barter"
        connection.execute(
            """
            INSERT INTO inventory_movements(
              season_id,tick,item_id,quantity,movement_type,from_kind,from_id,to_kind,to_id,note,created_at
            ) VALUES(?,?,?,1,?,'household',?,'household',?,?,?)
            """,
            (season_id, tick, stolen["item_id"], movement, victim["household_id"], actor["household_id"], kind, _now()),
        )
        if kind == "black_market" and offered:
            connection.execute("UPDATE household_inventory SET quantity=quantity-1 WHERE household_id=? AND item_id=?", (actor["household_id"], offered["item_id"]))
            connection.execute(
                """
                INSERT INTO household_inventory(household_id,item_id,quantity,acquired_tick) VALUES(?,?,1,?)
                ON CONFLICT(household_id,item_id) DO UPDATE SET quantity=quantity+1,acquired_tick=excluded.acquired_tick
                """,
                (victim["household_id"], offered["item_id"], tick),
            )
            barter_id = int(connection.execute(
                """
                INSERT INTO barter_transactions(
                  season_id,tick,resident_a,resident_b,summary,trade_channel,status,created_at
                ) VALUES(?,?,?,?,?,'black_market','completed',?) RETURNING id
                """,
                (season_id, tick, actor["id"], victim["id"], f"Quiet trade of {offered['name']} for {stolen['name']}", _now()),
            ).fetchone()[0])
            connection.executemany(
                "INSERT INTO barter_lines(barter_id,from_resident_id,item_id,quantity) VALUES(?,?,?,1)",
                ((barter_id, actor["id"], offered["item_id"]), (barter_id, victim["id"], stolen["item_id"])),
            )
            title = "A black-market trade surfaced"
            summary = f"{actor['name']} and {victim['name']} quietly traded {offered['name']} for {stolen['name']}."
            result["blackMarketTrades"] = 1
        else:
            title = f"{victim['name']} reported a theft"
            summary = f"{stolen['name']} disappeared from {victim['name']}'s household and turned up with {actor['name']}."
            result["thefts"] = 1
    low, high = sorted((int(actor["id"]), int(victim["id"])))
    connection.execute(
        """
        UPDATE relationships SET tension=MIN(100,tension+8),trust=MAX(0,trust-6),resentment=MIN(100,resentment+7),
          interactions=interactions+1,last_interaction_tick=? WHERE season_id=? AND resident_a=? AND resident_b=?
        """,
        (tick, season_id, low, high),
    )
    _story_event(
        connection, season_id, day, tick, kind, title, summary,
        int(actor["id"]), int(victim["id"]), transaction_id=transaction_id, significance=78,
    )
    return result


def _adjust_wages(connection: sqlite3.Connection, season_id: int, day: int) -> int:
    changed = 0
    for job in connection.execute("SELECT id,hourly_wage_cents FROM jobs WHERE active=1 ORDER BY id"):
        rng = _rng(season_id, day, job["id"], "wage")
        if rng.random() >= 0.22:
            continue
        factor = 1 + rng.choice((-1, 1)) * rng.uniform(0.003, 0.012)
        wage = max(1500, min(7500, round(int(job["hourly_wage_cents"]) * factor)))
        if wage == int(job["hourly_wage_cents"]):
            continue
        connection.execute("UPDATE jobs SET hourly_wage_cents=? WHERE id=?", (wage, job["id"]))
        connection.execute("UPDATE employment SET wage_cents=? WHERE job_id=? AND status='active'", (wage, job["id"]))
        changed += 1
    return changed


def _move_household_to_shelter(
    connection: sqlite3.Connection,
    season_id: int,
    tick: int,
    household_id: int,
    subject_id: int,
) -> bool:
    shelter = connection.execute("SELECT id FROM properties WHERE slug='harbour-shelter'").fetchone()
    occupancy = connection.execute(
        """
        SELECT po.id,po.property_id,p.name,p.property_type FROM property_occupancy po
        JOIN properties p ON p.id=po.property_id
        WHERE po.household_id=? AND po.ended_season_id IS NULL ORDER BY po.id DESC LIMIT 1
        """,
        (household_id,),
    ).fetchone()
    if not shelter or not occupancy or int(occupancy["property_id"]) == int(shelter[0]):
        return False
    connection.execute(
        "UPDATE property_occupancy SET ended_season_id=?,ended_tick=?,end_reason='financial displacement' WHERE id=?",
        (season_id, tick, occupancy["id"]),
    )
    connection.execute(
        """
        INSERT INTO property_occupancy(property_id,household_id,occupancy_type,monthly_cost_cents,started_season_id,started_tick)
        VALUES(?,?,'emergency',0,?,?)
        """,
        (shelter[0], household_id, season_id, tick),
    )
    connection.execute("UPDATE properties SET status='available' WHERE id=?", (occupancy["property_id"],))
    connection.execute("UPDATE properties SET status='occupied' WHERE id=?", (shelter[0],))
    connection.execute(
        """
        UPDATE residents SET home='Harbour Shelter' WHERE id IN (
          SELECT resident_id FROM household_members WHERE household_id=? AND ended_season_id IS NULL
        )
        """,
        (household_id,),
    )
    _story_event(
        connection, season_id, tick // 288, tick, "eviction", "A household moved into emergency shelter",
        f"Mounting arrears forced the household out of {occupancy['name']}; Harbour Shelter took them in.",
        subject_id, significance=86, household_id=household_id, property_id=int(occupancy["property_id"]),
    )
    return True


def _financial_hardship(connection: sqlite3.Connection, season_id: int, day: int, tick: int) -> dict[str, int]:
    result = {"lateDebts": 0, "defaults": 0, "repossessions": 0, "evictions": 0, "bankruptcies": 0, "recoveries": 0}
    clearing = connection.execute(
        """
        SELECT a.id FROM financial_accounts a JOIN businesses b ON b.id=a.business_id
        WHERE b.name='Krabville Credit Union' AND a.name='Operating'
        """
    ).fetchone()
    debts = list(connection.execute(
        """
        SELECT d.*,a.resident_id,r.name,
          (SELECT id FROM financial_accounts WHERE resident_id=a.resident_id AND name='Personal chequing') chequing_id,
          hm.household_id
        FROM debts d JOIN financial_accounts a ON a.id=d.borrower_account_id
        JOIN residents r ON r.id=a.resident_id
        LEFT JOIN household_members hm ON hm.resident_id=r.id AND hm.ended_season_id IS NULL
        WHERE d.status IN ('current','late','defaulted') ORDER BY d.id
        """
    ))
    for debt in debts:
        if not debt["chequing_id"]:
            continue
        balance = _account_balance(connection, int(debt["chequing_id"]))
        minimum = max(2500, int(debt["minimum_payment_cents"]))
        resident_id = int(debt["resident_id"])
        status = str(debt["status"])
        if status in {"late", "defaulted"} and balance >= minimum * 4:
            connection.execute("UPDATE debts SET status='current' WHERE id=?", (debt["id"],))
            connection.execute("UPDATE financial_accounts SET status='open' WHERE id=?", (debt["borrower_account_id"],))
            _story_event(connection, season_id, day, tick, "financial_recovery", f"{debt['name']} caught up",
                         f"{debt['name']} stabilized their account and brought a troubled debt current.", resident_id, significance=62)
            result["recoveries"] += 1
            continue
        if day >= 1 and status == "current" and balance < minimum:
            fee = min(2500, max(500, minimum // 8))
            connection.execute("UPDATE debts SET status='late',outstanding_cents=outstanding_cents+? WHERE id=?", (fee, debt["id"]))
            if clearing:
                transaction_id = int(connection.execute(
                    """
                    INSERT INTO financial_transactions(
                      season_id,tick,category,description,status,external_key,created_at,posted_at
                    ) VALUES(?,?,'late_fee',?,'posted',?,?,?) RETURNING id
                    """,
                    (season_id, tick, f"Late fee for {debt['name']}", f"late-fee:{day}:{debt['id']}", _now(), _now()),
                ).fetchone()[0])
                connection.executemany(
                    "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
                    ((transaction_id, int(debt["borrower_account_id"]), -fee, "late fee liability"),
                     (transaction_id, int(clearing[0]), fee, "late fee receivable")),
                )
            _story_event(connection, season_id, day, tick, "debt_late", f"{debt['name']} fell behind",
                         f"A missed payment put {debt['name']}'s debt into arrears.", resident_id, significance=58)
            result["lateDebts"] += 1
            continue
        if status == "late":
            late_tick = connection.execute(
                "SELECT MAX(tick) FROM life_events WHERE event_type='debt_late' AND subject_resident_id=?",
                (resident_id,),
            ).fetchone()[0]
            if late_tick is not None and tick - int(late_tick) >= 288 and balance < minimum * 2:
                connection.execute("UPDATE debts SET status='defaulted' WHERE id=?", (debt["id"],))
                connection.execute("UPDATE financial_accounts SET status='defaulted' WHERE id=?", (debt["borrower_account_id"],))
                _story_event(connection, season_id, day, tick, "debt_default", f"{debt['name']} defaulted",
                             f"The overdue balance became a formal default, putting housing and possessions at risk.", resident_id, significance=75)
                result["defaults"] += 1
                status = "defaulted"
        if status != "defaulted":
            continue
        household_id = int(debt["household_id"] or 0)
        prior_repo = connection.execute(
            "SELECT 1 FROM life_events WHERE event_type='repossession' AND subject_resident_id=? LIMIT 1",
            (resident_id,),
        ).fetchone()
        if day >= 3 and household_id and not prior_repo:
            item = connection.execute(
                """
                SELECT hi.item_id,hi.quantity,i.name,i.base_price_cents FROM household_inventory hi
                JOIN item_catalog i ON i.id=hi.item_id
                WHERE hi.household_id=? AND hi.quantity>=1 AND i.consumable=0
                ORDER BY i.base_price_cents DESC LIMIT 1
                """,
                (household_id,),
            ).fetchone()
            if item:
                credit = min(int(debt["outstanding_cents"]), round(int(item["base_price_cents"]) * 0.6))
                connection.execute("UPDATE household_inventory SET quantity=quantity-1 WHERE household_id=? AND item_id=?", (household_id, item["item_id"]))
                connection.execute("UPDATE debts SET outstanding_cents=MAX(0,outstanding_cents-?) WHERE id=?", (credit, debt["id"]))
                connection.execute(
                    """
                    INSERT INTO inventory_movements(
                      season_id,tick,item_id,quantity,movement_type,from_kind,from_id,to_kind,note,created_at
                    ) VALUES(?,?,?,1,'transfer','household',?,'estate','debt repossession',?)
                    """,
                    (season_id, tick, item["item_id"], household_id, _now()),
                )
                _story_event(connection, season_id, day, tick, "repossession", f"A possession was repossessed from {debt['name']}",
                             f"A {item['name']} was surrendered against the defaulted balance.", resident_id, significance=72, household_id=household_id)
                result["repossessions"] += 1
        prior_eviction = connection.execute(
            "SELECT 1 FROM life_events WHERE event_type='eviction' AND household_id=? LIMIT 1", (household_id,)
        ).fetchone() if household_id else None
        if day >= 4 and household_id and not prior_eviction and _move_household_to_shelter(connection, season_id, tick, household_id, resident_id):
            result["evictions"] += 1
        if day >= 6 and int(debt["outstanding_cents"]) >= 2_000_000 and not connection.execute(
            "SELECT 1 FROM life_events WHERE event_type='bankruptcy' AND subject_resident_id=? LIMIT 1", (resident_id,)
        ).fetchone():
            connection.execute(
                """
                UPDATE debts SET status='forgiven',outstanding_cents=0,closed_season_id=?,closed_tick=?
                WHERE borrower_account_id IN (SELECT id FROM financial_accounts WHERE resident_id=?)
                  AND status IN ('late','defaulted')
                """,
                (season_id, tick, resident_id),
            )
            _story_event(connection, season_id, day, tick, "bankruptcy", f"{debt['name']} entered bankruptcy",
                         f"A formal insolvency cleared unpayable debt but left {debt['name']} rebuilding from scratch.", resident_id, significance=92)
            result["bankruptcies"] += 1
    return result


def run_daily_commerce(connection: sqlite3.Connection, season_id: int, day: int, tick: int) -> dict[str, int]:
    seed_commerce(connection)
    inventory = _spoil_and_wear(connection, season_id, day, tick)
    consumed = _consume_home_stock(connection, season_id, tick)
    used_items = _use_personal_goods(connection, season_id, tick)
    restocked = _restock(connection, season_id, day, tick)
    purchases, shortfalls = _shop(connection, season_id, day, tick)
    barters = _barter(connection, season_id, day, tick, shortfalls)
    business = _business_life(connection, season_id, day, tick)
    illicit = _illicit_economy(connection, season_id, day, tick)
    hardship = _financial_hardship(connection, season_id, day, tick)
    wages = _adjust_wages(connection, season_id, day)
    snapshots = _snapshot_finances(connection, season_id, day, tick)
    for item in connection.execute("SELECT id FROM item_catalog WHERE active=1"):
        row = connection.execute(
            """
            SELECT COALESCE(AVG(unit_price_cents),0),COALESCE(SUM(quantity),0)
            FROM inventory_movements WHERE season_id=? AND item_id=? AND movement_type='purchase'
              AND tick BETWEEN ? AND ?
            """,
            (season_id, item["id"], day * 288, day * 288 + 287),
        ).fetchone()
        connection.execute(
            "INSERT OR REPLACE INTO price_history(season_id,day,item_id,average_price_cents,units_sold) VALUES(?,?,?,?,?)",
            (season_id, day, item["id"], int(row[0]), float(row[1])),
        )
    return {
        "consumed": consumed,
        "usedItems": used_items,
        "restocked": restocked,
        "purchases": purchases,
        "barters": barters,
        "shortfalls": len(shortfalls),
        "snapshots": snapshots,
        "businessesStarted": business["started"],
        "hires": business["hired"],
        "businessesClosed": business["closed"],
        "wagesAdjusted": wages,
        **inventory,
        **hardship,
        **illicit,
    }
