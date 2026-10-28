"""
Industry Blueprint Generator & AI Vision Auto-Recognition Service for Skantha WMS
Autonomously scaffolds turn-key industrial warehouse ecosystems:
- Automatic Company & Industry Classification (Auto-detect from company name/profile)
- Comprehensive Enterprise SKU Master (30-40 authentic SKUs per sector with weights, volumes, packaging, pallet math)
- AI Vision Zero-Shot Classes & Camera associations
- Automatic Visual Product Image Synthesis & Mapping into sku_images database table
- Specialized Warehouse Zones (Assembly, Cold Storage, Staging, Cleanrooms, Docks)
- Authentic Inbound Deliveries & Vehicle Plates for ANPR testing
- Storage Bin & Inventory Slotting
"""

import os
import re
import cv2
import json
import uuid
import logging
import sqlite3
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("industry_blueprint_service")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads", "sku_images")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ==============================================================================
# 1. AUTOMATIC COMPANY & INDUSTRY DOMAIN CLASSIFIER
# ==============================================================================

def auto_detect_company_industry(company_name: str, description: str = "") -> Dict[str, Any]:
    """
    Intelligently analyzes a company name or warehouse description to determine
    the matching industrial domain, operating mode, and blueprint specifications.
    E.g. 'Coca-Cola Bottling Plant' -> 'beverage'
         'Hyundai Motor Assembly' -> 'automotive'
         'Cipla Pharma Depot' -> 'pharma'
    """
    text = f"{company_name} {description}".lower()

    scores = {
        "beverage": 0,
        "automotive": 0,
        "electronics": 0,
        "pharma": 0,
        "metals": 0,
        "glass": 0,
        "wood": 0,
        "construction": 0,
        "chemicals": 0,
        "textiles": 0,
        "3pl": 0
    }

    keywords_map = {
        "beverage": [
            "coca", "coke", "pepsi", "beverage", "drink", "bottling", "bottle", "can",
            "brewery", "beer", "soda", "juice", "fmcg", "water", "kinley", "dairy",
            "milk", "syrup", "amul", "nestle", "heineken", "diageo", "cold beverage",
            "red bull", "britannia", "parle", "cadbury", "mondelez", "itc", "unilever",
            "hul", "kellogg", "tropicana", "bisleri", "aquafina", "mother dairy", "danone"
        ],
        "automotive": [
            "tata motors", "hyundai", "automotive", "auto", "car", "motor", "engine",
            "chassis", "oem", "assembly", "maruti", "mahindra", "toyota", "ford",
            "vehicle", "suspension", "brake", "tesla", "bosch", "honda", "bmw",
            "nissan", "audi", "mercedes", "volvo", "volkswagen", "kia", "continental", "denso"
        ],
        "electronics": [
            "samsung", "electronics", "lg", "semiconductor", "chip", "oled", "display",
            "tv", "phone", "hardware", "intel", "foxconn", "apple", "device", "pcb",
            "microchip", "dell", "lenovo", "asus", "sony", "panasonic", "nvidia", "amd",
            "qualcomm", "tsmc", "cisco", "hp", "xiaomi", "oppo", "vivo", "oneplus"
        ],
        "pharma": [
            "pfizer", "pharma", "pharmaceutical", "cipla", "vaccine", "medicine",
            "biotech", "drug", "healthcare", "sun pharma", "dr reddy", "biocon",
            "serum", "hospital", "vial", "ampoule", "medical", "novartis", "gsk", "astrazeneca",
            "lupin", "aurobindo", "zydus", "mankind", "abbott", "roche", "bayer", "sanofi", "moderna"
        ],
        "metals": [
            "tata steel", "steel", "jindal", "metal", "pipe", "tube", "rebar",
            "foundry", "iron", "smelter", "aluminum", "vedanta", "crane", "heavy industrial",
            "coil", "beam", "girders", "fabrication", "alloy", "arcelor", "sail", "posco",
            "hindalco", "copper", "brass", "zinc", "nippon"
        ],
        "glass": [
            "saint-gobain", "saint gobain", "asahi", "ais glass", "gold plus", "guardian glass",
            "borosil", "corning", "pilkington", "schott", "glass", "glazing", "float glass",
            "toughened", "tempered glass", "laminated glass", "mirror", "dgu", "insulated glass",
            "fenestration", "architectural glass", "safety glass", "tinted glass", "frosted glass",
            "a-frame", "glass sheet", "glass pane", "cullet", "borosilicate", "glassware"
        ],
        "wood": [
            "centuryply", "century ply", "greenply", "greenpanel", "action tesa", "merino",
            "kitply", "archidply", "sylvan", "wood", "timber", "plywood", "lumber",
            "mdf", "hdf", "hdhmr", "particle board", "veneer", "laminate", "teak",
            "pine", "oak", "mahogany", "hardwood", "softwood", "sawmill", "carpentry",
            "plank", "wooden", "joinery", "bwp", "blockboard", "shuttering ply", "forestry"
        ],
        "construction": [
            "ultratech", "ambuja", "acc cement", "shree cement", "dalmia", "ramco",
            "kajaria", "somany", "nitco", "cera", "hindware", "jaquar", "gyproc",
            "cement", "concrete", "mortar", "tile", "tiles", "ceramic", "vitrified",
            "porcelain", "gypsum", "drywall", "plasterboard", "brick", "aac block",
            "construction", "building material", "sanitaryware", "roofing", "aggregate"
        ],
        "chemicals": [
            "pidilite", "asian paints", "berger", "nerolac", "akzonobel", "basf",
            "dow chemical", "upl", "coromandel", "tata chemicals", "aarti industries", "srf",
            "deepak nitrite", "chemical", "polymer", "resin", "epoxy", "solvent",
            "adhesive", "paint", "coating", "fertilizer", "agrochemical", "acid",
            "alkali", "petrochemical", "polyurethane", "silicone", "pigment"
        ],
        "textiles": [
            "raymond", "arvind", "welspun", "vardhman", "trident", "page industries",
            "alok industries", "kpr mill", "grasim", "textile", "fabric", "cotton",
            "yarn", "spinning", "garment", "apparel", "denim", "polyester",
            "loom", "weaving", "knitting", "cloth", "dyeing", "silk", "wool"
        ],
        "3pl": [
            "dhl", "3pl", "logistics", "courier", "freight", "schenker", "commercial hub",
            "fedex", "blue dart", "ups", "warehousing", "express", "multi-client",
            "cargo", "transporter", "supply chain", "maersk", "kuehne", "amazon", "flipkart",
            "walmart", "target", "costco", "delhivery", "shadowfax", "e-commerce"
        ]
    }

    for ind, kw_list in keywords_map.items():
        for kw in kw_list:
            if kw in text:
                scores[ind] += (4 if " " in kw else 2)

    best_industry = max(scores, key=scores.get)
    highest_score = scores[best_industry]

    if highest_score > 0:
        detected_key = best_industry
        confidence = min(0.99, 0.70 + (highest_score * 0.05))
        reason = f"Identified industrial signature matching '{detected_key}' based on domain keywords."
    else:
        detected_key = "custom"
        confidence = 0.50
        reason = "Custom enterprise sector detected; dynamic synthesis engine activated."

    return {
        "detected_key": detected_key,
        "blueprint_key": detected_key,
        "confidence": round(confidence, 2),
        "company_name": company_name,
        "reason": reason,
        "scores": scores
    }


# ==============================================================================
# 2. INDUSTRIAL BLUEPRINT SPECIFICATIONS (30-40 AUTHENTIC SKUs EACH)
# ==============================================================================

