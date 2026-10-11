"""The Facet catalog: 24 fictional beauty and personal-care products, six per category.

External IDs are stable so the seed is idempotent. Demo-only merchandising fields
(brand, size, tags, accent) live in ``metadata``; the storefront renders product
art from the category and accent, so no image files are needed.
"""

from __future__ import annotations

from typing import Any, Dict, List

CATEGORIES = ("skincare", "haircare", "makeup", "fragrance")

ACCENTS = {
    "skincare": "#C9D8CD",
    "haircare": "#DCC9B4",
    "makeup": "#E8C4B8",
    "fragrance": "#E4D4AF",
}


def _p(
    external_id: str,
    title: str,
    price: str,
    category: str,
    size: str,
    brand: str,
    description: str,
    *tags: str,
) -> Dict[str, Any]:
    return {
        "external_id": external_id,
        "title": title,
        "description": description,
        "price": price,
        "category": category,
        "is_active": True,
        "availability_status": "available",
        "metadata": {
            "brand": brand,
            "size": size,
            "tags": list(tags),
            "accent": ACCENTS[category],
            "source": "facet-demo",
        },
    }


PRODUCTS: List[Dict[str, Any]] = [
    # -- skincare --------------------------------------------------------------------
    _p("skin-mist-01", "Rosewater Toning Mist", "24.00", "skincare", "120 ml", "Northstar",
       "A fine-mist toner of steam-distilled rose and glycerin. Settles redness after cleansing and leaves skin damp enough for a serum to absorb.",
       "toner", "sensitive"),
    _p("skin-cream-01", "Barrier Repair Cream", "38.00", "skincare", "50 ml", "Northstar",
       "Ceramides in a squalane base. Thick without being occlusive, formulated for skin that stings after actives.",
       "moisturiser", "ceramides", "sensitive"),
    _p("skin-mask-01", "Overnight Ceramide Mask", "34.00", "skincare", "60 ml", "Northstar",
       "A sleeping mask that seals moisture in place for eight hours. Fragrance-free and safe over retinoids.",
       "mask", "night"),
    _p("skin-cleanser-01", "Gentle Milk Cleanser", "22.00", "skincare", "150 ml", "Northstar",
       "A low-foam milk cleanser that removes sunscreen without stripping. Suitable for morning and evening use.",
       "cleanser", "gentle"),
    _p("skin-serum-01", "Niacinamide Serum 10%", "29.00", "skincare", "30 ml", "Northstar",
       "Ten percent niacinamide with zinc PCA for visible pores and uneven tone. Layer under moisturiser.",
       "serum", "niacinamide"),
    _p("skin-spf-01", "Daily Mineral SPF 50", "31.00", "skincare", "50 ml", "Northstar",
       "A zinc-oxide sunscreen that dries down sheer on most skin tones. Reef-safe and fragrance-free.",
       "spf", "mineral"),
    # -- haircare --------------------------------------------------------------------
    _p("hair-curl-01", "Curl Defining Cream", "26.00", "haircare", "200 ml", "Fennel & Co",
       "A humidity-resistant cream for waves and coils. Defines clumps on damp hair without a cast.",
       "styling", "curls"),
    _p("hair-tonic-01", "Scalp Balance Tonic", "31.00", "haircare", "100 ml", "Fennel & Co",
       "A lightweight tonic with salicylic acid and rosemary for flaking and build-up between washes.",
       "scalp", "treatment"),
    _p("hair-oil-01", "Weightless Repair Oil", "35.00", "haircare", "50 ml", "Fennel & Co",
       "Camellia and marula oils in a fast-absorbing blend. Two drops through mid-lengths, nothing left on the hands.",
       "oil", "repair"),
    _p("hair-conditioner-01", "Slow Rinse Conditioner", "24.00", "haircare", "250 ml", "Fennel & Co",
       "A slip-heavy conditioner made for detangling in the shower. Rinses clean, leaves no coating.",
       "conditioner"),
    _p("hair-shampoo-01", "Low-Lather Shampoo", "22.00", "haircare", "250 ml", "Fennel & Co",
       "A sulfate-free shampoo that cleans without squeak. Made for every-other-day washing.",
       "shampoo", "sulfate-free"),
    _p("hair-beard-01", "Beard & Brow Balm", "19.00", "haircare", "40 g", "Fennel & Co",
       "A soft-hold balm of shea and jojoba for beards, brows and flyaways. Unscented.",
       "grooming", "balm"),
    # -- makeup ----------------------------------------------------------------------
    _p("makeup-tint-01", "Sheer Tint SPF 30", "32.00", "makeup", "40 ml", "Ochre",
       "A skin tint with mineral SPF 30 in twelve shades. Evens tone without covering texture.",
       "base", "spf"),
    _p("makeup-blush-01", "Cream Blush in Ochre", "23.00", "makeup", "6 g", "Ochre",
       "A warm ochre cream blush that melts into skin. Buildable from a wash to a flush with fingertips.",
       "cheek", "cream"),
    _p("makeup-mascara-01", "Lash Conditioning Mascara", "26.00", "makeup", "9 ml", "Ochre",
       "Separates and conditions with peptides and castor oil. Washes off with warm water alone.",
       "eyes", "mascara"),
    _p("makeup-balm-01", "Satin Lip Balm", "18.00", "makeup", "4 g", "Ochre",
       "A satin-finish balm in a twist tube. Comfortable enough to reapply without looking at a mirror.",
       "lips", "balm"),
    _p("makeup-brow-01", "Brow Setting Gel", "19.00", "makeup", "8 ml", "Ochre",
       "A clear flexible gel that holds brows in place all day and brushes out at night.",
       "brows", "gel"),
    _p("makeup-palette-01", "Warm Neutrals Eye Palette", "42.00", "makeup", "9 × 1.5 g", "Ochre",
       "Nine matte and satin shades from sand to espresso. Pressed soft enough to blend with a finger.",
       "eyes", "palette"),
    # -- fragrance -------------------------------------------------------------------
    _p("frag-edp-01", "Fig & Cedar Eau de Parfum", "78.00", "fragrance", "50 ml", "Saltmarsh",
       "Green fig over cedar and a dry musk. Warms through the afternoon rather than announcing itself.",
       "perfume", "woody"),
    _p("frag-handwash-01", "Neroli Hand Wash", "21.00", "fragrance", "300 ml", "Saltmarsh",
       "A gentle surfactant wash scented with neroli and petitgrain. Made for a sink that guests will use.",
       "home", "citrus"),
    _p("frag-solid-01", "Amber Solid Perfume", "44.00", "fragrance", "15 g", "Saltmarsh",
       "Amber and benzoin in a beeswax base, in a refillable tin. Apply at the wrists and collarbone.",
       "perfume", "amber"),
    _p("frag-mist-01", "Linen Room Mist", "29.00", "fragrance", "200 ml", "Saltmarsh",
       "A clean linen and white tea mist for bedding and towels. Alcohol-light so fabric dries fast.",
       "home", "fresh"),
    _p("frag-candle-01", "Smoked Tea Candle", "36.00", "fragrance", "220 g", "Saltmarsh",
       "Lapsang tea, birch tar and a little honey in a coconut-soy wax. Forty hours of burn time.",
       "home", "candle"),
    _p("frag-oil-01", "Vetiver Roll-On Oil", "32.00", "fragrance", "10 ml", "Saltmarsh",
       "Haitian vetiver and grapefruit in a jojoba base. A quiet, close-wearing scent for work days.",
       "perfume", "green"),
]

PRODUCT_IDS = [p["external_id"] for p in PRODUCTS]
BY_ID = {p["external_id"]: p for p in PRODUCTS}

assert len(PRODUCTS) == 24
assert all(sum(1 for p in PRODUCTS if p["category"] == c) == 6 for c in CATEGORIES)