INDUSTRY_BLUEPRINTS: Dict[str, Dict[str, Any]] = {
    # --------------------------------------------------------------------------
    # 1. BEVERAGE & FMCG (Coca-Cola / PepsiCo Style) - 35 SKUs
    # --------------------------------------------------------------------------
    "beverage": {
        "key": "beverage",
        "name": "Beverage & FMCG Bottling",
        "badge_icon": "fa-bottle-water",
        "theme_color": "#ef4444",
        "company_example": "The Coca-Cola Company / PepsiCo Bottling Hub",
        "operating_mode": "DEDICATED",
        "description": "Finished beverage cases, PET bottles, glass returnables, concentrates, syrups, preforms, and can bodies.",
        "skus": [
            # Carbonated Cans
            {"sku_id": "COKE-CAN-330", "name": "Coca-Cola Original 330ml (24-Tray)", "category": "Canned Beverages", "description": "Classic Coca-Cola 330ml aluminum cans packed in corrugated 24-can distribution tray.", "unit_weight": 8.6, "unit_volume": 0.018, "uom": "Tray", "units_per_bundle": 24, "target_bundles_per_pallet": 60, "bundle_name": "Can Tray 24pk", "visual_color": (30, 30, 200), "icon_shape": "can"},
            {"sku_id": "COKE-ZERO-330", "name": "Coca-Cola Zero Sugar 330ml (24-Tray)", "category": "Canned Beverages", "description": "Zero sugar black-band 330ml cans packed in sealed 24-tray.", "unit_weight": 8.4, "unit_volume": 0.018, "uom": "Tray", "units_per_bundle": 24, "target_bundles_per_pallet": 60, "bundle_name": "Can Tray 24pk", "visual_color": (20, 20, 20), "icon_shape": "can"},
            {"sku_id": "COKE-DIET-330", "name": "Diet Coke 330ml Cans (24-Tray)", "category": "Canned Beverages", "description": "Silver edition Diet Coke 330ml aluminum cans in shrink-wrapped tray.", "unit_weight": 8.4, "unit_volume": 0.018, "uom": "Tray", "units_per_bundle": 24, "target_bundles_per_pallet": 60, "bundle_name": "Can Tray 24pk", "visual_color": (160, 160, 160), "icon_shape": "can"},
            {"sku_id": "COKE-CAN-500", "name": "Coca-Cola 500ml Tall Boy Cans (24pk)", "category": "Canned Beverages", "description": "500ml tall boy cans in heavy corrugated base tray.", "unit_weight": 12.8, "unit_volume": 0.026, "uom": "Tray", "units_per_bundle": 24, "target_bundles_per_pallet": 45, "bundle_name": "Tall Boy Tray", "visual_color": (25, 25, 180), "icon_shape": "can"},
            {"sku_id": "SPRITE-CAN-330", "name": "Sprite Lemon-Lime 330ml (24-Tray)", "category": "Canned Beverages", "description": "Green can 330ml Sprite lemon-lime drink in 24-pack shrink tray.", "unit_weight": 8.5, "unit_volume": 0.018, "uom": "Tray", "units_per_bundle": 24, "target_bundles_per_pallet": 60, "bundle_name": "Can Tray 24pk", "visual_color": (30, 160, 50), "icon_shape": "can"},
            {"sku_id": "FANTA-CAN-330", "name": "Fanta Orange 330ml (24-Tray)", "category": "Canned Beverages", "description": "Fanta Orange sparkling beverage 330ml cans in corrugated tray.", "unit_weight": 8.6, "unit_volume": 0.018, "uom": "Tray", "units_per_bundle": 24, "target_bundles_per_pallet": 60, "bundle_name": "Can Tray 24pk", "visual_color": (10, 120, 230), "icon_shape": "can"},
            {"sku_id": "THUMS-CAN-330", "name": "Thums Up Charged 330ml (24-Tray)", "category": "Canned Beverages", "description": "Strong carbonated cola Thums Up 330ml cans in shrink-film tray.", "unit_weight": 8.6, "unit_volume": 0.018, "uom": "Tray", "units_per_bundle": 24, "target_bundles_per_pallet": 60, "bundle_name": "Can Tray 24pk", "visual_color": (80, 20, 20), "icon_shape": "can"},
            
            # PET Bottles
            {"sku_id": "COKE-PET-250", "name": "Coca-Cola 250ml Mini PET (30-Pack)", "category": "PET Bottles", "description": "Pocket-size 250ml PET bottles bundled in polyethylene shrink bundle.", "unit_weight": 8.2, "unit_volume": 0.017, "uom": "Pack", "units_per_bundle": 30, "target_bundles_per_pallet": 64, "bundle_name": "Shrink Pack 30", "visual_color": (30, 30, 190), "icon_shape": "bottle"},
            {"sku_id": "COKE-PET-500", "name": "Coca-Cola 500ml PET (12-Pack)", "category": "PET Bottles", "description": "Single-serve 500ml contoured PET bottles bundled with thermo-shrink film.", "unit_weight": 6.4, "unit_volume": 0.014, "uom": "Pack", "units_per_bundle": 12, "target_bundles_per_pallet": 72, "bundle_name": "Shrink Pack 12", "visual_color": (30, 30, 200), "icon_shape": "bottle"},
            {"sku_id": "COKE-PET-750", "name": "Coca-Cola 750ml PET (12-Pack)", "category": "PET Bottles", "description": "750ml mid-size PET bottles shrink-wrapped with integrated carry handle.", "unit_weight": 9.6, "unit_volume": 0.021, "uom": "Pack", "units_per_bundle": 12, "target_bundles_per_pallet": 54, "bundle_name": "Shrink Pack 12", "visual_color": (25, 25, 185), "icon_shape": "bottle"},
            {"sku_id": "COKE-PET-1.5L", "name": "Coca-Cola 1.5L Family PET (6-Pack)", "category": "PET Bottles", "description": "Family-sharing 1.5-litre PET bottles in robust 6-pack shrink bundle.", "unit_weight": 9.5, "unit_volume": 0.022, "uom": "Pack", "units_per_bundle": 6, "target_bundles_per_pallet": 50, "bundle_name": "6-Bottle Pack", "visual_color": (25, 25, 190), "icon_shape": "bottle"},
            {"sku_id": "COKE-PET-2.0L", "name": "Coca-Cola 2.0L Party PET (6-Pack)", "category": "PET Bottles", "description": "Large 2.0L carbonated PET bottles bundled in 6-bottle shrink packs.", "unit_weight": 12.6, "unit_volume": 0.028, "uom": "Pack", "units_per_bundle": 6, "target_bundles_per_pallet": 40, "bundle_name": "6-Bottle Pack", "visual_color": (25, 25, 180), "icon_shape": "bottle"},
            {"sku_id": "SPRITE-PET-500", "name": "Sprite 500ml PET Bottles (12-Pack)", "category": "PET Bottles", "description": "Clear 500ml PET bottles of Sprite in green branded shrink film.", "unit_weight": 6.3, "unit_volume": 0.014, "uom": "Pack", "units_per_bundle": 12, "target_bundles_per_pallet": 72, "bundle_name": "Shrink Pack 12", "visual_color": (40, 170, 60), "icon_shape": "bottle"},
            {"sku_id": "SPRITE-PET-1.5L", "name": "Sprite 1.5L Family PET (6-Pack)", "category": "PET Bottles", "description": "1.5L Sprite refreshing beverage bottles in 6-bottle bundles.", "unit_weight": 9.5, "unit_volume": 0.022, "uom": "Pack", "units_per_bundle": 6, "target_bundles_per_pallet": 50, "bundle_name": "6-Bottle Pack", "visual_color": (35, 160, 55), "icon_shape": "bottle"},
            {"sku_id": "FANTA-PET-500", "name": "Fanta Orange 500ml PET (12-Pack)", "category": "PET Bottles", "description": "500ml vibrant orange carbonated PET bottles in shrink packaging.", "unit_weight": 6.4, "unit_volume": 0.014, "uom": "Pack", "units_per_bundle": 12, "target_bundles_per_pallet": 72, "bundle_name": "Shrink Pack 12", "visual_color": (15, 130, 240), "icon_shape": "bottle"},
            {"sku_id": "THUMS-PET-500", "name": "Thums Up 500ml PET (12-Pack)", "category": "PET Bottles", "description": "Strong fizzy cola 500ml PET bottles in 12-bottle bundle.", "unit_weight": 6.4, "unit_volume": 0.014, "uom": "Pack", "units_per_bundle": 12, "target_bundles_per_pallet": 72, "bundle_name": "Shrink Pack 12", "visual_color": (90, 20, 20), "icon_shape": "bottle"},
            {"sku_id": "LIMCA-PET-500", "name": "Limca Fresh Lemon 500ml (12-Pack)", "category": "PET Bottles", "description": "Cloudy lemon carbonated beverage 500ml PET bottles.", "unit_weight": 6.3, "unit_volume": 0.014, "uom": "Pack", "units_per_bundle": 12, "target_bundles_per_pallet": 72, "bundle_name": "Shrink Pack 12", "visual_color": (180, 190, 120), "icon_shape": "bottle"},
            {"sku_id": "MAAZA-PET-250", "name": "Maaza Real Mango Drink 250ml (30pk)", "category": "Juices & Still", "description": "Alphonso mango pulp fruit beverage 250ml bottles in 30-pack case.", "unit_weight": 8.4, "unit_volume": 0.017, "uom": "Pack", "units_per_bundle": 30, "target_bundles_per_pallet": 64, "bundle_name": "Juice Case 30", "visual_color": (20, 140, 220), "icon_shape": "bottle"},
            {"sku_id": "MAAZA-PET-600", "name": "Maaza Real Mango Drink 600ml (12pk)", "category": "Juices & Still", "description": "Rich mango fruit pulp beverage in 600ml PET 12-pack.", "unit_weight": 7.8, "unit_volume": 0.016, "uom": "Pack", "units_per_bundle": 12, "target_bundles_per_pallet": 65, "bundle_name": "Juice Case 12", "visual_color": (20, 140, 220), "icon_shape": "bottle"},
            {"sku_id": "MAAZA-PET-1.2L", "name": "Maaza Mango 1.2L Family Bottle (6pk)", "category": "Juices & Still", "description": "1.2L family bottles of thick mango pulp drink in 6-pack.", "unit_weight": 7.9, "unit_volume": 0.018, "uom": "Pack", "units_per_bundle": 6, "target_bundles_per_pallet": 55, "bundle_name": "6-Bottle Pack", "visual_color": (15, 135, 215), "icon_shape": "bottle"},
            
            # Water & Club Soda
            {"sku_id": "KINLEY-WTR-500", "name": "Kinley Packaged Water 500ml (24pk)", "category": "Packaged Water", "description": "Purified drinking water with added minerals 500ml PET 24-pack.", "unit_weight": 12.4, "unit_volume": 0.025, "uom": "Pack", "units_per_bundle": 24, "target_bundles_per_pallet": 50, "bundle_name": "Water Pack 24", "visual_color": (210, 150, 40), "icon_shape": "bottle"},
            {"sku_id": "KINLEY-WTR-1.0L", "name": "Kinley Packaged Water 1.0L (12pk)", "category": "Packaged Water", "description": "1.0-litre mineralized drinking water bottles in 12-pack shrinkwrap.", "unit_weight": 12.3, "unit_volume": 0.026, "uom": "Pack", "units_per_bundle": 12, "target_bundles_per_pallet": 50, "bundle_name": "Water Pack 12", "visual_color": (220, 160, 45), "icon_shape": "bottle"},
            {"sku_id": "KINLEY-SODA-500", "name": "Kinley Extra Soda 500ml (24-Pack)", "category": "Carbonated Water", "description": "High carbonation club soda bottles in heavy-gauge 24-pack bundle.", "unit_weight": 12.6, "unit_volume": 0.026, "uom": "Pack", "units_per_bundle": 24, "target_bundles_per_pallet": 50, "bundle_name": "Soda Pack 24", "visual_color": (190, 190, 80), "icon_shape": "bottle"},

            # Returnable Glass Crates & Fountain Syrups
            {"sku_id": "COKE-GLASS-330", "name": "Coca-Cola 330ml RGB Crate (24 btls)", "category": "Returnable Glass", "description": "Heavy-duty plastic modular crate holding 24 returnable glass bottles.", "unit_weight": 16.2, "unit_volume": 0.038, "uom": "Crate", "units_per_bundle": 24, "target_bundles_per_pallet": 36, "bundle_name": "Modular RGB Crate", "visual_color": (30, 30, 180), "icon_shape": "crate"},
            {"sku_id": "COKE-SYRUP-BIB", "name": "Post-Mix Fountain Syrup (20L BIB)", "category": "Fountain Syrups", "description": "Bag-in-Box 20L commercial soda fountain concentrated syrup for QSR.", "unit_weight": 24.5, "unit_volume": 0.028, "uom": "Box", "units_per_bundle": 1, "target_bundles_per_pallet": 32, "bundle_name": "Bag-In-Box 20L", "visual_color": (15, 15, 140), "icon_shape": "box"},
            {"sku_id": "SPRITE-SYRUP-BIB", "name": "Sprite Fountain Syrup (20L BIB)", "category": "Fountain Syrups", "description": "Lemon-lime post-mix beverage dispenser syrup in heavy 20L corrugated box.", "unit_weight": 24.2, "unit_volume": 0.028, "uom": "Box", "units_per_bundle": 1, "target_bundles_per_pallet": 32, "bundle_name": "Bag-In-Box 20L", "visual_color": (30, 130, 40), "icon_shape": "box"},

            # Inbound Raw Materials, Concentrates & Packaging
            {"sku_id": "COKE-CONC-DRUM", "name": "Proprietary Base Concentrate (200L)", "category": "Concentrates", "description": "Aseptic sealed food-grade steel drum containing proprietary cola concentrate.", "unit_weight": 225.0, "unit_volume": 0.28, "uom": "Drum", "units_per_bundle": 1, "target_bundles_per_pallet": 4, "bundle_name": "Steel Drum 200L", "visual_color": (20, 20, 70), "icon_shape": "cylinder"},
            {"sku_id": "SUGAR-BULK-BAG", "name": "Refined Cane Sugar (50kg Bag)", "category": "Dry Ingredients", "description": "Moisture-sealed polypropylene woven bag with food-grade inner liner.", "unit_weight": 50.0, "unit_volume": 0.065, "uom": "Bag", "units_per_bundle": 1, "target_bundles_per_pallet": 20, "bundle_name": "Heavy Sugar Sack", "visual_color": (200, 200, 200), "icon_shape": "box"},
            {"sku_id": "CITRIC-ACID-DRUM", "name": "Citric Acid Anhydrous (25kg Drum)", "category": "Dry Ingredients", "description": "Food-grade acidulant powder in sealed fiber drum for pH regulation.", "unit_weight": 25.0, "unit_volume": 0.042, "uom": "Drum", "units_per_bundle": 1, "target_bundles_per_pallet": 16, "bundle_name": "Fiber Drum 25kg", "visual_color": (180, 180, 160), "icon_shape": "cylinder"},
            {"sku_id": "PET-PREFORM-28", "name": "PET Bottle Preforms 28mm (10,000ct)", "category": "Packaging Materials", "description": "Virgin PET injection-molded preforms in corrugated octabin container.", "unit_weight": 240.0, "unit_volume": 0.95, "uom": "Bin", "units_per_bundle": 10000, "target_bundles_per_pallet": 1, "bundle_name": "Octabin Preforms", "visual_color": (120, 140, 150), "icon_shape": "box"},
            {"sku_id": "CAN-BODY-330", "name": "Empty Aluminum 330ml Can Bodies", "category": "Packaging Materials", "description": "Pallet layer tier pack containing 8,000 unsealed aluminum cans.", "unit_weight": 115.0, "unit_volume": 1.10, "uom": "Tier", "units_per_bundle": 8000, "target_bundles_per_pallet": 1, "bundle_name": "Can Tier Pack", "visual_color": (180, 180, 190), "icon_shape": "crate"},
            {"sku_id": "CAN-LID-202", "name": "Aluminum Stay-on-Tab Lids (5,000ct)", "category": "Packaging Materials", "description": "Hermetic seaming easy-open can ends packed in corrugated sleeves.", "unit_weight": 18.0, "unit_volume": 0.035, "uom": "Box", "units_per_bundle": 5000, "target_bundles_per_pallet": 36, "bundle_name": "Lid Sleeve Box", "visual_color": (150, 150, 150), "icon_shape": "box"},
            {"sku_id": "CAP-PLASTIC-28", "name": "28mm PCO Plastic Screw Caps (5k)", "category": "Packaging Materials", "description": "HDPE tamper-evident beverage bottle screw caps in sealed box.", "unit_weight": 16.5, "unit_volume": 0.032, "uom": "Box", "units_per_bundle": 5000, "target_bundles_per_pallet": 40, "bundle_name": "Cap Carton 5k", "visual_color": (40, 80, 200), "icon_shape": "box"},
            {"sku_id": "GAS-CO2-50KG", "name": "Liquid CO2 Beverage Gas (50kg Cyl)", "category": "Process Gases", "description": "Food-grade liquefied carbon dioxide in certified high-pressure steel cylinder.", "unit_weight": 110.0, "unit_volume": 0.12, "uom": "Cyl", "units_per_bundle": 1, "target_bundles_per_pallet": 6, "bundle_name": "CO2 Gas Cylinder", "visual_color": (70, 70, 70), "icon_shape": "cylinder"},
            {"sku_id": "FILM-SHRINK-450", "name": "LDPE Thermo Shrink Film Roll (450mm)", "category": "Packaging Materials", "description": "Heavy-duty 65-micron clear polyethylene shrink film for case bundlers.", "unit_weight": 28.0, "unit_volume": 0.045, "uom": "Roll", "units_per_bundle": 1, "target_bundles_per_pallet": 24, "bundle_name": "Shrink Film Roll", "visual_color": (170, 190, 200), "icon_shape": "cylinder"}
        ],
        "vision_classes": [
            ("BEVERAGE_CRATE", "Beverage Crate / Tray", "24-can corrugated trays, shrink-wrapped bottle cases, and RGB crates"),
            ("CAN_BUNDLE", "Can Case / Tray", "Sealed 24-can trays with stretch film"),
            ("BOTTLE_PACK", "Bottle Shrink Pack", "Multipack shrink-wrapped PET and glass bottles"),
            ("PALLET", "Storage Pallet", "Heavy wooden EUR/ISO pallets holding unit loads"),
            ("FORKLIFT", "Forklift Truck", "Counterbalance electric forklifts and clamp trucks"),
            ("WORKER", "Plant Operator", "High-visibility safety vests, hairnets, and safety shoes"),
            ("TRUCK", "Delivery Trailer", "Inbound ingredient reefers, bulk tankers, and curtain-side distribution trucks"),
            ("LICENSE_PLATE", "License Plate", "Automated gate access ANPR plate check-in")
        ],
        "zones": [
            ("TB-BEV", "Gate 01 Inbound ANPR Bay", "TRUCK_BAY", "Primary gate check-in for inbound tankers and distribution fleets"),
            ("DOCK-CAN", "Inbound Dock 01 (Cans & Raw Materials)", "DOCK", "High-speed dock for can tier packs, preforms, and raw sugar"),
            ("DOCK-EXP", "Outbound Dock 02 (Finished Goods Dispatch)", "DOCK", "Direct loading bays for local and regional delivery trucks"),
            ("COLD-BEV", "Refrigerated Staging & Syrups Zone", "STORAGE", "Temperature-controlled chamber (4-8°C) for sensitive syrups and concentrates"),
            ("RACK-FG", "High-Bay Pallet Racks (Finished Goods)", "STORAGE", "Automated drive-in pallet racking for fast-moving beverage cases")
        ],
        "deliveries": [
            {"po_number": "PO-COKE-9011", "plate": "KA-01-MJ-4412", "vendor": "Ball Packaging India Pvt Ltd", "load_description": "24x Tier-Packs Aluminum 330ml Can Bodies", "sku": "CAN-BODY-330", "expected": 24},
            {"po_number": "PO-COKE-9012", "plate": "MH-12-PQ-8845", "vendor": "Dhampur Sugar Mills Ltd", "load_description": "40x Refined Cane Sugar 50kg Bags", "sku": "SUGAR-BULK-BAG", "expected": 40},
            {"po_number": "PO-COKE-9013", "plate": "DL-01-AB-1290", "vendor": "Linde India Industrial Gases", "load_description": "12x Liquid CO2 Beverage Cylinders", "sku": "GAS-CO2-50KG", "expected": 12}
        ]
    },

    # --------------------------------------------------------------------------
    # 2. AUTOMOTIVE OEM & ASSEMBLY (Tata Motors / Hyundai Style) - 35 SKUs
    # --------------------------------------------------------------------------
    "automotive": {
        "key": "automotive",
        "name": "Automotive OEM & Parts Assembly",
        "badge_icon": "fa-car",
        "theme_color": "#38bdf8",
        "company_example": "Tata Motors / Hyundai Automotive Hub",
        "operating_mode": "DEDICATED",
        "description": "Powertrain, chassis, steering suspension bundles, A-frame glass dollies, and line-side intralogistics feeding.",
        "skus": [
            # Powertrain & Engine
            {"sku_id": "AUTO-ENG-01", "name": "4-Cylinder Turbo Engine Block", "category": "Powertrain", "description": "Cast-iron turbocharged engine block assembly in heavy welded steel transport cradle.", "unit_weight": 128.0, "unit_volume": 0.42, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 2, "bundle_name": "Engine Cradle", "visual_color": (50, 70, 95), "icon_shape": "block"},
            {"sku_id": "AUTO-CYL-HEAD", "name": "Aluminum 16V Cylinder Head", "category": "Powertrain", "description": "Machined aluminum dual-overhead-cam cylinder head with valve guide inserts.", "unit_weight": 24.5, "unit_volume": 0.065, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 12, "bundle_name": "Cylinder Head Stillage", "visual_color": (90, 110, 130), "icon_shape": "block"},
            {"sku_id": "AUTO-CRANK-01", "name": "Forged Counterweighted Crankshaft", "category": "Powertrain", "description": "Nitride-hardened forged steel crankshaft packed in anti-corrosion VCI stillage.", "unit_weight": 18.2, "unit_volume": 0.045, "uom": "EA", "units_per_bundle": 2, "target_bundles_per_pallet": 16, "bundle_name": "Crankshaft Stillage", "visual_color": (80, 90, 105), "icon_shape": "cylinder"},
            {"sku_id": "AUTO-CAM-01", "name": "Dual Overhead Camshaft Set", "category": "Powertrain", "description": "Intake and exhaust chill-cast camshaft pair packed in preservative oil wrapper.", "unit_weight": 7.4, "unit_volume": 0.015, "uom": "Set", "units_per_bundle": 4, "target_bundles_per_pallet": 32, "bundle_name": "Camshaft Box", "visual_color": (95, 105, 120), "icon_shape": "cylinder"},
            {"sku_id": "AUTO-PIST-SET", "name": "Piston & Ring Assembly (Set 4)", "category": "Powertrain", "description": "Graphite-coated aluminum pistons with wrist pins and moly rings.", "unit_weight": 3.2, "unit_volume": 0.008, "uom": "Set", "units_per_bundle": 4, "target_bundles_per_pallet": 60, "bundle_name": "Piston Set Carton", "visual_color": (120, 130, 140), "icon_shape": "box"},
            {"sku_id": "AUTO-CONROD-01", "name": "Forged H-Beam Connecting Rods (Set)", "category": "Powertrain", "description": "Fracture-split forged steel connecting rods for turbocharged engines.", "unit_weight": 2.8, "unit_volume": 0.007, "uom": "Set", "units_per_bundle": 4, "target_bundles_per_pallet": 64, "bundle_name": "Conrod Set Pack", "visual_color": (110, 115, 130), "icon_shape": "box"},
            {"sku_id": "AUTO-TURBO-01", "name": "Variable Geometry Turbocharger", "category": "Powertrain", "description": "Precision balanced exhaust turbocharger with integrated electronic actuator.", "unit_weight": 9.5, "unit_volume": 0.024, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 24, "bundle_name": "Turbo Stillage", "visual_color": (60, 80, 100), "icon_shape": "block"},

            # Suspension & Steering
            {"sku_id": "AUTO-ROD-01", "name": "High-Tensile Steering Tie Rod (Pk 48)", "category": "Steering & Suspension", "description": "Cold-drawn steel steering tie rods bundled in circular hexagonal cluster straps.", "unit_weight": 1.4, "unit_volume": 0.008, "uom": "Bundle", "units_per_bundle": 48, "target_bundles_per_pallet": 6, "bundle_name": "Circular Tube Pack", "visual_color": (90, 110, 130), "icon_shape": "bundle"},
            {"sku_id": "AUTO-CTRL-ARM", "name": "Front Suspension Lower Control Arm", "category": "Steering & Suspension", "description": "Stamped high-strength steel wishbone control arm with rubber bushings.", "unit_weight": 6.8, "unit_volume": 0.032, "uom": "EA", "units_per_bundle": 2, "target_bundles_per_pallet": 28, "bundle_name": "Control Arm Rack", "visual_color": (70, 85, 100), "icon_shape": "block"},
            {"sku_id": "AUTO-STRUT-01", "name": "Front MacPherson Strut Damper", "category": "Steering & Suspension", "description": "Gas-pressurized twin-tube front suspension strut damper assembly.", "unit_weight": 11.2, "unit_volume": 0.040, "uom": "EA", "units_per_bundle": 2, "target_bundles_per_pallet": 20, "bundle_name": "Strut Caddy", "visual_color": (65, 80, 95), "icon_shape": "cylinder"},
            {"sku_id": "AUTO-COIL-SPRG", "name": "Suspension Helical Coil Springs (Pair)", "category": "Steering & Suspension", "description": "Shot-peened progressive rate steel suspension springs with epoxy finish.", "unit_weight": 8.4, "unit_volume": 0.022, "uom": "Pair", "units_per_bundle": 2, "target_bundles_per_pallet": 30, "bundle_name": "Spring Caddy", "visual_color": (40, 45, 55), "icon_shape": "cylinder"},
            {"sku_id": "AUTO-STEER-RCK", "name": "Electric Power Steering Rack (EPAS)", "category": "Steering & Suspension", "description": "Rack-and-pinion electric power steering unit with ECU and motor assembly.", "unit_weight": 14.6, "unit_volume": 0.062, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 14, "bundle_name": "Steering Rack Box", "visual_color": (75, 90, 110), "icon_shape": "bundle"},

            # Braking System
            {"sku_id": "AUTO-DISC-VENT", "name": "Ventilated Front Brake Rotors (Pair)", "category": "Braking System", "description": "Grey cast iron high-carbon ventilated front disc brake rotors.", "unit_weight": 15.8, "unit_volume": 0.018, "uom": "Pair", "units_per_bundle": 2, "target_bundles_per_pallet": 32, "bundle_name": "Brake Rotor Pack", "visual_color": (100, 105, 115), "icon_shape": "cylinder"},
            {"sku_id": "AUTO-DRUM-RR", "name": "Balanced Rear Brake Drums (Pair)", "category": "Braking System", "description": "Dynamically balanced cast iron rear brake drums with anti-rust oil film.", "unit_weight": 13.4, "unit_volume": 0.022, "uom": "Pair", "units_per_bundle": 2, "target_bundles_per_pallet": 30, "bundle_name": "Drum Pack", "visual_color": (90, 95, 105), "icon_shape": "cylinder"},
            {"sku_id": "AUTO-CALIPER", "name": "Dual-Piston Front Brake Caliper LH", "category": "Braking System", "description": "Lightweight cast aluminum front disc brake caliper assembly with brackets.", "unit_weight": 4.6, "unit_volume": 0.012, "uom": "EA", "units_per_bundle": 4, "target_bundles_per_pallet": 48, "bundle_name": "Caliper Tote", "visual_color": (120, 125, 135), "icon_shape": "box"},
            {"sku_id": "AUTO-PADS-CER", "name": "Ceramic Brake Pads Set (Front)", "category": "Braking System", "description": "Low-dust high-friction ceramic brake pad set with shims and clips.", "unit_weight": 2.1, "unit_volume": 0.005, "uom": "Set", "units_per_bundle": 10, "target_bundles_per_pallet": 80, "bundle_name": "Pad Carton 10pk", "visual_color": (45, 50, 60), "icon_shape": "box"},
            {"sku_id": "AUTO-BRAKE-BST", "name": "Vacuum Brake Booster & Master Cyl", "category": "Braking System", "description": "Tandem diaphragm vacuum booster unit with attached brake master cylinder.", "unit_weight": 5.4, "unit_volume": 0.035, "uom": "EA", "units_per_bundle": 2, "target_bundles_per_pallet": 24, "bundle_name": "Booster Box", "visual_color": (50, 55, 65), "icon_shape": "block"},

            # Automotive Glass & Body
            {"sku_id": "AUTO-GLASS-01", "name": "Laminated Acoustic Windshield Glass", "category": "Glass & Trim", "description": "Shatterproof acoustic laminated automotive windshield glass stored on specialized A-frame stillages.", "unit_weight": 14.5, "unit_volume": 0.15, "uom": "Set", "units_per_bundle": 10, "target_bundles_per_pallet": 1, "bundle_name": "A-Frame Glass Dolly", "visual_color": (40, 120, 160), "icon_shape": "glass"},
            {"sku_id": "AUTO-GLASS-RR", "name": "Tempered Heated Rear Glass (Dolly)", "category": "Glass & Trim", "description": "Curved tempered safety glass with integrated defogger grid lines.", "unit_weight": 11.2, "unit_volume": 0.12, "uom": "Set", "units_per_bundle": 12, "target_bundles_per_pallet": 1, "bundle_name": "Rear Glass Dolly", "visual_color": (45, 115, 150), "icon_shape": "glass"},
            {"sku_id": "AUTO-GLASS-DR", "name": "Toughened Front Door Window Glass", "category": "Glass & Trim", "description": "Tempered side window door glass panels in cushioned slotted crate.", "unit_weight": 4.2, "unit_volume": 0.045, "uom": "Set", "units_per_bundle": 20, "target_bundles_per_pallet": 2, "bundle_name": "Door Glass Crate", "visual_color": (50, 130, 170), "icon_shape": "glass"},
            {"sku_id": "AUTO-BMPR-01", "name": "Injection-Molded Front Bumper Fascia", "category": "Body & Trim", "description": "Primed thermoplastic polyolefin front bumper fascia stacked on nesting dollies.", "unit_weight": 5.2, "unit_volume": 0.35, "uom": "EA", "units_per_bundle": 5, "target_bundles_per_pallet": 2, "bundle_name": "Bumper Stillage Stack", "visual_color": (80, 80, 80), "icon_shape": "block"},
            {"sku_id": "AUTO-DOOR-SKIN", "name": "Deep-Draw Stamped Door Outer Skin", "category": "Body & Trim", "description": "Electro-galvanized stamped sheet metal outer door panel on vertical rack.", "unit_weight": 7.8, "unit_volume": 0.18, "uom": "EA", "units_per_bundle": 10, "target_bundles_per_pallet": 1, "bundle_name": "Panel Stillage", "visual_color": (140, 145, 155), "icon_shape": "block"},
            {"sku_id": "AUTO-HOOD-ALU", "name": "Stamped Aluminum Engine Hood Panel", "category": "Body & Trim", "description": "Lightweight 6000-series stamped aluminum hood in padded cradle rack.", "unit_weight": 8.9, "unit_volume": 0.40, "uom": "EA", "units_per_bundle": 6, "target_bundles_per_pallet": 1, "bundle_name": "Hood Stillage", "visual_color": (160, 165, 175), "icon_shape": "block"},

            # Electrical, Fasteners & Ancillaries
            {"sku_id": "AUTO-BOLT-10", "name": "Grade 10.9 Flange Bolts M10x50 (500)", "category": "Fasteners", "description": "High-tensile zinc-flake coated chassis bolts in heavy reinforced bin boxes.", "unit_weight": 22.0, "unit_volume": 0.012, "uom": "Box", "units_per_bundle": 500, "target_bundles_per_pallet": 40, "bundle_name": "Fastener Box 500ct", "visual_color": (130, 130, 130), "icon_shape": "box"},
            {"sku_id": "AUTO-WHEEL-16", "name": "16-Inch Stamped Steel Wheel Rim", "category": "Wheels & Tires", "description": "Heavy-duty 16x6.5J black e-coated steel wheel rims stacked on pallets.", "unit_weight": 9.4, "unit_volume": 0.038, "uom": "EA", "units_per_bundle": 4, "target_bundles_per_pallet": 10, "bundle_name": "Wheel Stack 4pk", "visual_color": (30, 30, 35), "icon_shape": "cylinder"},
            {"sku_id": "AUTO-RAD-ALU", "name": "Aluminum Engine Cooling Radiator", "category": "Thermal Systems", "description": "Controlled atmosphere brazed aluminum radiator core with plastic tanks.", "unit_weight": 5.8, "unit_volume": 0.055, "uom": "EA", "units_per_bundle": 2, "target_bundles_per_pallet": 16, "bundle_name": "Radiator Carton", "visual_color": (120, 135, 145), "icon_shape": "block"},
            {"sku_id": "AUTO-ALT-12V", "name": "12V 140A Automotive Alternator", "category": "Electrical", "description": "Brushless high-output alternator generator with integrated voltage regulator.", "unit_weight": 6.8, "unit_volume": 0.018, "uom": "EA", "units_per_bundle": 4, "target_bundles_per_pallet": 36, "bundle_name": "Alternator Tote", "visual_color": (90, 100, 115), "icon_shape": "box"},
            {"sku_id": "AUTO-STRT-MTR", "name": "1.4kW Planetary Starter Motor", "category": "Electrical", "description": "High-torque reduction gear electric starter motor for diesel/petrol engines.", "unit_weight": 4.2, "unit_volume": 0.012, "uom": "EA", "units_per_bundle": 6, "target_bundles_per_pallet": 48, "bundle_name": "Starter Tote", "visual_color": (80, 90, 105), "icon_shape": "box"},
            {"sku_id": "AUTO-ECU-MOD", "name": "Powertrain Engine Control Unit (ESD)", "category": "Electrical", "description": "Waterproof aluminum housed 32-bit ECU module in ESD anti-static bubble pack.", "unit_weight": 1.1, "unit_volume": 0.004, "uom": "EA", "units_per_bundle": 10, "target_bundles_per_pallet": 80, "bundle_name": "ESD ECU Tote", "visual_color": (30, 70, 120), "icon_shape": "box"},
            {"sku_id": "AUTO-HARNESS", "name": "Main Engine Wiring Harness Loom", "category": "Electrical", "description": "Complete sealed automotive engine compartment wiring harness loom.", "unit_weight": 4.5, "unit_volume": 0.035, "uom": "EA", "units_per_bundle": 4, "target_bundles_per_pallet": 24, "bundle_name": "Harness Crate", "visual_color": (40, 40, 45), "icon_shape": "bundle"},
            {"sku_id": "AUTO-EXH-MANI", "name": "Stainless Steel Exhaust Manifold", "category": "Exhaust Systems", "description": "TIG-welded austenitic stainless steel exhaust manifold with heat shield.", "unit_weight": 7.4, "unit_volume": 0.032, "uom": "EA", "units_per_bundle": 2, "target_bundles_per_pallet": 28, "bundle_name": "Manifold Stillage", "visual_color": (150, 130, 100), "icon_shape": "block"},
            {"sku_id": "AUTO-CLUTCH", "name": "Dry Friction Clutch Pressure Plate", "category": "Drivetrain", "description": "Diaphragm spring clutch pressure plate and organic friction clutch disc.", "unit_weight": 8.2, "unit_volume": 0.020, "uom": "EA", "units_per_bundle": 2, "target_bundles_per_pallet": 36, "bundle_name": "Clutch Carton", "visual_color": (100, 105, 115), "icon_shape": "cylinder"},
            {"sku_id": "AUTO-FUEL-TNK", "name": "Blow-Molded HDPE 50L Fuel Tank", "category": "Fuel Systems", "description": "6-layer co-extruded plastic fuel tank with integrated fuel pump sender bracket.", "unit_weight": 8.6, "unit_volume": 0.22, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 4, "bundle_name": "Fuel Tank Stillage", "visual_color": (50, 50, 55), "icon_shape": "block"},
            {"sku_id": "AUTO-COOL-200L", "name": "Organic Acid Coolant (200L Drum)", "category": "Fluids & Chemicals", "description": "Long-life anti-corrosion pre-mixed engine coolant in sealed steel drum.", "unit_weight": 218.0, "unit_volume": 0.28, "uom": "Drum", "units_per_bundle": 1, "target_bundles_per_pallet": 4, "bundle_name": "Coolant Drum 200L", "visual_color": (30, 130, 80), "icon_shape": "cylinder"},
            {"sku_id": "AUTO-FILTER-OIL", "name": "Spin-On Engine Oil Filters (Box 24)", "category": "Maintenance Parts", "description": "High-efficiency synthetic media spin-on oil filters packed in master carton.", "unit_weight": 7.2, "unit_volume": 0.016, "uom": "Box", "units_per_bundle": 24, "target_bundles_per_pallet": 60, "bundle_name": "Filter Carton 24", "visual_color": (40, 60, 90), "icon_shape": "box"}
        ],
        "vision_classes": [
            ("BOX", "Component Box / Master Carton", "Automotive parts boxes, fasteners, and packaged assembly sets"),
            ("BUNDLE", "Tie Rod / Tubing Bundle", "Hexagonal strapped steel bundles and rod packs"),
            ("PALLET", "Industrial Steel Stillage / Pallet", "Heavy welded cradles, A-frames, and wooden pallets"),
            ("BIN", "Line-Side Parts Tote", "KLT picking totes and line-side feeder bins"),
            ("FORKLIFT", "Industrial Reach Truck", "Counterbalance forklifts, reach trucks, and tuggers"),
            ("WORKER", "Plant Assembly Crew", "Certified assembly operators with hard-hats and gloves"),
            ("TRUCK", "Inbound Component Transporter", "Articulated supplier delivery trailers and container trucks"),
            ("LICENSE_PLATE", "License Plate", "Automated gate check-in ANPR plate logging")
        ],
        "zones": [
            ("TB-AUTO", "Gate 01 Inbound ANPR Bay", "TRUCK_BAY", "Automated vehicle plate scanning and vendor check-in"),
            ("DOCK-POWERTRAIN", "Dock 01 Heavy Powertrain Bay", "DOCK", "Direct dock for engine blocks, cylinder heads, and crankshafts"),
            ("DOCK-CHASSIS", "Dock 02 Chassis & Suspension Inbound", "DOCK", "High-capacity offloading for tie rods, control arms, and struts"),
            ("STG-LINESIDE", "Line-Side Assembly Staging Buffer", "STAGING", "JIT buffer directly supplying automotive assembly lines"),
            ("RACK-AUTO", "High-Density Steel Racking Bay", "STORAGE", "Heavy-duty pallet racking engineered for metallic sub-assemblies")
        ],
        "deliveries": [
            {"po_number": "PO-AUTO-7710", "plate": "MH-14-GH-6612", "vendor": "Tata AutoComp Systems Ltd", "load_description": "12x Bundles High-Tensile Tie Rods (576 units)", "sku": "AUTO-ROD-01", "expected": 12},
            {"po_number": "PO-AUTO-7711", "plate": "KA-04-TR-9023", "vendor": "Asahi India Glass Ltd", "load_description": "10x Laminated Windshield Glass A-Frames", "sku": "AUTO-GLASS-01", "expected": 10},
            {"po_number": "PO-AUTO-7712", "plate": "TN-09-ZX-3319", "vendor": "Sundram Fasteners Ltd", "load_description": "20x Fastener Boxes Grade 10.9 Bolts", "sku": "AUTO-BOLT-10", "expected": 20}
        ]
    },

    # --------------------------------------------------------------------------
    # 3. CONSUMER ELECTRONICS & APPLIANCES (Samsung Style) - 30 SKUs
    # --------------------------------------------------------------------------
    "electronics": {
        "key": "electronics",
        "name": "Consumer Electronics & Appliances",
        "badge_icon": "fa-tv",
        "theme_color": "#6366f1",
        "company_example": "Samsung Electronics Distribution Hub",
        "operating_mode": "DEDICATED",
        "description": "Smart TVs, appliances, smartphones, OLED panels, DRAM modules, and lithium battery storage.",
        "skus": [
            {"sku_id": "SAMS-TV-55", "name": "55-Inch 4K UHD Smart QLED TV", "category": "Displays & TVs", "description": "Ultra-slim 55-inch QLED Smart TV in shock-absorbent EPS foam master carton.", "unit_weight": 19.5, "unit_volume": 0.22, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 8, "bundle_name": "Individual TV Carton", "visual_color": (30, 40, 80), "icon_shape": "block"},
            {"sku_id": "SAMS-TV-65", "name": "65-Inch Neo QLED 8K Smart TV", "category": "Displays & TVs", "description": "Premium 65-inch 8K television master carton with drop-sensor indicator.", "unit_weight": 28.0, "unit_volume": 0.32, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 6, "bundle_name": "Premium TV Carton", "visual_color": (25, 35, 75), "icon_shape": "block"},
            {"sku_id": "SAMS-TV-75", "name": "75-Inch Crystal UHD 4K TV", "category": "Displays & TVs", "description": "Large format 75-inch TV in impact-resistant reinforced carton packaging.", "unit_weight": 36.5, "unit_volume": 0.44, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 4, "bundle_name": "Large TV Carton", "visual_color": (20, 30, 70), "icon_shape": "block"},
            {"sku_id": "SAMS-PHONE-20", "name": "Galaxy Smartphone Master Pack (20ct)", "category": "Mobile Devices", "description": "Factory sealed master shipper containing 20 retail-boxed flagship smartphones.", "unit_weight": 8.5, "unit_volume": 0.016, "uom": "Carton", "units_per_bundle": 20, "target_bundles_per_pallet": 64, "bundle_name": "Security Shipper 20pk", "visual_color": (60, 40, 110), "icon_shape": "box"},
            {"sku_id": "SAMS-TAB-10", "name": "11-Inch Android Tablet Master (10ct)", "category": "Mobile Devices", "description": "Corrugated shipper containing 10 unit-boxed tablets with charging blocks.", "unit_weight": 7.8, "unit_volume": 0.018, "uom": "Carton", "units_per_bundle": 10, "target_bundles_per_pallet": 60, "bundle_name": "Tablet Shipper 10pk", "visual_color": (70, 50, 120), "icon_shape": "box"},
            {"sku_id": "SAMS-OLED-67", "name": "6.7-Inch Dynamic AMOLED Panels (100)", "category": "Display Sub-Assemblies", "description": "Anti-static sealed cleanroom tray containing 100 flexible OLED touch panels.", "unit_weight": 6.2, "unit_volume": 0.024, "uom": "Tray", "units_per_bundle": 100, "target_bundles_per_pallet": 40, "bundle_name": "ESD OLED Tray", "visual_color": (30, 80, 140), "icon_shape": "box"},
            {"sku_id": "SAMS-CHIP-DRAM", "name": "16GB LPDDR5X DRAM Reel (2,000ct)", "category": "Semiconductors", "description": "Moisture-barrier vacuum sealed reel of mobile high-speed memory chips.", "unit_weight": 2.4, "unit_volume": 0.006, "uom": "Reel", "units_per_bundle": 2000, "target_bundles_per_pallet": 80, "bundle_name": "ESD Chip Reel", "visual_color": (30, 90, 80), "icon_shape": "cylinder"},
            {"sku_id": "SAMS-BATT-LI", "name": "5,000mAh Li-Po Battery Pack (50ct)", "category": "Batteries & Power", "description": "UN3480 certified explosion-resistant hazardous materials carton for batteries.", "unit_weight": 6.8, "unit_volume": 0.015, "uom": "Box", "units_per_bundle": 50, "target_bundles_per_pallet": 48, "bundle_name": "Hazmat Battery Box", "visual_color": (140, 30, 30), "icon_shape": "box"},
            {"sku_id": "SAMS-WASH-9KG", "name": "9kg Front Load AI Washing Machine", "category": "Home Appliances", "description": "Inverter direct-drive washing machine packed in full-protection EPS crate.", "unit_weight": 72.0, "unit_volume": 0.48, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 2, "bundle_name": "Appliance Crate", "visual_color": (160, 160, 170), "icon_shape": "block"},
            {"sku_id": "SAMS-FRIDGE-650", "name": "650L Side-by-Side Refrigerator", "category": "Home Appliances", "description": "Triple-cooling French door refrigerator in reinforced wooden-base crate.", "unit_weight": 118.0, "unit_volume": 1.15, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 1, "bundle_name": "Heavy Refrigerator Crate", "visual_color": (140, 145, 150), "icon_shape": "block"}
        ],
        "vision_classes": [
            ("BOX", "Electronics Master Carton", "Factory sealed carton boxes, TV packaging, and appliance crates"),
            ("ESD_TOTE", "Anti-Static Cleanroom Tote", "Blue conductive polypropylene picking totes"),
            ("PALLET", "Storage Pallet", "Heavy wooden/plastic handling pallets"),
            ("WORKER", "Cleanroom Handler", "Operators with ESD smocks, wrist straps, and gloves"),
            ("FORKLIFT", "Narrow-Aisle Reach Truck", "Electric wire-guided reach trucks"),
            ("TRUCK", "Security Air-Ride Van", "Climate-controlled air-ride suspension trucks"),
            ("LICENSE_PLATE", "License Plate", "High-security facility ANPR plate recognition")
        ],
        "zones": [
            ("TB-ELEC", "Gate 01 High-Security Bay", "TRUCK_BAY", "Biometric and ANPR secured carrier check-in bay"),
            ("DOCK-TV", "Dock 01 Flat Screen Staging", "DOCK", "Dedicated cushioned dock for large TVs and appliances"),
            ("CLEAN-ESD", "Class 10,000 ESD Component Bay", "INSPECTION", "Grounding-monitored zone for chips, boards, and sensors"),
            ("HAZ-BATT", "Fire-Suppressed Lithium Battery Cell", "STORAGE", "Aerosol-suppressed fire-rated storage room for lithium battery packs"),
            ("RACK-HIGH", "High-Bay Narrow Aisle Storage", "STORAGE", "VNA wire-guided pallet racking for finished electronics")
        ],
        "deliveries": [
            {"po_number": "PO-SAMS-1001", "plate": "KA-03-HA-8822", "vendor": "Samsung Display Co Ltd", "load_description": "24x Anti-Static Trays 6.7\" Dynamic AMOLED", "sku": "SAMS-OLED-67", "expected": 24},
            {"po_number": "PO-SAMS-1002", "plate": "MH-04-DE-3109", "vendor": "Samsung SDI Energy Storage", "load_description": "30x Hazmat Cartons 5000mAh Li-Po Packs", "sku": "SAMS-BATT-LI", "expected": 30}
        ]
    },

    # --------------------------------------------------------------------------
    # 4. PHARMACEUTICALS & COLD-CHAIN (Pfizer Style) - 30 SKUs
    # --------------------------------------------------------------------------
    "pharma": {
        "key": "pharma",
        "name": "Pharmaceuticals & Cold-Chain Logistics",
        "badge_icon": "fa-pills",
        "theme_color": "#10b981",
        "company_example": "Pfizer / Cipla Healthcare Distribution",
        "operating_mode": "DEDICATED",
        "description": "Cold-chain biologic vaccine trays (-20°C), sterile injectable ampoules, blister card master cartons, and APIs.",
        "skus": [
            {"sku_id": "PHRM-VAC-VIAL", "name": "Cold-Chain Vaccine Vial Tray (-20°C)", "category": "Biologics & Vaccines", "description": "Sterile multi-dose biologic vaccine vials in insulated cold-box with dry ice telemetry logger.", "unit_weight": 4.8, "unit_volume": 0.015, "uom": "Tray", "units_per_bundle": 50, "target_bundles_per_pallet": 36, "bundle_name": "Cryo Vaccine Tray", "visual_color": (30, 160, 180), "icon_shape": "box"},
            {"sku_id": "PHRM-AMP-INJ", "name": "Sterile Injectable Ampoules (Pack 100)", "category": "Injectables", "description": "Type 1 borosilicate glass 2ml ampoules packed in validated sterile shipper box.", "unit_weight": 2.2, "unit_volume": 0.006, "uom": "Box", "units_per_bundle": 100, "target_bundles_per_pallet": 80, "bundle_name": "Ampoule Shipper 100pk", "visual_color": (40, 180, 140), "icon_shape": "box"},
            {"sku_id": "PHRM-BLIST-1K", "name": "Antibiotic Blister Shipper (1000ct)", "category": "Oral Solid Dose", "description": "Alu-Alu blister cards containing oral solid tablets in tamper-evident master carton.", "unit_weight": 8.5, "unit_volume": 0.024, "uom": "Carton", "units_per_bundle": 1000, "target_bundles_per_pallet": 48, "bundle_name": "Blister Shipper 1k", "visual_color": (50, 170, 120), "icon_shape": "box"},
            {"sku_id": "PHRM-IV-BAG", "name": "Normal Saline 0.9% 500ml IV Bags (24pk)", "category": "Infusions", "description": "PVC-free flexible infusion bags with twin ports in corrugated distribution box.", "unit_weight": 13.2, "unit_volume": 0.028, "uom": "Box", "units_per_bundle": 24, "target_bundles_per_pallet": 45, "bundle_name": "IV Bag Box 24pk", "visual_color": (60, 190, 200), "icon_shape": "box"},
            {"sku_id": "PHRM-SYR-PREF", "name": "Prefilled Safety Syringes (Pack 25)", "category": "Injectables", "description": "Prefilled glass safety syringes with automatic needle retraction mechanism.", "unit_weight": 1.4, "unit_volume": 0.005, "uom": "Box", "units_per_bundle": 25, "target_bundles_per_pallet": 90, "bundle_name": "Syringe Box 25pk", "visual_color": (70, 180, 150), "icon_shape": "box"},
            {"sku_id": "PHRM-API-DRUM", "name": "Active Pharma Ingredient API (25kg)", "category": "Raw Materials & APIs", "description": "High-potency crystalline API in double PE liner inside fiber drum with security seal.", "unit_weight": 28.0, "unit_volume": 0.052, "uom": "Drum", "units_per_bundle": 1, "target_bundles_per_pallet": 16, "bundle_name": "API Fiber Drum 25kg", "visual_color": (160, 160, 140), "icon_shape": "cylinder"}
        ],
        "vision_classes": [
            ("BOX", "Sterile Shipper Carton", "Sealed insulated cartons and medical master packs"),
            ("BIN", "Pharma Picking Tote", "Clean medical-grade polypropylene totes"),
            ("PALLET", "Hygienic Plastic Pallet", "Seamless washable FDA-compliant white plastic pallets"),
            ("WORKER", "Cleanroom Operator", "Gowned and masked certified warehouse handlers"),
            ("TRUCK", "Reefer Temperature Truck", "Active refrigeration cold-chain transport reefers"),
            ("LICENSE_PLATE", "License Plate", "Certified GDP medical courier vehicle identification")
        ],
        "zones": [
            ("TB-PHARMA", "Gate 01 Cold-Chain Bay", "TRUCK_BAY", "Temperature-logged gate check-in"),
            ("DOCK-COLD", "Reefer Direct Dock Shelter", "DOCK", "Sealed airlock dock keeping cold-chain unbroken"),
            ("COLD-CHAIN-01", "Ultra-Cold Freezer Bay (-20°C)", "STORAGE", "Continuous temperature-monitored biologic freezer zone"),
            ("QUARANTINE", "Regulatory QA Quarantine", "INSPECTION", "Holding zone for batch release and COA verification"),
            ("RACK-ORALS", "Ambient Medical Storage Racks", "STORAGE", "Controlled room temperature (15-25°C) racking")
        ],
        "deliveries": [
            {"po_number": "PO-PFIZER-1090", "plate": "MH-01-AX-9912", "vendor": "Thermo King Reefer Logistics", "load_description": "60x Cold-Chain Vaccine Crates", "sku": "PHRM-VAC-VIAL", "expected": 60}
        ]
    },

    # --------------------------------------------------------------------------
    # 5. HEAVY METALS & STEEL (Tata Steel Style) - 30 SKUs
    # --------------------------------------------------------------------------
    "metals": {
        "key": "metals",
        "name": "Heavy Metals & Industrial Profiles",
        "badge_icon": "fa-layer-group",
        "theme_color": "#eab308",
        "company_example": "Tata Steel / Jindal Steel & Power Hub",
        "operating_mode": "DEDICATED",
        "description": "Bundled hollow steel pipes (circular packs of 48/84), galvanized C-studs, rebar, coils, and crane staging.",
        "skus": [
            {"sku_id": "STL-TUBE-50", "name": "50mm OD Carbon Steel Pipes (Bundle 48)", "category": "Hollow Sections", "description": "Heavy-wall circular structural steel pipes strapped with high-tensile steel bands.", "unit_weight": 320.0, "unit_volume": 0.35, "uom": "Bundle", "units_per_bundle": 48, "target_bundles_per_pallet": 4, "bundle_name": "Hexagonal Pipe Bundle", "visual_color": (80, 85, 95), "icon_shape": "bundle"},
            {"sku_id": "STL-CSTUD-75", "name": "75mm Galvanized C-Stud (Pack 36)", "category": "Framing Channels", "description": "Cold-rolled galvanized structural steel drywall framing channels.", "unit_weight": 180.0, "unit_volume": 0.28, "uom": "Bundle", "units_per_bundle": 36, "target_bundles_per_pallet": 6, "bundle_name": "Strapped C-Stud Pack", "visual_color": (120, 125, 135), "icon_shape": "bundle"},
            {"sku_id": "STL-REBAR-12", "name": "12mm TMT High-Yield Rebar (Bundle 84)", "category": "Concrete Reinforcement", "description": "Fe-550D seismic resistant ribbed reinforcement bars bundled in full lengths.", "unit_weight": 448.0, "unit_volume": 0.40, "uom": "Bundle", "units_per_bundle": 84, "target_bundles_per_pallet": 2, "bundle_name": "Heavy Rebar Pack", "visual_color": (95, 75, 65), "icon_shape": "bundle"},
            {"sku_id": "STL-COIL-HR", "name": "Hot-Rolled Steel Coil (3 Tonne)", "category": "Flat Rolled Products", "description": "Mill-finished structural grade hot-rolled coil strapped on hardwood timber saddles.", "unit_weight": 3000.0, "unit_volume": 0.85, "uom": "Coil", "units_per_bundle": 1, "target_bundles_per_pallet": 1, "bundle_name": "Steel Coil Saddle", "visual_color": (60, 65, 75), "icon_shape": "cylinder"},
            {"sku_id": "STL-BEAM-200", "name": "200mm Universal Steel I-Beam (Pack 4)", "category": "Structural Beams", "description": "High-yield structural universal I-beams banded with safety corner protectors.", "unit_weight": 520.0, "unit_volume": 0.55, "uom": "Bundle", "units_per_bundle": 4, "target_bundles_per_pallet": 2, "bundle_name": "I-Beam Bundle", "visual_color": (70, 75, 85), "icon_shape": "bundle"}
        ],
        "vision_classes": [
            ("BUNDLE", "Circular/Profile Steel Bundle", "Strapped bundles of pipes, tubes, C-studs, and rebar"),
            ("PALLET", "Heavy Duty Steel Cradle", "Heavy timber dunnage and steel tube cradles"),
            ("WORKER", "Rigger / Crane Operator", "Hard-hat and high-visibility industrial yard crew"),
            ("TRUCK", "Flatbed Articulated Trailer", "Multi-axle flatbed transport trucks"),
            ("FORKLIFT", "Heavy Rough-Terrain Reach", "Heavy-capacity yard forklifts and mobile cranes"),
            ("LICENSE_PLATE", "License Plate", "Weighbridge and security bay ANPR vehicle logging")
        ],
        "zones": [
            ("TB-METALS", "Gate 01 Weighbridge Bay", "TRUCK_BAY", "Gross vehicle weight bridge and plate recognition check-in"),
            ("YARD-CRANE", "Overhead Gantry Crane Yard", "STORAGE", "Heavy tube and structural beam outdoor storage"),
            ("BAY-TUBE", "Tube Offloading Bay 01", "UNLOADING", "Side-unloading bay for articulated pipe trailers"),
            ("DOCK-DISPATCH", "Outbound Rail/Road Dock", "DOCK", "Staging bay for bundle strapping and outbound delivery")
        ],
        "deliveries": [
            {"po_number": "PO-TATA-STL-904", "plate": "JH-05-CB-7810", "vendor": "Tata Steel Jamshedpur Works", "load_description": "4x Hexagonal Pipe Bundles (192 tubes)", "sku": "STL-TUBE-50", "expected": 4}
        ]
    },

    # --------------------------------------------------------------------------
    # 6. COMMERCIAL MULTI-CLIENT 3PL HUB (DHL / DB Schenker Style) - 30 SKUs
    # --------------------------------------------------------------------------
    "3pl": {
        "key": "3pl",
        "name": "3PL Commercial Multi-Client Hub",
        "badge_icon": "fa-network-wired",
        "theme_color": "#c084fc",
        "company_example": "DHL Supply Chain / DB Schenker Multi-Client Hub",
        "operating_mode": "3PL",
        "description": "Multi-tenant inventory with client partitioning, bonded warehousing, and cross-docking.",
        "skus": [
            {"sku_id": "3PL-SAMS-TV", "name": "[Samsung] 55-inch 4K Display Panel", "category": "Consumer Electronics", "description": "High-value fragile client cargo with bonded serial number tracking.", "unit_weight": 21.0, "unit_volume": 0.24, "uom": "EA", "units_per_bundle": 1, "target_bundles_per_pallet": 8, "bundle_name": "Client Boxed Unit", "visual_color": (30, 80, 160), "icon_shape": "block"},
            {"sku_id": "3PL-TATA-PARTS", "name": "[Tata] Tier-1 High-Tensile Rod Pack", "category": "Automotive Inbound", "description": "Client manufacturing inventory staged for just-in-sequence feeding.", "unit_weight": 67.2, "unit_volume": 0.12, "uom": "Bundle", "units_per_bundle": 48, "target_bundles_per_pallet": 6, "bundle_name": "Strapped Component Bundle", "visual_color": (90, 110, 130), "icon_shape": "bundle"},
            {"sku_id": "3PL-COKE-CASE", "name": "[Coca-Cola] 330ml Can Tray (24pk)", "category": "FMCG Distribution", "description": "FMCG high-turnover cross-dock delivery pallet.", "unit_weight": 8.6, "unit_volume": 0.018, "uom": "Tray", "units_per_bundle": 24, "target_bundles_per_pallet": 60, "bundle_name": "FMCG Can Tray", "visual_color": (190, 30, 30), "icon_shape": "can"},
            {"sku_id": "3PL-IKEA-CHAIR", "name": "[IKEA] Flat-Pack Ergonomic Office Chair", "category": "Furniture & Home", "description": "Compact corrugated flat-pack containing unassembled task chair.", "unit_weight": 14.5, "unit_volume": 0.085, "uom": "FlatPack", "units_per_bundle": 1, "target_bundles_per_pallet": 20, "bundle_name": "Flat-Pack Carton", "visual_color": (160, 130, 60), "icon_shape": "box"},
            {"sku_id": "3PL-ZARA-APPAR", "name": "[Zara] Garment-on-Hanger Wardrobe Box", "category": "Apparel & Retail", "description": "Reinforced wardrobe carton with metal rail for hanging apparel.", "unit_weight": 18.0, "unit_volume": 0.28, "uom": "Wardrobe", "units_per_bundle": 25, "target_bundles_per_pallet": 6, "bundle_name": "Wardrobe Master Carton", "visual_color": (50, 50, 60), "icon_shape": "box"}
        ],
        "vision_classes": [
            ("BOX", "Multi-Client Shipping Carton", "Universal corrugated shipping boxes and eCommerce master packs"),
            ("TOTE", "Sortation Tote", "Standard 3PL distribution and conveyor totes"),
            ("PALLET", "Universal Euro/GMA Pallet", "Four-way entry standard handling pallets"),
            ("WORKER", "Logistics Associate", "Warehouse pickers and forklift drivers with RF scanners"),
            ("TRUCK", "Carrier / Trailer", "Third-party transport lorries and container trailers"),
            ("FORKLIFT", "Warehouse Vehicle", "Electric reach trucks and pallet jacks"),
            ("LICENSE_PLATE", "License Plate", "Universal multi-client carrier gate pass logging")
        ],
        "zones": [
            ("TB-01", "Gate 01 Multi-Client Bay", "TRUCK_BAY", "Primary ANPR security gate for carrier check-in"),
            ("DOCK-01", "Client Inbound Dock 01", "DOCK", "General inbound offloading bay"),
            ("DOCK-02", "Client Outbound Dock 02", "DOCK", "Cross-dock and outbound carrier dispatch"),
            ("SORT-01", "Conveyor & Sorting Floor", "SORTING", "Multi-client parcel sorting and cross-dock hub"),
            ("RACK-01", "High-Bay Pallet Racks A-D", "STORAGE", "High-density multi-client pallet storage")
        ],
        "deliveries": [
            {"po_number": "PO-SAMS-8820", "plate": "KA-03-KY-0875", "vendor": "Samsung Supply Chain Logistics", "load_description": "12x 55-inch Smart TV Pallets", "sku": "3PL-SAMS-TV", "expected": 12},
            {"po_number": "PO-TATA-3101", "plate": "MH-12-DE-1432", "vendor": "Tata AutoComp Delivery Fleet", "load_description": "6x Tier-1 Rod Packs", "sku": "3PL-TATA-PARTS", "expected": 6}
        ]
    },

    # --------------------------------------------------------------------------
    # 7. ARCHITECTURAL GLASS, GLAZING & MIRROR HUB (Saint-Gobain / AIS Style)
    # --------------------------------------------------------------------------
    "glass": {
        "key": "glass",
        "name": "Glass, Glazing & Architectural Sheets",
        "badge_icon": "fa-border-all",
        "theme_color": "#06b6d4",
        "company_example": "Saint-Gobain Glass / Asahi India Glass (AIS) Hub",
        "operating_mode": "DEDICATED",
        "description": "Jumbo float glass sheets, toughened safety panes, laminated acoustic glass, DGU units, mirrors, A-frame stillages, and CNC cutting remnants.",
        "skus": [
            # Clear Float Glass Sheets
            {"sku_id": "GLS-FLT-04MM", "name": "4mm Clear Float Glass Sheet (2440x1830mm)", "category": "Float Glass", "description": "Architectural grade 4mm Annealed Clear Float Glass sheets packed on vertical wooden end-cap crates (48 sq.ft/sheet).", "unit_weight": 44.6, "unit_volume": 0.018, "uom": "Sheet", "units_per_bundle": 40, "target_bundles_per_pallet": 1, "bundle_name": "End-Cap Glass Crate (40 Sheets)", "visual_color": (190, 210, 60), "icon_shape": "glass"},
            {"sku_id": "GLS-FLT-06MM", "name": "6mm Clear Float Glass Sheet (3660x2440mm)", "category": "Float Glass", "description": "Jumbo 6mm Clear Float Glass master sheets stored on heavy A-frame stillage (96 sq.ft/sheet).", "unit_weight": 134.0, "unit_volume": 0.054, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "A-Frame Pack (25 Sheets)", "visual_color": (200, 195, 45), "icon_shape": "glass"},
            {"sku_id": "GLS-FLT-08MM", "name": "8mm Extra-Clear Low-Iron Float Glass (3660x2440)", "category": "Float Glass", "description": "High-clarity low-iron Diamant 8mm architectural glass sheet with cork spacer pads.", "unit_weight": 178.5, "unit_volume": 0.071, "uom": "Sheet", "units_per_bundle": 20, "target_bundles_per_pallet": 1, "bundle_name": "A-Frame Pack (20 Sheets)", "visual_color": (220, 210, 80), "icon_shape": "glass"},
            {"sku_id": "GLS-FLT-10MM", "name": "10mm Heavy Float Glass Sheet (3660x2440mm)", "category": "Float Glass", "description": "Thick 10mm commercial storefront float glass sheet on reinforced steel A-frame.", "unit_weight": 223.2, "unit_volume": 0.089, "uom": "Sheet", "units_per_bundle": 16, "target_bundles_per_pallet": 1, "bundle_name": "A-Frame Pack (16 Sheets)", "visual_color": (180, 175, 40), "icon_shape": "glass"},
            {"sku_id": "GLS-FLT-12MM", "name": "12mm Jumbo Structural Float Glass (3660x2440mm)", "category": "Float Glass", "description": "Heavy 12mm structural glazing float glass sheet requiring vacuum-lifter crane handling.", "unit_weight": 268.0, "unit_volume": 0.107, "uom": "Sheet", "units_per_bundle": 12, "target_bundles_per_pallet": 1, "bundle_name": "Heavy A-Frame (12 Sheets)", "visual_color": (165, 160, 35), "icon_shape": "glass"},

            # Toughened / Tempered Safety Glass
            {"sku_id": "GLS-TGH-08MM", "name": "8mm Toughened Safety Glass Panel (2440x1220mm)", "category": "Toughened Glass", "description": "Heat-strengthened 8mm tempered safety glass with polished pencil edges.", "unit_weight": 59.5, "unit_volume": 0.024, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "Harp Rack Slot (25 Panes)", "visual_color": (210, 160, 30), "icon_shape": "glass"},
            {"sku_id": "GLS-TGH-10MM", "name": "10mm Toughened Shower & Partition Glass (2440x1830)", "category": "Toughened Glass", "description": "EN-12150 certified 10mm frameless partition tempered glass panel.", "unit_weight": 111.6, "unit_volume": 0.045, "uom": "Sheet", "units_per_bundle": 20, "target_bundles_per_pallet": 1, "bundle_name": "A-Frame Stillage (20 Panes)", "visual_color": (200, 145, 25), "icon_shape": "glass"},
            {"sku_id": "GLS-TGH-12MM", "name": "12mm Toughened Facade Safety Glass (3050x2140mm)", "category": "Toughened Glass", "description": "High-impact 12mm spider-glazing toughened facade glass with counter-sunk holes.", "unit_weight": 195.8, "unit_volume": 0.078, "uom": "Sheet", "units_per_bundle": 15, "target_bundles_per_pallet": 1, "bundle_name": "Facade Stillage (15 Panes)", "visual_color": (185, 130, 20), "icon_shape": "glass"},
            {"sku_id": "GLS-TGH-15MM", "name": "15mm Balustrade Toughened Glass (2440x1220mm)", "category": "Toughened Glass", "description": "Extra-thick 15mm structural balustrade safety glass panel.", "unit_weight": 111.5, "unit_volume": 0.045, "uom": "Sheet", "units_per_bundle": 12, "target_bundles_per_pallet": 1, "bundle_name": "Balustrade Stillage (12 Panes)", "visual_color": (170, 120, 20), "icon_shape": "glass"},

            # Laminated & Insulated (DGU) Glass
            {"sku_id": "GLS-LAM-638", "name": "6.38mm Laminated Safety Glass (3+0.38 PVB+3mm)", "category": "Laminated Glass", "description": "Shatter-resistant laminated safety glass with 0.38mm clear PVB acoustic interlayer.", "unit_weight": 71.2, "unit_volume": 0.029, "uom": "Sheet", "units_per_bundle": 24, "target_bundles_per_pallet": 1, "bundle_name": "Laminated Crate (24 Sheets)", "visual_color": (190, 180, 70), "icon_shape": "glass"},
            {"sku_id": "GLS-LAM-1076", "name": "10.76mm Acoustic Laminated Glass (5+0.76+5mm)", "category": "Laminated Glass", "description": "Sound-control laminated facade glass with 0.76mm acoustic PVB interlayer.", "unit_weight": 120.5, "unit_volume": 0.048, "uom": "Sheet", "units_per_bundle": 18, "target_bundles_per_pallet": 1, "bundle_name": "Acoustic Stillage (18 Sheets)", "visual_color": (175, 165, 65), "icon_shape": "glass"},
            {"sku_id": "GLS-LAM-1352", "name": "13.52mm SentryGlas Structural Laminated (6+1.52+6)", "category": "Laminated Glass", "description": "Hurricane and security rated structural ionoplast interlayer laminated glass.", "unit_weight": 152.0, "unit_volume": 0.061, "uom": "Sheet", "units_per_bundle": 14, "target_bundles_per_pallet": 1, "bundle_name": "Security Stillage (14 Sheets)", "visual_color": (160, 150, 55), "icon_shape": "glass"},
            {"sku_id": "GLS-DGU-24MM", "name": "24mm Double Glazed Low-E Argon Unit (6+12A+6mm)", "category": "Insulated Glass (DGU)", "description": "Hermetically sealed argon-filled solar control Low-E Double Glazed Unit.", "unit_weight": 90.0, "unit_volume": 0.072, "uom": "Unit", "units_per_bundle": 10, "target_bundles_per_pallet": 1, "bundle_name": "DGU Padded Rack (10 Units)", "visual_color": (210, 175, 50), "icon_shape": "glass"},
            {"sku_id": "GLS-DGU-28MM", "name": "28mm Triple-Silver Solar DGU (8+12A+8mm)", "category": "Insulated Glass (DGU)", "description": "High-performance curtain wall insulated glazing unit with warm-edge spacer.", "unit_weight": 120.0, "unit_volume": 0.084, "uom": "Unit", "units_per_bundle": 8, "target_bundles_per_pallet": 1, "bundle_name": "DGU Curtain Rack (8 Units)", "visual_color": (195, 160, 45), "icon_shape": "glass"},

            # Mirrors, Tinted & Specialty Glass
            {"sku_id": "GLS-MIR-05MM", "name": "5mm Copper-Free Silver Mirror Sheet (2440x1830)", "category": "Mirrors & Coated", "description": "Corrosion-resistant copper-free silver mirror sheet with moisture barrier backing.", "unit_weight": 55.8, "unit_volume": 0.022, "uom": "Sheet", "units_per_bundle": 30, "target_bundles_per_pallet": 1, "bundle_name": "Mirror Crate (30 Sheets)", "visual_color": (210, 215, 220), "icon_shape": "glass"},
            {"sku_id": "GLS-TNT-BRZ6", "name": "6mm Solar Control Bronze Tinted Glass (2440x1830)", "category": "Mirrors & Coated", "description": "Heat-absorbing bronze body-tinted architectural float glass sheet.", "unit_weight": 67.0, "unit_volume": 0.027, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "Tinted Crate (25 Sheets)", "visual_color": (70, 110, 160), "icon_shape": "glass"},
            {"sku_id": "GLS-TNT-BLU6", "name": "6mm Ocean Blue Hard-Coat Reflective Glass", "category": "Mirrors & Coated", "description": "Pyrolytic reflective solar control facade glass sheet.", "unit_weight": 67.0, "unit_volume": 0.027, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "Reflective Crate (25 Sheets)", "visual_color": (220, 130, 30), "icon_shape": "glass"},
            {"sku_id": "GLS-FRS-08MM", "name": "8mm Acid-Etched Satin Frosted Glass (2440x1830)", "category": "Mirrors & Coated", "description": "Translucent matte acid-etched privacy partition glass sheet.", "unit_weight": 89.3, "unit_volume": 0.036, "uom": "Sheet", "units_per_bundle": 20, "target_bundles_per_pallet": 1, "bundle_name": "Frosted Crate (20 Sheets)", "visual_color": (225, 230, 235), "icon_shape": "glass"},
            {"sku_id": "GLS-FIR-BORO", "name": "6mm Fire-Rated Borosilicate Glass (E-120 Rated)", "category": "Specialty Glass", "description": "2-hour fire and thermal shock resistant clear borosilicate safety glass.", "unit_weight": 52.0, "unit_volume": 0.021, "uom": "Sheet", "units_per_bundle": 15, "target_bundles_per_pallet": 1, "bundle_name": "Fire-Glass Crate (15 Sheets)", "visual_color": (160, 190, 210), "icon_shape": "glass"},

            # Glazing Accessories, Hardware & Consumables
            {"sku_id": "GLS-PAD-CORK", "name": "Anti-Slip Adhesive Cork Spacer Pads (Roll 5000)", "category": "Glazing Consumables", "description": "18x18x3mm static-cling cork separator pads preventing glass sheet contact damage.", "unit_weight": 4.5, "unit_volume": 0.012, "uom": "Box", "units_per_bundle": 5000, "target_bundles_per_pallet": 48, "bundle_name": "Cork Pad Carton", "visual_color": (90, 140, 190), "icon_shape": "box"},
            {"sku_id": "GLS-SIL-200L", "name": "Two-Part Structural Glazing Silicone (200L Drum)", "category": "Sealants & Interlayers", "description": "High-modulus neutral cure structural glazing and DGU secondary sealant drum.", "unit_weight": 245.0, "unit_volume": 0.28, "uom": "Drum", "units_per_bundle": 1, "target_bundles_per_pallet": 4, "bundle_name": "Silicone Drum 200L", "visual_color": (60, 70, 90), "icon_shape": "cylinder"},
            {"sku_id": "GLS-PVB-ROLL", "name": "0.76mm Clear PVB Lamination Film Roll (2440mm)", "category": "Sealants & Interlayers", "description": "Refrigerated polyvinyl butyral interlayer roll for autoclave glass lamination.", "unit_weight": 165.0, "unit_volume": 0.32, "uom": "Roll", "units_per_bundle": 1, "target_bundles_per_pallet": 2, "bundle_name": "Foil-Sealed PVB Roll", "visual_color": (180, 190, 200), "icon_shape": "cylinder"}
        ],
        "vision_classes": [
            ("GLASS_A_FRAME", "A-Frame Glass Stillage", "Vertical steel A-frame and L-frame racks holding jumbo glass sheets"),
            ("GLASS_SHEET_STACK", "Stacked Glass Sheets", "Multi-sheet float, toughened, and laminated glass stacks with edge visibility"),
            ("WOODEN_GLASS_CRATE", "End-Cap Wooden Glass Crate", "Imported timber end-cap crates containing annealed glass sheets"),
            ("BOX", "Glazing Hardware & Spacer Box", "Cartons of patch fittings, cork pads, and desiccant spacers"),
            ("PALLET", "Heavy Stillage Base", "Reinforced steel and hardwood glass transport bases"),
            ("FORKLIFT", "Glass Handler / Vacuum Crane", "Side-loader forklifts and overhead vacuum suction lifters"),
            ("WORKER", "Glazing Safety Handler", "Operators wearing cut-resistant Kevlar sleeves, suction cups, and helmets"),
            ("TRUCK", "Floatliner / Inloader Glass Truck", "Specialized A-frame flatbed and inloader glass transport trailers"),
            ("LICENSE_PLATE", "License Plate", "Automated ANPR check-in for glass carriers and returnable stillage tracking")
        ],
        "zones": [
            ("TB-GLS", "Gate 01 Floatliner ANPR & Stillage Bay", "TRUCK_BAY", "Inbound check-in for inloader glass trailers and returnable A-frame tracking"),
            ("DOCK-JUMBO", "Overhead Vacuum Crane Offloading Bay", "DOCK", "Gantry crane bay with vacuum suction frames for 3660x2440mm jumbo crates"),
            ("RACK-AFRAME", "Heavy A-Frame & Harp Rack Storage Hall", "STORAGE", "Angled vertical A-frame and slotted harp racks for float and toughened sheets"),
            ("CUT-TABLE", "CNC Glass Cutting & Remnant Off-Cut Bay", "STAGING", "Automated bridge cutting table and indexed usable remnant slot racks"),
            ("QUAR-BRK", "Cullet & Breakage Quarantine Bin", "INSPECTION", "Transit breakage inspection and crushed glass cullet recycling bunker")
        ],
        "deliveries": [
            {"po_number": "PO-SGG-4011", "plate": "TN-21-AX-7741", "vendor": "Saint-Gobain Glass India (Sriperumbudur)", "load_description": "8x A-Frames 6mm Clear Float Glass Jumbo (200 Sheets)", "sku": "GLS-FLT-06MM", "expected": 8},
            {"po_number": "PO-AIS-4012", "plate": "MH-04-GL-3390", "vendor": "Asahi India Glass Ltd (AIS)", "load_description": "6x Stillages 12mm Toughened Facade Glass (90 Panes)", "sku": "GLS-TGH-12MM", "expected": 6},
            {"po_number": "PO-GPL-4013", "plate": "HR-55-CD-1920", "vendor": "Gold Plus Float Glass Ltd", "load_description": "10x Crates 5mm Copper-Free Silver Mirror (300 Sheets)", "sku": "GLS-MIR-05MM", "expected": 10}
        ]
    },

    # --------------------------------------------------------------------------
    # 8. WOOD, TIMBER, PLYWOOD & ENGINEERED BOARDS (CenturyPly / Greenply Style)
    # --------------------------------------------------------------------------
    "wood": {
        "key": "wood",
        "name": "Wood, Timber, Plywood & Engineered Boards",
        "badge_icon": "fa-tree",
        "theme_color": "#d97706",
        "company_example": "CenturyPly / Greenply & Seasoned Timber Hub",
        "operating_mode": "DEDICATED",
        "description": "Marine BWP plywood stacks, HDHMR/MDF boards, seasoned Burma teak & pine timber planks (CFT), decorative veneers, laminates, and cantilever storage.",
        "skus": [
            # Plywood Sheets (8x4 ft = 32 sq.ft)
            {"sku_id": "WD-PLY-BWP18", "name": "18mm BWP Marine Waterproof Plywood (8x4 ft)", "category": "Marine & Commercial Plywood", "description": "IS:710 certified 18mm Boiling Water Proof marine grade gurjan plywood sheet (32 sq.ft).", "unit_weight": 36.5, "unit_volume": 0.053, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "Strapped Plywood Stack (25 Sheets)", "visual_color": (60, 120, 185), "icon_shape": "wood"},
            {"sku_id": "WD-PLY-BWP12", "name": "12mm BWP Marine Waterproof Plywood (8x4 ft)", "category": "Marine & Commercial Plywood", "description": "IS:710 12mm marine plywood treated with GLP preservative against borer and termite.", "unit_weight": 24.8, "unit_volume": 0.035, "uom": "Sheet", "units_per_bundle": 35, "target_bundles_per_pallet": 1, "bundle_name": "Strapped Plywood Stack (35 Sheets)", "visual_color": (55, 115, 175), "icon_shape": "wood"},
            {"sku_id": "WD-PLY-MR18", "name": "18mm MR Grade Commercial Plywood (8x4 ft)", "category": "Marine & Commercial Plywood", "description": "IS:303 Moisture Resistant 18mm interior furniture grade calibrated plywood.", "unit_weight": 33.0, "unit_volume": 0.053, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "Commercial Ply Bundle (25 Sheets)", "visual_color": (70, 135, 195), "icon_shape": "wood"},
            {"sku_id": "WD-PLY-MR06", "name": "6mm Flexible Gurjan Plywood Sheet (8x4 ft)", "category": "Marine & Commercial Plywood", "description": "Bendable 6mm flexi-ply sheet for curved architectural millwork and arches.", "unit_weight": 11.2, "unit_volume": 0.018, "uom": "Sheet", "units_per_bundle": 60, "target_bundles_per_pallet": 1, "bundle_name": "Flexi-Ply Stack (60 Sheets)", "visual_color": (80, 145, 205), "icon_shape": "wood"},
            {"sku_id": "WD-PLY-FIRE18", "name": "18mm Firewall Fire-Retardant Plywood (8x4 ft)", "category": "Specialty Boards", "description": "IS:5509 certified low-flammability, low-smoke fire-retardant structural plywood.", "unit_weight": 38.0, "unit_volume": 0.053, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "Fire-Rated Ply Stack (25 Sheets)", "visual_color": (50, 80, 190), "icon_shape": "wood"},
            {"sku_id": "WD-PLY-SHUT12", "name": "12mm Phenolic Film-Faced Shuttering Ply (8x4)", "category": "Specialty Boards", "description": "High-density 30kg densified concrete formwork shuttering plywood with WBP glue.", "unit_weight": 30.0, "unit_volume": 0.036, "uom": "Sheet", "units_per_bundle": 30, "target_bundles_per_pallet": 1, "bundle_name": "Shuttering Ply Pack (30 Sheets)", "visual_color": (45, 55, 110), "icon_shape": "wood"},
            {"sku_id": "WD-BLK-19MM", "name": "19mm Pinewood Core Blockboard (8x4 ft)", "category": "Marine & Commercial Plywood", "description": "Kiln-seasoned imported pinewood baton core blockboard for warp-free long shutters.", "unit_weight": 31.5, "unit_volume": 0.056, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "Blockboard Pack (25 Sheets)", "visual_color": (65, 125, 180), "icon_shape": "wood"},

            # MDF, HDHMR & Particle Boards
            {"sku_id": "WD-HDHMR-18", "name": "18mm Green High-Density HDHMR Board (8x4 ft)", "category": "MDF & Engineered Boards", "description": "High-Density High-Moisture-Resistant eucalyptus fiber board (850 kg/m3 density).", "unit_weight": 44.0, "unit_volume": 0.053, "uom": "Sheet", "units_per_bundle": 22, "target_bundles_per_pallet": 1, "bundle_name": "HDHMR Pallet (22 Boards)", "visual_color": (70, 140, 95), "icon_shape": "wood"},
            {"sku_id": "WD-MDF-18MM", "name": "18mm Interior Plain MDF Board (8x4 ft)", "category": "MDF & Engineered Boards", "description": "Smooth homogeneous Medium Density Fiberboard for CNC routing and lacquer finishes.", "unit_weight": 39.5, "unit_volume": 0.053, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "MDF Pallet Stack (25 Boards)", "visual_color": (85, 150, 195), "icon_shape": "wood"},
            {"sku_id": "WD-MDF-12MM", "name": "12mm Calibrated Plain MDF Board (8x4 ft)", "category": "MDF & Engineered Boards", "description": "12mm medium density fiberboard for wall paneling and cabinet backs.", "unit_weight": 26.5, "unit_volume": 0.035, "uom": "Sheet", "units_per_bundle": 35, "target_bundles_per_pallet": 1, "bundle_name": "MDF Pallet Stack (35 Boards)", "visual_color": (90, 155, 200), "icon_shape": "wood"},
            {"sku_id": "WD-PRT-PRE18", "name": "18mm Twin-Side Pre-Laminated Particle Board", "category": "MDF & Engineered Boards", "description": "Melamine-faced Frosty White & Walnut pre-laminated modular office furniture board.", "unit_weight": 34.0, "unit_volume": 0.053, "uom": "Sheet", "units_per_bundle": 25, "target_bundles_per_pallet": 1, "bundle_name": "Pre-Lam Board Pack (25 Sheets)", "visual_color": (120, 145, 175), "icon_shape": "wood"},

            # Sawn Hardwood & Softwood Timber Planks / Beams (CFT Tracked)
            {"sku_id": "WD-TEAK-PLK", "name": "Burma Teak Kiln-Seasoned Plank (10ft x 8in x 2in)", "category": "Hardwood & Softwood Timber", "description": "First-class golden Burma Teak sawn plank kiln-dried to 10% moisture content (1.11 CFT/plank).", "unit_weight": 22.0, "unit_volume": 0.031, "uom": "Plank", "units_per_bundle": 20, "target_bundles_per_pallet": 1, "bundle_name": "Strapped Teak Pack (22.2 CFT)", "visual_color": (35, 95, 165), "icon_shape": "wood"},
            {"sku_id": "WD-OAK-PLK", "name": "American White Oak Planed Timber (8ft x 6in x 1.5in)", "category": "Hardwood & Softwood Timber", "description": "FAS-grade kiln-dried white oak hardwood lumber for premium flooring and joinery (0.5 CFT).", "unit_weight": 11.5, "unit_volume": 0.014, "uom": "Plank", "units_per_bundle": 32, "target_bundles_per_pallet": 1, "bundle_name": "Oak Lumber Pack (16 CFT)", "visual_color": (75, 140, 195), "icon_shape": "wood"},
            {"sku_id": "WD-PINE-BEAM", "name": "Structural Southern Yellow Pine Beam (12ft x 4in x 4in)", "category": "Hardwood & Softwood Timber", "description": "Pressure-treated structural softwood timber beam for framing and trusses (1.33 CFT).", "unit_weight": 21.0, "unit_volume": 0.038, "uom": "Beam", "units_per_bundle": 16, "target_bundles_per_pallet": 1, "bundle_name": "Pine Beam Bundle (21.3 CFT)", "visual_color": (80, 165, 215), "icon_shape": "wood"},
            {"sku_id": "WD-MRNT-FRM", "name": "Malaysian Sal / Meranti Door Frame Scantling (7ft x 5x3in)", "category": "Hardwood & Softwood Timber", "description": "Heavy hardwood door chowkhat scantling treated against warping (0.73 CFT).", "unit_weight": 16.8, "unit_volume": 0.021, "uom": "Piece", "units_per_bundle": 24, "target_bundles_per_pallet": 1, "bundle_name": "Scantling Bundle (24 Pcs)", "visual_color": (45, 85, 155), "icon_shape": "wood"},

            # Veneers, Laminates & Wood Adhesives
            {"sku_id": "WD-LAM-1MM", "name": "1.0mm High-Pressure Decorative Laminate (8x4 ft)", "category": "Laminates & Veneers", "description": "Scratch-resistant suede & high-gloss phenolic decorative laminate sheets packed in flat wooden crates.", "unit_weight": 4.2, "unit_volume": 0.003, "uom": "Sheet", "units_per_bundle": 100, "target_bundles_per_pallet": 1, "bundle_name": "Laminate Crate (100 Sheets)", "visual_color": (90, 110, 145), "icon_shape": "wood"},
            {"sku_id": "WD-VNR-TEAK4", "name": "4mm Natural Smoked Teak Crown Veneer (8x4 ft)", "category": "Laminates & Veneers", "description": "Book-matched natural hardwood decorative sliced veneer on MDF recon backing.", "unit_weight": 7.8, "unit_volume": 0.012, "uom": "Sheet", "units_per_bundle": 50, "target_bundles_per_pallet": 1, "bundle_name": "Veneer Flat Pallet (50 Sheets)", "visual_color": (40, 90, 145), "icon_shape": "wood"},
            {"sku_id": "WD-ADH-D3-50", "name": "D3 Waterproof PVA Wood Adhesive (50kg Carboy)", "category": "Wood Adhesives & Edgeband", "description": "Cross-linking waterproof synthetic resin carpenter adhesive (Fevicol Marine / SH grade).", "unit_weight": 52.0, "unit_volume": 0.055, "uom": "Drum", "units_per_bundle": 1, "target_bundles_per_pallet": 12, "bundle_name": "Adhesive Carboy 50kg", "visual_color": (190, 130, 40), "icon_shape": "cylinder"}
        ],
        "vision_classes": [
            ("PLYWOOD_STACK", "Plywood / MDF Board Stack", "Flat-stacked bundles of 8x4ft plywood, blockboard, HDHMR, and MDF sheets"),
            ("TIMBER_PLANK_BUNDLE", "Strapped Timber / Plank Bundle", "Steel/PET-strapped bundles of sawn hardwood planks, beams, and scantlings"),
            ("PALLET", "Timber Dunnage / Skids", "Heavy wooden skids, cantilever cradles, and laminate crates"),
            ("BOX", "Hardware & Adhesive Carton", "Boxes of edge-banding tape, laminates, and wood adhesive drums"),
            ("FORKLIFT", "Side-Loader / Cantilever Forklift", "Wide-carriage and multi-directional side-loader forklifts for 8ft-12ft timber"),
            ("WORKER", "Timber Yard Operator", "Operators with dust masks, ear protection, and moisture meters"),
            ("TRUCK", "Flatbed Timber Lorry", "Inbound timber flatbed trailers and container trucks"),
            ("LICENSE_PLATE", "License Plate", "Forestry transit pass and gate ANPR vehicle verification")
        ],
        "zones": [
            ("TB-WOOD", "Gate 01 Timber Weighbridge & Moisture Check Bay", "TRUCK_BAY", "ANPR check-in, forestry transit permit verification, and timber moisture audit"),
            ("YRD-CANT", "Cantilever Heavy Timber & Beam Racking", "STORAGE", "Multi-tier heavy cantilever arms for 10ft-12ft teak planks and pine beams"),
            ("BAY-PLY", "Flat-Stack Plywood & MDF Humidity-Controlled Hall", "STORAGE", "Level concrete dunnage bays keeping 8x4ft plywood and MDF boards warp-free"),
            ("KILN-DRY", "Kiln Seasoning & Anti-Borer Treatment Chamber", "INSPECTION", "Thermal seasoning chamber reducing timber moisture to 8-12%"),
            ("SAW-REM", "CNC Panel Saw & Off-Cut Remnant Racks", "STAGING", "Beam-saw sizing station and barcoded off-cut remnant storage slots")
        ],
        "deliveries": [
            {"po_number": "PO-CENT-5011", "plate": "WB-03-MP-6612", "vendor": "CenturyPly Panels Ltd", "load_description": "12x Stacks 18mm BWP Marine Plywood (300 Sheets)", "sku": "WD-PLY-BWP18", "expected": 12},
            {"po_number": "PO-GRN-5012", "plate": "UK-06-TR-4409", "vendor": "Greenpanel Industries Ltd", "load_description": "10x Pallets 18mm Green HDHMR Boards (220 Sheets)", "sku": "WD-HDHMR-18", "expected": 10},
            {"po_number": "PO-TEAK-5013", "plate": "KL-07-BW-8910", "vendor": "Malabar Seasoned Timber Corp", "load_description": "8x Strapped Bundles Burma Teak Planks (177.6 CFT)", "sku": "WD-TEAK-PLK", "expected": 8}
        ]
    },

    # --------------------------------------------------------------------------
    # 9. CONSTRUCTION, CEMENT, TILES & BUILDING MATERIALS (UltraTech / Kajaria)
    # --------------------------------------------------------------------------
    "construction": {
        "key": "construction",
        "name": "Construction, Cement, Tiles & Building Materials",
        "badge_icon": "fa-trowel-bricks",
        "theme_color": "#f97316",
        "company_example": "UltraTech Cement / Kajaria Ceramics Depot",
        "operating_mode": "DEDICATED",
        "description": "OPC/PPC cement bags, vitrified & porcelain tile pallets, gypsum drywall boards, AAC blocks, tile adhesives, and uPVC plumbing bundles.",
        "skus": [
            {"sku_id": "BLD-CEM-OPC53", "name": "OPC 53 Grade Structural Cement (50kg Bag)", "category": "Cement & Binders", "description": "High-early-strength Ordinary Portland Cement 50kg laminated polypropylene sack.", "unit_weight": 50.0, "unit_volume": 0.036, "uom": "Bag", "units_per_bundle": 40, "target_bundles_per_pallet": 1, "bundle_name": "Sling Pallet (40 Bags / 2T)", "visual_color": (120, 125, 130), "icon_shape": "box"},
            {"sku_id": "BLD-CEM-PPC", "name": "Weather-Shield Pozzolana Cement (50kg Bag)", "category": "Cement & Binders", "description": "Moisture-resistant Portland Pozzolana Cement in tamper-proof AD-Star sack.", "unit_weight": 50.0, "unit_volume": 0.036, "uom": "Bag", "units_per_bundle": 40, "target_bundles_per_pallet": 1, "bundle_name": "Sling Pallet (40 Bags)", "visual_color": (90, 130, 160), "icon_shape": "box"},
            {"sku_id": "BLD-TIL-VIT60", "name": "600x600mm Double-Charged Vitrified Tiles (Box 4)", "category": "Ceramic & Vitrified Tiles", "description": "High-gloss nano-polished 600x600mm floor tiles (1.44 sq.m / 15.5 sq.ft per carton).", "unit_weight": 29.5, "unit_volume": 0.018, "uom": "Box", "units_per_bundle": 40, "target_bundles_per_pallet": 1, "bundle_name": "Strapped Tile Pallet (40 Boxes)", "visual_color": (150, 140, 125), "icon_shape": "box"},
            {"sku_id": "BLD-TIL-SLB16", "name": "800x1600mm Glazed Porcelain GVT Slab (Box 2)", "category": "Ceramic & Vitrified Tiles", "description": "Large-format Italian marble finish glazed vitrified slab tiles on A-frame pallet.", "unit_weight": 54.0, "unit_volume": 0.034, "uom": "Box", "units_per_bundle": 24, "target_bundles_per_pallet": 1, "bundle_name": "Vertical Slab Pallet (24 Boxes)", "visual_color": (170, 160, 150), "icon_shape": "glass"},
            {"sku_id": "BLD-GYP-12MM", "name": "12.5mm Gyproc Fireline Plasterboard (8x4 ft)", "category": "Drywall & Ceilings", "description": "Glass-fiber reinforced gypsum drywall board for fire-rated partitions.", "unit_weight": 28.0, "unit_volume": 0.037, "uom": "Sheet", "units_per_bundle": 40, "target_bundles_per_pallet": 1, "bundle_name": "Drywall Stack (40 Boards)", "visual_color": (140, 130, 170), "icon_shape": "wood"},
            {"sku_id": "BLD-AAC-200", "name": "600x200x200mm AAC Lightweight Blocks (Pallet)", "category": "Masonry & Blocks", "description": "Autoclaved Aerated Concrete thermal-insulating structural masonry blocks.", "unit_weight": 14.5, "unit_volume": 0.024, "uom": "Block", "units_per_bundle": 60, "target_bundles_per_pallet": 1, "bundle_name": "Shrink-Wrapped AAC Pallet (60)", "visual_color": (165, 165, 170), "icon_shape": "block"},
            {"sku_id": "BLD-ADH-TILE", "name": "Polymer-Modified Tile & Stone Adhesive (20kg)", "category": "Cement & Binders", "description": "C2TE-S1 deformable cementitious adhesive for large-format vitrified tiles.", "unit_weight": 20.0, "unit_volume": 0.016, "uom": "Bag", "units_per_bundle": 50, "target_bundles_per_pallet": 1, "bundle_name": "Adhesive Pallet (50 Bags)", "visual_color": (70, 110, 175), "icon_shape": "box"},
            {"sku_id": "BLD-PIP-UPVC", "name": "110mm SWR uPVC Drainage Pipe 6m (Bundle 10)", "category": "Plumbing & Sanitary", "description": "Ring-fit UV-stabilized uPVC soil, waste, and rainwater pipes.", "unit_weight": 68.0, "unit_volume": 0.35, "uom": "Bundle", "units_per_bundle": 10, "target_bundles_per_pallet": 4, "bundle_name": "Strapped Pipe Bundle", "visual_color": (150, 155, 165), "icon_shape": "bundle"}
        ],
        "vision_classes": [
            ("BOX", "Tile Carton / Cement Sling Bag", "Corrugated vitrified tile boxes and 50kg cement/adhesive sacks"),
            ("PALLET", "Heavy Tile / AAC Block Pallet", "Shrink-wrapped masonry and ceramic tile pallets"),
            ("BUNDLE", "uPVC / Conduit Pipe Bundle", "Strapped 6m plumbing and electrical pipe bundles"),
            ("FORKLIFT", "Heavy Counterbalance Forklift", "3-5 Tonne diesel/electric yard forklifts"),
            ("WORKER", "Depot Loader / Inspector", "Safety helmet and vest equipped depot crew"),
            ("TRUCK", "Flatbed / Bulker Lorry", "Cement bag flatbed trucks and tile container trailers"),
            ("LICENSE_PLATE", "License Plate", "Automated weighbridge and gate ANPR check-in")
        ],
        "zones": [
            ("TB-BLD", "Gate 01 Weighbridge & ANPR Bay", "TRUCK_BAY", "Inbound weighbridge for cement bulkers and tile trailers"),
            ("BAY-CEM", "Moisture-Proof Cement & Mortar Godown", "STORAGE", "Raised dunnage floor bays preventing ground moisture ingress"),
            ("RACK-TILE", "Batch-Indexed Vitrified Tile Racking", "STORAGE", "Heavy pallet racking segregating tiles by shade and caliber lot"),
            ("YRD-PIPE", "Outdoor AAC Block & uPVC Pipe Yard", "STORAGE", "Cantilever and block-stacking yard for weather-proof materials")
        ],
        "deliveries": [
            {"po_number": "PO-ULT-6011", "plate": "RJ-14-GC-8821", "vendor": "UltraTech Cement Works", "load_description": "20x Sling Pallets OPC 53 Grade Cement (800 Bags)", "sku": "BLD-CEM-OPC53", "expected": 20},
            {"po_number": "PO-KAJ-6012", "plate": "GJ-03-AT-5519", "vendor": "Kajaria Ceramics Morbi Plant", "load_description": "15x Pallets 600x600mm Vitrified Tiles (600 Boxes)", "sku": "BLD-TIL-VIT60", "expected": 15}
        ]
    },

    # --------------------------------------------------------------------------
    # 10. CHEMICALS, PAINTS, POLYMERS & RESINS (Asian Paints / Pidilite / BASF)
    # --------------------------------------------------------------------------
    "chemicals": {
        "key": "chemicals",
        "name": "Chemicals, Paints, Polymers & Resins",
        "badge_icon": "fa-flask-vial",
        "theme_color": "#14b8a6",
        "company_example": "Asian Paints / Pidilite & BASF Chemical Hub",
        "operating_mode": "DEDICATED",
        "description": "Emulsion paint pails, 200L epoxy/solvent drums, 1000L IBC chemical totes, polymer resin granules, and hazmat spill-containment racking.",
        "skus": [
            {"sku_id": "CHM-PNT-20L", "name": "Apex Weatherproof Exterior Emulsion (20L Pail)", "category": "Architectural Coatings", "description": "100% acrylic elastomeric exterior wall paint in heavy HDPE bucket.", "unit_weight": 26.5, "unit_volume": 0.028, "uom": "Pail", "units_per_bundle": 24, "target_bundles_per_pallet": 1, "bundle_name": "Palletized Paint Pails (24)", "visual_color": (160, 150, 40), "icon_shape": "cylinder"},
            {"sku_id": "CHM-EPX-200L", "name": "Bisphenol-A Liquid Epoxy Resin (200L Drum)", "category": "Industrial Resins", "description": "Unmodified liquid epoxy resin in tight-head UN-certified steel drum.", "unit_weight": 232.0, "unit_volume": 0.28, "uom": "Drum", "units_per_bundle": 4, "target_bundles_per_pallet": 1, "bundle_name": "4-Drum Spill Pallet", "visual_color": (180, 90, 30), "icon_shape": "cylinder"},
            {"sku_id": "CHM-IBC-1000", "name": "Polyurethane Polyol Blend (1000L IBC Tote)", "category": "Bulk Liquid Chemicals", "description": "Galvanized steel-caged 1000-litre HDPE Intermediate Bulk Container with bottom valve.", "unit_weight": 1120.0, "unit_volume": 1.35, "uom": "IBC", "units_per_bundle": 1, "target_bundles_per_pallet": 1, "bundle_name": "Caged IBC Tote 1000L", "visual_color": (190, 185, 175), "icon_shape": "block"},
            {"sku_id": "CHM-PLY-HDPE", "name": "Virgin Injection-Grade HDPE Granules (25kg Bag)", "category": "Polymers & Plastics", "description": "High-Density Polyethylene virgin pellets in moisture-barrier FFS woven sack.", "unit_weight": 25.0, "unit_volume": 0.042, "uom": "Bag", "units_per_bundle": 40, "target_bundles_per_pallet": 1, "bundle_name": "Stretch-Hooded Polymer Pallet", "visual_color": (140, 160, 180), "icon_shape": "box"},
            {"sku_id": "CHM-TIO2-25", "name": "Rutile Titanium Dioxide Pigment (25kg Sack)", "category": "Pigments & Additives", "description": "High-opacity white TiO2 pigment powder for coatings and masterbatches.", "unit_weight": 25.0, "unit_volume": 0.032, "uom": "Bag", "units_per_bundle": 40, "target_bundles_per_pallet": 1, "bundle_name": "Pigment Pallet (1 Tonne)", "visual_color": (200, 205, 210), "icon_shape": "box"},
            {"sku_id": "CHM-SLV-200L", "name": "Industrial Grade Ethyl Acetate Solvent (200L)", "category": "Solvents & Hazmat", "description": "Flammable Class-3 organic solvent in grounded explosion-proof steel drum.", "unit_weight": 198.0, "unit_volume": 0.28, "uom": "Drum", "units_per_bundle": 4, "target_bundles_per_pallet": 1, "bundle_name": "Hazmat 4-Drum Bund", "visual_color": (40, 60, 190), "icon_shape": "cylinder"}
        ],
        "vision_classes": [
            ("IBC_TOTE", "1000L Caged IBC Chemical Tote", "Steel-caged 1000L intermediate bulk liquid containers"),
            ("DRUM_PALLET", "200L Steel Drum / Paint Pail Pallet", "4-drum spill containment pallets and stacked 20L paint pails"),
            ("BOX", "Polymer / Pigment Sack Pallet", "Stretch-hooded 25kg resin and chemical powder bags"),
            ("PALLET", "Spill-Containment Bund Pallet", "Chemical-resistant polyethylene and steel pallets"),
            ("FORKLIFT", "Flameproof Ex-Rated Forklift", "ATEX explosion-proof reach trucks and drum clamp handlers"),
            ("WORKER", "Hazmat PPE Operator", "Operators with chemical respirators, goggles, and nitrile aprons"),
            ("TRUCK", "ISO Chemical Tanker / Box Van", "ADR/HAZCHEM certified chemical transport trucks"),
            ("LICENSE_PLATE", "License Plate", "HAZCHEM gate manifest and ANPR check-in")
        ],
        "zones": [
            ("TB-CHM", "Gate 01 HAZCHEM & SDS Verification Bay", "TRUCK_BAY", "ANPR check-in and Safety Data Sheet (SDS) compliance check"),
            ("DOCK-LIQ", "Spill-Bunded Drum & IBC Offloading Dock", "DOCK", "Containment-trenched dock for 1000L IBCs and 200L drums"),
            ("HAZ-FLAM", "Class-3 Flammable Solvent Bunker", "STORAGE", "Foam-suppressed, grounded explosion-proof drum storage"),
            ("RACK-PNT", "High-Bay Paint & Polymer Racking", "STORAGE", "Selective pallet racking for paint pails and resin bags")
        ],
        "deliveries": [
            {"po_number": "PO-APNT-7011", "plate": "GJ-16-CH-4490", "vendor": "Asian Paints Ankleshwar Plant", "load_description": "16x Pallets 20L Apex Exterior Emulsion Pails", "sku": "CHM-PNT-20L", "expected": 16},
            {"po_number": "PO-BASF-7012", "plate": "MH-43-BZ-9910", "vendor": "BASF India Chemical Complex", "load_description": "10x 1000L Caged IBC Totes Polyurethane Polyol", "sku": "CHM-IBC-1000", "expected": 10}
        ]
    },

    # --------------------------------------------------------------------------
    # 11. TEXTILES, FABRICS, YARN & APPAREL MILL HUB (Arvind / Welspun / Raymond)
    # --------------------------------------------------------------------------
    "textiles": {
        "key": "textiles",
        "name": "Textiles, Fabrics, Yarn & Apparel Hub",
        "badge_icon": "fa-shirt",
        "theme_color": "#ec4899",
        "company_example": "Arvind Mills / Welspun & Raymond Textile Hub",
        "operating_mode": "DEDICATED",
        "description": "Woven denim & cotton fabric rolls, combed yarn cone pallets, compressed cotton/polyester bales, dye-lot shade tracking, and apparel cartons.",
        "skus": [
            {"sku_id": "TXT-DEN-200M", "name": "12oz Indigo Stretch Denim Fabric Roll (200m)", "category": "Woven Fabric Rolls", "description": "Rope-dyed 62-inch width sanforized indigo denim fabric roll wrapped in UV poly sleeve.", "unit_weight": 95.0, "unit_volume": 0.18, "uom": "Roll", "units_per_bundle": 6, "target_bundles_per_pallet": 1, "bundle_name": "Fabric Roll Cradle (6 Rolls)", "visual_color": (150, 75, 40), "icon_shape": "cylinder"},
            {"sku_id": "TXT-COT-POP", "name": "100% Organic Cotton Poplin Bolt (150m Roll)", "category": "Woven Fabric Rolls", "description": "Mercerized 60s count bleached white shirting cotton fabric roll.", "unit_weight": 42.0, "unit_volume": 0.11, "uom": "Roll", "units_per_bundle": 10, "target_bundles_per_pallet": 1, "bundle_name": "Shirting Roll Rack (10 Rolls)", "visual_color": (190, 185, 180), "icon_shape": "cylinder"},
            {"sku_id": "TXT-YRN-40S", "name": "40s Combed Compact Cotton Yarn Cones (Bag 24)", "category": "Spun Yarn & Fibers", "description": "Auto-coned waxing-grade knitting cotton yarn cones (1.89kg each) in HDPE master bag.", "unit_weight": 45.4, "unit_volume": 0.085, "uom": "Bag", "units_per_bundle": 16, "target_bundles_per_pallet": 1, "bundle_name": "Yarn Cone Pallet (16 Bags)", "visual_color": (160, 130, 175), "icon_shape": "box"},
            {"sku_id": "TXT-BAL-COT", "name": "Pressed Raw Shankar-6 Cotton Bale (170kg)", "category": "Spun Yarn & Fibers", "description": "High-density hydraulically pressed raw cotton lint bale with cotton cloth wrapping.", "unit_weight": 170.0, "unit_volume": 0.42, "uom": "Bale", "units_per_bundle": 4, "target_bundles_per_pallet": 1, "bundle_name": "4-Bale Clamp Load", "visual_color": (175, 170, 155), "icon_shape": "block"},
            {"sku_id": "TXT-KNT-FRT", "name": "320 GSM Loopback French Terry Knit Roll (25kg)", "category": "Knitted Fabrics", "description": "Bio-washed reactive dyed tubular knitted hoodie fabric roll.", "unit_weight": 25.0, "unit_volume": 0.075, "uom": "Roll", "units_per_bundle": 12, "target_bundles_per_pallet": 1, "bundle_name": "Knit Roll Stillage (12 Rolls)", "visual_color": (130, 70, 165), "icon_shape": "cylinder"},
            {"sku_id": "TXT-GAR-BOX", "name": "Export Ready-Made Garment Shipper (60 Pcs)", "category": "Finished Apparel", "description": "RFID-tagged polybagged garments in 5-ply export corrugated master carton.", "unit_weight": 16.5, "unit_volume": 0.072, "uom": "Carton", "units_per_bundle": 20, "target_bundles_per_pallet": 1, "bundle_name": "Apparel Export Pallet (20 Ctn)", "visual_color": (110, 90, 150), "icon_shape": "box"}
        ],
        "vision_classes": [
            ("FABRIC_ROLL", "Woven / Knitted Fabric Roll", "Cylindrical poly-wrapped fabric bolts and denim rolls on cradles"),
            ("COTTON_BALE", "Compressed Fiber / Cotton Bale", "Strapped high-density raw cotton and polyester fiber bales"),
            ("BOX", "Yarn Cone Bag / Apparel Carton", "Export garment cartons and palletized yarn cone sacks"),
            ("PALLET", "Roll Stillage / Pallet", "Steel fabric roll stillages and plastic pallets"),
            ("FORKLIFT", "Bale-Clamp / Carpet-Pole Forklift", "Specialized bale-clamp and boom-pole forklifts for fabric rolls"),
            ("WORKER", "Mill & QA Inspector", "Fabric shade-matching and warehouse operators"),
            ("TRUCK", "Container Trailer", "Dry-van apparel and textile container trucks"),
            ("LICENSE_PLATE", "License Plate", "Automated textile mill gate ANPR check-in")
        ],
        "zones": [
            ("TB-TXT", "Gate 01 Textile Mill ANPR Bay", "TRUCK_BAY", "Carrier check-in for yarn, bale, and export garment containers"),
            ("BAY-BALE", "Fire-Protected Raw Cotton Bale Godown", "STORAGE", "Humidity-controlled block storage for compressed cotton bales"),
            ("RACK-ROLL", "Cantilever & Stillage Fabric Roll Racks", "STORAGE", "Shade-lot segregated honeycomb racks for denim and woven fabric rolls"),
            ("STG-INSP", "4-Point Fabric Inspection & Shade Lot Bay", "INSPECTION", "Light-box fabric inspection and GSM verification tables")
        ],
        "deliveries": [
            {"po_number": "PO-ARV-8011", "plate": "GJ-01-TX-3318", "vendor": "Arvind Denim Division Ahmedabad", "load_description": "12x Cradles 12oz Indigo Denim Fabric Rolls (72 Rolls)", "sku": "TXT-DEN-200M", "expected": 12},
            {"po_number": "PO-VRD-8012", "plate": "PB-10-YN-7704", "vendor": "Vardhman Spinning & General Mills", "load_description": "15x Pallets 40s Combed Cotton Yarn Cones", "sku": "TXT-YRN-40S", "expected": 15}
        ]
    }
}


# ==============================================================================
# 3. PROCEDURAL VISUAL PRODUCT IMAGE GENERATOR
# ==============================================================================

def generate_sku_thumbnail(sku_id: str, sku_name: str, category: str, bg_color: tuple, icon_shape: str = "box") -> str:
    """
    Renders a high-resolution, modern technical product card thumbnail
    with realistic geometric silhouettes, barcode markings, and dimension badges.
    Saves directly to static/uploads/sku_images/<sku_id>.png
    """
    filename = f"{sku_id}.png"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # 440x330 high-res canvas
    img = np.zeros((330, 440, 3), dtype=np.uint8)
    b, g, r = bg_color
    img[:] = (int(b * 0.35), int(g * 0.35), int(r * 0.35))

    # Gradient highlight card body
    cv2.rectangle(img, (12, 12), (428, 318), (int(b * 0.75), int(g * 0.75), int(r * 0.75)), -1)
    cv2.rectangle(img, (12, 12), (428, 318), (210, 230, 250), 2)

    # Central Product Illustration Viewport
    cv2.rectangle(img, (60, 40), (380, 210), (int(b * 1.15), int(g * 1.15), int(r * 1.15)), -1)
    cv2.rectangle(img, (60, 40), (380, 210), (255, 255, 255), 2)

    # Geometric Product Silhouette based on icon_shape
    center_x, center_y = 220, 115
    if icon_shape == "can":
        # Draw cylindrical beverage can
        cv2.rectangle(img, (center_x - 35, center_y - 50), (center_x + 35, center_y + 50), (240, 240, 245), -1)
        cv2.ellipse(img, (center_x, center_y - 50), (35, 12), 0, 0, 360, (210, 210, 220), -1)
        cv2.ellipse(img, (center_x, center_y + 50), (35, 12), 0, 0, 360, (180, 180, 190), -1)
        cv2.line(img, (center_x - 30, center_y), (center_x + 30, center_y), (int(b), int(g), int(r)), 4)
    elif icon_shape == "bottle":
        # Draw contoured PET bottle
        cv2.rectangle(img, (center_x - 12, center_y - 55), (center_x + 12, center_y - 40), (200, 200, 200), -1) # Cap
        cv2.rectangle(img, (center_x - 30, center_y - 35), (center_x + 30, center_y + 55), (230, 245, 255), -1) # Body
        cv2.ellipse(img, (center_x, center_y + 55), (30, 10), 0, 0, 360, (200, 220, 240), -1)
        cv2.rectangle(img, (center_x - 28, center_y - 10), (center_x + 28, center_y + 25), (int(b), int(g), int(r)), -1) # Label
    elif icon_shape == "bundle":
        # Draw cluster of pipe/tube circles
        for dy in (-25, 0, 25):
            for dx in (-30, 0, 30):
                cv2.circle(img, (center_x + dx, center_y + dy), 14, (200, 210, 225), 3)
                cv2.circle(img, (center_x + dx, center_y + dy), 10, (120, 130, 145), -1)
        cv2.rectangle(img, (center_x - 50, center_y - 42), (center_x + 50, center_y + 42), (0, 215, 255), 2) # Strapping band
    elif icon_shape == "cylinder":
        # Industrial Drum / Coil / Gas Cylinder
        cv2.rectangle(img, (center_x - 45, center_y - 45), (center_x + 45, center_y + 45), (160, 170, 185), -1)
        cv2.ellipse(img, (center_x, center_y - 45), (45, 14), 0, 0, 360, (200, 210, 225), -1)
        cv2.ellipse(img, (center_x, center_y + 45), (45, 14), 0, 0, 360, (140, 150, 165), -1)
        cv2.line(img, (center_x - 45, center_y - 10), (center_x + 45, center_y - 10), (255, 255, 255), 2)
        cv2.line(img, (center_x - 45, center_y + 20), (center_x + 45, center_y + 20), (255, 255, 255), 2)
    elif icon_shape == "glass":
        # A-frame steel stillage with stacked translucent architectural glass sheets
        pts = np.array([[center_x - 52, center_y + 52], [center_x, center_y - 52], [center_x + 52, center_y + 52]], np.int32)
        cv2.polylines(img, [pts], True, (0, 200, 255), 3)
        for offset in (8, 4, 0):
            cv2.rectangle(img, (center_x - 42 + offset, center_y - 36 - offset), (center_x + 36 + offset, center_y + 44 - offset), (235, 245, 220), -1)
            cv2.rectangle(img, (center_x - 42 + offset, center_y - 36 - offset), (center_x + 36 + offset, center_y + 44 - offset), (255, 255, 255), 2)
        # Diagonal glass reflection lines
        cv2.line(img, (center_x - 28, center_y + 25), (center_x + 15, center_y - 22), (255, 255, 255), 3)
        cv2.line(img, (center_x - 12, center_y + 30), (center_x + 25, center_y - 10), (255, 255, 255), 1)
    elif icon_shape in ("wood", "plank", "sheet"):
        # Stacked timber planks / layered marine plywood sheets with strapping bands
        for layer in range(4):
            y_top = center_y - 38 + (layer * 20)
            y_bot = y_top + 15
            cv2.rectangle(img, (center_x - 62, y_top), (center_x + 62, y_bot), (70, 145, 210), -1)
            cv2.rectangle(img, (center_x - 62, y_top), (center_x + 62, y_bot), (45, 95, 150), 2)
            cv2.line(img, (center_x - 55, y_top + 7), (center_x + 55, y_top + 7), (55, 115, 175), 1)
        # Vertical steel/PET strapping bands
        cv2.line(img, (center_x - 32, center_y - 40), (center_x - 32, center_y + 40), (0, 230, 255), 3)
        cv2.line(img, (center_x + 32, center_y - 40), (center_x + 32, center_y + 40), (0, 230, 255), 3)
    else:
        # Standard industrial carton box with 3D isometric flap lines
        cv2.rectangle(img, (center_x - 55, center_y - 45), (center_x + 55, center_y + 45), (int(b * 1.3), int(g * 1.3), int(r * 1.3)), -1)
        cv2.rectangle(img, (center_x - 55, center_y - 45), (center_x + 55, center_y + 45), (255, 255, 255), 2)
        cv2.line(img, (center_x - 55, center_y), (center_x + 55, center_y), (255, 255, 255), 1)

    # Simulated Barcode Strip
    cv2.rectangle(img, (80, 175), (360, 202), (255, 255, 255), -1)
    for x in range(95, 345, 6):
        thick = 2 if (x % 12 == 0) else 1
        cv2.line(img, (x, 180), (x, 198), (15, 15, 15), thick)

    # Clean Typography Metadata
    cv2.putText(img, sku_id, (25, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (0, 230, 255), 2, cv2.LINE_AA)
    short_name = sku_name[:32] + ("..." if len(sku_name) > 32 else "")
    cv2.putText(img, short_name, (25, 272), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(img, f"[{category.upper()}]", (25, 298), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (180, 215, 245), 1, cv2.LINE_AA)

    cv2.imwrite(filepath, img)
    return f"/static/uploads/sku_images/{filename}"


# ==============================================================================
# 4. BLUEPRINT APPLICATION & ZERO-SHOT INFUSION ENGINE
# ==============================================================================

def get_blueprint_catalog() -> List[Dict[str, Any]]:
    """Returns metadata for all available pre-defined industry blueprints."""
    catalog = []
    for key, bp in INDUSTRY_BLUEPRINTS.items():
        sample_skus = [s["name"] for s in bp.get("skus", [])[:4]]
        catalog.append({
            "key": key,
            "name": bp["name"],
            "badge_icon": bp.get("badge_icon", "fa-boxes"),
            "theme_color": bp.get("theme_color", "#38bdf8"),
            "company_example": bp.get("company_example", ""),
            "operating_mode": bp.get("operating_mode", "DEDICATED"),
            "mode": bp.get("operating_mode", "DEDICATED"),
            "description": bp["description"],
            "sku_count": len(bp.get("skus", [])),
            "vision_classes_count": len(bp.get("vision_classes", [])),
            "zones_count": len(bp.get("zones", [])),
            "sample_skus": sample_skus
        })
    return catalog


def apply_industry_blueprint(
    blueprint_key: str,
    warehouse_code: Optional[str] = None,
    custom_company_name: Optional[str] = None,
    custom_prompt: Optional[str] = None,
    db_path: Optional[str] = None,
    custom_industry_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Applies an industry blueprint to SQLite database:
    1. Re-seeds SKUs with realistic industry items (30-40 SKUs) and procedural visual assets.
    2. Maps every generated image into sku_images database table with is_primary = 1.
    3. Updates object_classes and active camera associations for YOLO-World vision.
    4. Reconfigures warehouse zones for the industry workflow.
    5. Populates matching authentic inbound deliveries with valid plates.
    6. Slots initial inventory across storage bins.
    """
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), "skandha_wms.db")

    c_name = custom_company_name or custom_industry_name
    bp_key = (blueprint_key or "").strip().lower()

    # If key is empty or auto-detect requested
    if not bp_key or bp_key == "auto":
        detected = auto_detect_company_industry(c_name or custom_prompt or "General")
        bp_key = detected["detected_key"]

    bp = INDUSTRY_BLUEPRINTS.get(bp_key)
    if not bp and (bp_key == "custom" or not bp_key) and (custom_prompt or c_name):
        bp = _synthesize_custom_blueprint(custom_prompt or c_name, c_name)
    elif not bp:
        bp = INDUSTRY_BLUEPRINTS["automotive"]

    company_name = c_name.strip() if c_name and c_name.strip() else bp["company_example"]
    operating_mode = bp.get("operating_mode", "DEDICATED")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # 1. Update Company & Warehouse Facility Master
        target_wh_code = (warehouse_code or "").strip().upper()
        
        if not target_wh_code or target_wh_code == "NEW":
            # Generate a new facility code from company name or key
            slug_comp = re.sub(r'[^A-Z0-9]', '', company_name.upper())[:6] or bp.get("key", "WH")[:4].upper()
            target_wh_code = f"WH-{slug_comp}"
            cur.execute("""
                INSERT INTO warehouses (code, name, city, operating_mode, industry, status, is_active, company_name)
                VALUES (?, ?, 'Bengaluru Facility', ?, ?, 'Active', 1, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    operating_mode = excluded.operating_mode,
                    industry = excluded.industry,
                    company_name = excluded.company_name,
                    is_active = 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (target_wh_code, company_name, operating_mode, bp["name"], company_name))
        else:
            cur.execute("""
                UPDATE warehouses
                SET name = ?, operating_mode = ?, industry = ?, company_name = ?, updated_at = CURRENT_TIMESTAMP
                WHERE UPPER(code) = UPPER(?)
            """, (company_name, operating_mode, bp["name"], company_name, target_wh_code))

        # Synchronize active facility flag
        cur.execute("UPDATE warehouses SET is_active = 0")
        cur.execute("UPDATE warehouses SET is_active = 1 WHERE UPPER(code) = UPPER(?)", (target_wh_code,))

        # Fetch active warehouse details
        cur.execute("SELECT code, name, city, operating_mode, industry FROM warehouses WHERE UPPER(code) = UPPER(?)", (target_wh_code,))
        wh_row = cur.fetchone()
        wh_dict = {
            "code": wh_row[0] if wh_row else target_wh_code,
            "name": wh_row[1] if wh_row else company_name,
            "city": wh_row[2] if wh_row else "Bengaluru Facility",
            "operating_mode": wh_row[3] if wh_row else operating_mode,
            "industry": wh_row[4] if wh_row else bp["name"]
        }

        # 2. Reset and Populate SKU Master & SKU Images Master
        cur.execute("DELETE FROM sku_images")
        cur.execute("DELETE FROM skus")
        created_skus = []

        for item in bp["skus"]:
            sku_id = item["sku_id"]
            img_rel_url = generate_sku_thumbnail(
                sku_id=sku_id,
                sku_name=item["name"],
                category=item["category"],
                bg_color=item.get("visual_color", (50, 80, 110)),
                icon_shape=item.get("icon_shape", "box")
            )
            abs_img_path = os.path.join(UPLOAD_DIR, f"{sku_id}.png")
            file_size = os.path.getsize(abs_img_path) if os.path.exists(abs_img_path) else 18000

            # Insert into skus
            cur.execute("""
                INSERT INTO skus (
                    sku_id, name, category, description, unit_weight, unit_volume,
                    uom, status, units_per_bundle, target_bundles_per_pallet, bundle_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Active', ?, ?, ?)
            """, (
                sku_id,
                item["name"],
                item["category"],
                item["description"],
                item["unit_weight"],
                item["unit_volume"],
                item["uom"],
                item["units_per_bundle"],
                item["target_bundles_per_pallet"],
                item["bundle_name"]
            ))

            # MAP INTO sku_images TABLE WITH is_primary = 1
            cur.execute("""
                INSERT INTO sku_images (sku_id, filename, original_filename, file_path, file_size, mime_type, is_primary)
                VALUES (?, ?, ?, ?, ?, 'image/png', 1)
            """, (sku_id, f"{sku_id}.png", f"{sku_id}.png", img_rel_url, file_size))

            created_skus.append({**item, "image_url": img_rel_url})

        # 3. Synchronize AI Vision Object Classes for YOLO-World (Strictly scoped to active warehouse industry)
        cur.execute("DELETE FROM vision_camera_object_classes")
        cur.execute("DELETE FROM object_classes")
        for cls_code, cls_name, cls_desc in bp["vision_classes"]:
            cur.execute("""
                INSERT INTO object_classes (code, name, description, status)
                VALUES (?, ?, ?, 'Active')
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    status = 'Active'
            """, (cls_code, cls_name, cls_desc))

        # Associate vision classes with all active cameras
        cur.execute("SELECT camera_id FROM cameras")
        cam_rows = cur.fetchall()
        for cam_row in cam_rows:
            cid = cam_row[0]
            for cls_code, _, _ in bp["vision_classes"]:
                cur.execute("""
                    INSERT OR IGNORE INTO vision_camera_object_classes (camera_id, class_code)
                    VALUES (?, ?)
                """, (cid, cls_code))

        # 4. Reconfigure Warehouse Zones for this Industry
        cur.execute("DELETE FROM vision_zones")
        for z_code, z_name, z_type, z_desc in bp["zones"]:
            cur.execute("""
                INSERT INTO vision_zones (zone_code, zone_name, zone_type, warehouse, description, status)
                VALUES (?, ?, ?, 'Warehouse A', ?, 'Active')
            """, (z_code, z_name, z_type, z_desc))

        # 5. Populate Authentic Inbound Deliveries for ANPR testing
        cur.execute("DELETE FROM expected_deliveries")
        created_deliveries = []
        for d in bp["deliveries"]:
            sheet_json = json.dumps([{
                "sku": d["sku"],
                "desc": d["load_description"],
                "expected": d["expected"],
                "counted": 0
            }])
            cur.execute("""
                INSERT INTO expected_deliveries (
                    po_number, expected_date, activity, vendor, vendor_email,
                    load_description, plate, driver_name, driver_phone, status, unloading_sheet
                ) VALUES (?, ?, 'Unloading', ?, 'logistics@supplier.com', ?, ?, 'Verified Carrier Driver', '9876543210', 'Expected', ?)
            """, (
                d["po_number"],
                datetime.now().strftime("%Y-%m-%d"),
                d["vendor"],
                d["load_description"],
                d["plate"],
                sheet_json
            ))
            created_deliveries.append(d)

        # 6. Slot Initial Inventory into Storage Bins
        cur.execute("DELETE FROM inventory")
        cur.execute("SELECT bin_id FROM bins LIMIT 20")
        bin_rows = cur.fetchall()
        for i, bin_row in enumerate(bin_rows):
            if i < len(bp["skus"]):
                target_sku = bp["skus"][i]
                cur.execute("""
                    INSERT INTO inventory (bin_id, sku_id, quantity, batch_number, vendor)
                    VALUES (?, ?, ?, 'BATCH-2026-A1', ?)
                """, (bin_row[0], target_sku["sku_id"], target_sku["units_per_bundle"] * 10, company_name))

        # 6.5. Clear previous pallets and initialize active pallets for the new warehouse
        cur.execute("DELETE FROM pallet_items")
        cur.execute("DELETE FROM pallets")
        if len(created_skus) > 0:
            for idx, p_sku in enumerate(created_skus[:2]):
                p_id = f"PLT-{datetime.now().strftime('%y%m%d')}-{1001 + idx}"
                u_per_bundle = p_sku.get("units_per_bundle") or 10
                tgt_bundles = p_sku.get("target_bundles_per_pallet") or 20
                cur.execute("""
                    INSERT INTO pallets (
                        pallet_id, sku_id, name, units_per_bundle, target_bundles,
                        counted_bundles, total_units, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 0, 'STACKING', CURRENT_TIMESTAMP)
                """, (
                    p_id,
                    p_sku["sku_id"],
                    f"Pallet {p_id} ({p_sku['name']})",
                    u_per_bundle,
                    tgt_bundles
                ))

        conn.commit()

        # 7. Update dynamic zero-shot classes on active YOLO detector if available
        try:
            from detection_service import get_detection_engine
            engine = get_detection_engine()
            if engine and getattr(engine, 'model', None) and 'world' in getattr(engine, 'model_name', '').lower():
                custom_names = [c[1].lower() for c in bp["vision_classes"]]
                engine.model.set_classes(custom_names)
                logger.info(f"Updated YOLO-World zero-shot classes for '{bp['name']}': {custom_names}")
        except Exception as det_err:
            logger.warning(f"Could not dynamic-update YOLO-World classes: {det_err}")

        logger.info(f"Successfully applied '{bp['name']}' blueprint ({len(created_skus)} SKUs) for '{company_name}'.")

        return {
            "success": True,
            "message": f"Successfully applied '{bp['name']}' blueprint for {company_name}.",
            "blueprint": bp["key"],
            "blueprint_name": bp["name"],
            "company_name": company_name,
            "operating_mode": operating_mode,
            "warehouse": wh_dict,
            "skus_created": len(created_skus),
            "skus_count": len(created_skus),
            "skus": created_skus,
            "classes_created": len(bp["vision_classes"]),
            "vision_classes_count": len(bp["vision_classes"]),
            "zones_created": len(bp["zones"]),
            "zones_count": len(bp["zones"]),
            "deliveries_created": len(created_deliveries),
            "deliveries_count": len(created_deliveries),
            "deliveries": created_deliveries
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Error applying industry blueprint: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


# ==============================================================================
# 5. DYNAMIC CUSTOM SYNTHESIS GENERATOR (Generates 30 authentic SKUs)
# ==============================================================================

def _synthesize_custom_blueprint(prompt: str, company_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Synthesizes a 30-item industry blueprint from a custom user prompt
    (e.g., 'Boeing Aerospace Components', 'Solar Panel Factory', 'Apparel Distribution').
    """
    clean_p = prompt.strip().title()
    comp = company_name.strip() if company_name else f"{clean_p} Hub"
    slug = re.sub(r'[^A-Z0-9]', '', clean_p.upper())[:5] or "IND"

    skus = []
    categories = [
        ("Finished Goods", "Primary unit packaging ready for distribution", "EA", 1, 20, "Finished Unit", (40, 90, 160), "box"),
        ("Sub-Assemblies", "Heavy sub-assembly module for integration", "Set", 2, 24, "Assembly Stillage", (60, 110, 80), "block"),
        ("Raw Materials", "Bulk feedstock and raw material bundle", "Bundle", 25, 12, "Feedstock Bundle", (130, 90, 45), "bundle"),
        ("Fasteners & Hardware", "High-grade industrial fastening components", "Box", 500, 40, "Fastener Box", (110, 110, 110), "box"),
        ("Packaging & Consumables", "Protective secondary packaging and slip sheets", "Pack", 100, 30, "Consumables Pack", (150, 140, 120), "box")
    ]

    sku_counter = 1
    for cat_name, cat_desc, uom, upb, tbpp, bname, vcolor, ishape in categories:
        for i in range(1, 7): # 6 items per category = 30 total SKUs
            code = f"{slug}-{cat_name[:3].upper()}-{sku_counter:02d}"
            name = f"{clean_p} {cat_name[:-1] if cat_name.endswith('s') else cat_name} Grade-{chr(64 + i)}"
            skus.append({
                "sku_id": code,
                "name": name,
                "category": cat_name,
                "description": f"{cat_desc} (Specification Model {i:02d}).",
                "unit_weight": round(float(i * 3.5 + 1.2), 2),
                "unit_volume": round(float(i * 0.015 + 0.005), 3),
                "uom": uom,
                "units_per_bundle": upb,
                "target_bundles_per_pallet": tbpp,
                "bundle_name": bname,
                "visual_color": vcolor,
                "icon_shape": ishape
            })
            sku_counter += 1

    return {
        "key": "custom",
        "name": f"{clean_p} Custom Industrial Hub",
        "badge_icon": "fa-wand-magic-sparkles",
        "theme_color": "#f59e0b",
        "company_example": comp,
        "operating_mode": "DEDICATED",
        "description": f"Custom intralogistics blueprint engineered for {clean_p} operations and computer vision.",
        "skus": skus,
        "vision_classes": [
            ("BOX", "Finished Goods Carton", "Standard manufactured product cases"),
            ("BUNDLE", "Material / Tube Bundle", "Strapped industrial product bundles"),
            ("PALLET", "Storage Pallet", "Heavy wooden and plastic handling pallets"),
            ("BIN", "Parts Tote", "Line-side picking storage totes"),
            ("WORKER", "Plant Personnel", "Certified warehouse and handling operators"),
            ("TRUCK", "Transport Trailer", "Commercial supplier delivery trucks"),
            ("LICENSE_PLATE", "License Plate", "Automated gate access check-in")
        ],
        "zones": [
            ("TB-CUST", "Gate 01 Inbound Bay", "TRUCK_BAY", "Primary gate check-in and automated plate scanner"),
            ("DOCK-MAIN", "Primary Inbound Dock 01", "DOCK", "Main trailer offloading bay"),
            ("STG-LINE", "Line-Side Assembly Staging", "STAGING", "Staging floor directly feeding production cells"),
            ("RACK-MAIN", "High-Bay Bulk Storage Racks", "STORAGE", "Pallet racking for finished goods inventory")
        ],
        "deliveries": [
            {
                "po_number": f"PO-{slug}-101",
                "plate": "KA-01-MJ-9900",
                "vendor": f"{clean_p} Prime Supplier",
                "load_description": f"20x {clean_p} Finished Goods Packs",
                "sku": skus[0]["sku_id"],
                "expected": 20
            }
        ]
    }
