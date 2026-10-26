"""
Industry Blueprint Generator Service for W.A.R.L.O.G. WMS
Autonomously scaffolds turn-key warehouse ecosystems:
- Tailored SKU Master (with volumetric dimensions, unit weights, bundle math, and pallet constraints)
- AI Vision Zero-Shot Classes & Camera associations
- Specialized Warehouse Zones (Assembly, Cold Storage, Staging, ESD, Docks)
- Authentic Inbound Deliveries & Vehicle Plates for ANPR testing
- Procedural Visual Image Generation for SKU thumbnails
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
from typing import Dict, Any, List, Optional

logger = logging.getLogger("industry_blueprint_service")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads", "sku_images")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ----------------------------------------------------------------------
# 1. PRE-DEFINED INDUSTRY BLUEPRINT SPECIFICATIONS
# ----------------------------------------------------------------------

INDUSTRY_BLUEPRINTS: Dict[str, Dict[str, Any]] = {
    "automotive": {
        "key": "automotive",
        "name": "Automotive OEM & Parts Assembly",
        "badge_icon": "fa-car",
        "theme_color": "#38bdf8",
        "company_example": "Tata Motors / Hyundai Automotive Hub",
        "operating_mode": "DEDICATED",
        "description": "Powertrain, chassis, steering suspension bundles, A-frame glass dollies, and line-side intralogistics feeding.",
        "skus": [
            {
                "sku_id": "AUTO-ENG-01",
                "name": "4-Cylinder Turbo Engine Block",
                "category": "Powertrain",
                "description": "Cast-iron turbocharged engine block assembly in heavy welded steel transport cradle.",
                "unit_weight": 128.0,
                "unit_volume": 0.42,
                "uom": "EA",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 2,
                "bundle_name": "Engine Cradle",
                "visual_color": (50, 70, 95)
            },
            {
                "sku_id": "AUTO-ROD-01",
                "name": "High-Tensile Steering Tie Rod (Pack 48)",
                "category": "Steering & Suspension",
                "description": "Cold-drawn steel steering tie rods bundled in circular hexagonal cluster straps.",
                "unit_weight": 1.4,
                "unit_volume": 0.008,
                "uom": "Bundle",
                "units_per_bundle": 48,
                "target_bundles_per_pallet": 6,
                "bundle_name": "Circular Tube Pack",
                "visual_color": (90, 110, 130)
            },
            {
                "sku_id": "AUTO-GLASS-01",
                "name": "Laminated Windshield Glass Set",
                "category": "Glass & Trim",
                "description": "Acoustic PVB laminated front windshield glass stacked on vertical rubberized A-frame dolly.",
                "unit_weight": 8.5,
                "unit_volume": 0.05,
                "uom": "Set",
                "units_per_bundle": 10,
                "target_bundles_per_pallet": 2,
                "bundle_name": "A-Frame Stillage",
                "visual_color": (70, 140, 160)
            },
            {
                "sku_id": "AUTO-BMPR-01",
                "name": "Front Bumper Fascia Assembly",
                "category": "Body & Exterior",
                "description": "Color-keyed injection-molded front bumper fascia in nesting foam-lined racks.",
                "unit_weight": 4.6,
                "unit_volume": 0.16,
                "uom": "EA",
                "units_per_bundle": 6,
                "target_bundles_per_pallet": 4,
                "bundle_name": "Nesting Stillage",
                "visual_color": (60, 95, 140)
            },
            {
                "sku_id": "AUTO-BOLT-10",
                "name": "Grade 10.9 Flange Fasteners (100pk)",
                "category": "Fasteners & Hardware",
                "description": "Zinc-flake coated high-strength chassis bolts packaged in heavy-duty picking totes.",
                "unit_weight": 2.2,
                "unit_volume": 0.004,
                "uom": "Pack",
                "units_per_bundle": 10,
                "target_bundles_per_pallet": 24,
                "bundle_name": "Hardware Tote",
                "visual_color": (120, 130, 145)
            }
        ],
        "vision_classes": [
            ("BOX", "Box / Carton", "Standard industrial parts boxes"),
            ("WORKER", "Worker / Personnel", "Plant floor technicians and assembly operators"),
            ("TRUCK", "Truck / Carrier", "Heavy commercial suppliers and logistics carriers"),
            ("PALLET", "Storage Pallet", "Heavy duty wooden and steel stillage pallets"),
            ("FORKLIFT", "Forklift / Vehicle", "Plant tow tractors, tuggers and reach forklifts"),
            ("BUNDLE", "Circular Rod/Pipe Bundle", "Bundled tie rods, exhaust pipes, and steel profiles"),
            ("BIN", "Storage Bin / Tote", "Color-coded picking bins for small fasteners and clips"),
            ("LICENSE_PLATE", "License Plate", "Automated gate entry vehicle plate recognition")
        ],
        "zones": [
            ("TB-AUTO", "Gate 01 Tier-1 Truck Bay", "TRUCK_BAY", "Main security check-in for supplier delivery trailers"),
            ("DOCK-ENG", "Powertrain Inbound Dock 01", "DOCK", "Heavy engine and transmission offloading bay"),
            ("STG-CHASSIS", "Chassis Marriage Staging", "STAGING", "Line-side staging floor for suspension and steering"),
            ("ZONE-STILLAGE", "Body Stamping Stillage Yard", "STORAGE", "High-capacity zone for bumper and door stillages"),
            ("BIN-FASTENERS", "Small Parts Bin Shelving A1-A20", "BIN_AREA", "Fastener and clip picking rack rows")
        ],
        "deliveries": [
            {
                "po_number": "PO-BOSCH-8821",
                "plate": "MH-14-GH-1200",
                "vendor": "Bosch Automotive Systems",
                "load": "48x Steering Tie Rod Bundles",
                "sku": "AUTO-ROD-01",
                "expected": 48
            },
            {
                "po_number": "PO-ASAHI-4490",
                "plate": "DL-01-AB-4050",
                "vendor": "Asahi India Glass (AIS)",
                "load": "20x Laminated Windshield Packs",
                "sku": "AUTO-GLASS-01",
                "expected": 20
            }
        ]
    },

    "beverage": {
        "key": "beverage",
        "name": "Beverage & FMCG Bottling",
        "badge_icon": "fa-bottle-water",
        "theme_color": "#ef4444",
        "company_example": "The Coca-Cola Company / PepsiCo Bottling Hub",
        "operating_mode": "DEDICATED",
        "description": "High-velocity carbonated cans, PET heat-shrink bundles, syrup BIBs, and 80-case pallet stacking.",
        "skus": [
            {
                "sku_id": "COKE-CAN-330",
                "name": "Original Taste 330ml Cans (24-Tray)",
                "category": "Canned Beverages",
                "description": "24-can corrugated tray shrinkwrapped in high-clarity recyclable LDPE film.",
                "unit_weight": 8.6,
                "unit_volume": 0.015,
                "uom": "Tray",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 80,
                "bundle_name": "Can Tray (24pk)",
                "visual_color": (30, 30, 200)
            },
            {
                "sku_id": "COKE-PET-500",
                "name": "500ml PET Bottles (12-Pack Shrinkwrap)",
                "category": "PET Beverages",
                "description": "12-bottle heat-shrink bundle with reinforced carrying tape.",
                "unit_weight": 6.4,
                "unit_volume": 0.012,
                "uom": "Bundle",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 96,
                "bundle_name": "Shrinkwrap Bundle",
                "visual_color": (35, 40, 210)
            },
            {
                "sku_id": "COKE-ZERO-330",
                "name": "Zero Sugar 330ml Cans (24-Tray)",
                "category": "Zero Sugar",
                "description": "24-can matte-black tray of zero sugar beverage for retail distribution.",
                "unit_weight": 8.4,
                "unit_volume": 0.015,
                "uom": "Tray",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 80,
                "bundle_name": "Zero Sugar Tray",
                "visual_color": (20, 20, 20)
            },
            {
                "sku_id": "SPRITE-PET-1.5L",
                "name": "Sprite 1.5L Bottles (6-Pack Case)",
                "category": "Lemon-Lime Soda",
                "description": "Clear green PET 1.5L bottles in 6-bottle corrugated case.",
                "unit_weight": 9.5,
                "unit_volume": 0.022,
                "uom": "Case",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 64,
                "bundle_name": "PET Case (6pk)",
                "visual_color": (40, 160, 60)
            },
            {
                "sku_id": "COKE-SYRUP-BIB",
                "name": "Fountain Syrup Bag-in-Box 20L",
                "category": "Concentrates",
                "description": "Heavy-duty commercial post-mix dispenser concentrate syrup in corrugated carton.",
                "unit_weight": 24.2,
                "unit_volume": 0.035,
                "uom": "BIB",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 36,
                "bundle_name": "Heavy BIB Carton",
                "visual_color": (80, 25, 25)
            }
        ],
        "vision_classes": [
            ("BOX", "Beverage Tray / Case", "Can trays, shrinkwrap cases, and concentrate boxes"),
            ("PALLET", "Euro/Chep Pallet", "High-density stacked full beverage pallets (80 cases)"),
            ("BUNDLE", "Shrinkwrapped Multi-Pack", "12-pack and 24-pack shrinkwrap packs"),
            ("WORKER", "Warehouse Personnel", "Dock loaders, forklift pilots, and sanitation staff"),
            ("TRUCK", "Distribution Trailer", "Inter-city trailers and Direct Store Delivery (DSD) trucks"),
            ("FORKLIFT", "Counterbalance Forklift", "Twin-pallet reach and counterbalance trucks"),
            ("BIN", "Storage Location", "Pallet flow lanes and staging floor bays"),
            ("LICENSE_PLATE", "License Plate", "Automated distribution fleet gate pass logging")
        ],
        "zones": [
            ("TB-BEV", "Gate 01 Fleet Inbound Bay", "TRUCK_BAY", "Primary gate check-in for packaging suppliers and route trucks"),
            ("DOCK-BOTTLING", "Bottling Line Outfeed Dock", "DOCK", "Automated conveyor offloading from high-speed canning lines"),
            ("STG-FAST-DSD", "Direct Store Delivery (DSD) Staging", "STAGING", "Fast-turnaround staging for local store distribution"),
            ("ZONE-RACK-BEV", "High-Bay Pallet Flow Racks", "STORAGE", "FIFO high-density gravity pallet flow racking"),
            ("COLD-CONC", "Concentrate Syrup Cold Vault", "STORAGE", "Climate-controlled vault for syrup concentrates")
        ],
        "deliveries": [
            {
                "po_number": "PO-BALL-CAN-9021",
                "plate": "KA-04-E-5510",
                "vendor": "Ball Beverage Packaging Corp",
                "load": "96x 330ml Can Trays",
                "sku": "COKE-CAN-330",
                "expected": 96
            },
            {
                "po_number": "PO-RESIN-310",
                "plate": "GJ-06-TR-8840",
                "vendor": "Alpla Plastic Polymers",
                "load": "64x 1.5L PET Cases",
                "sku": "SPRITE-PET-1.5L",
                "expected": 64
            }
        ]
    },

    "electronics": {
        "key": "electronics",
        "name": "Consumer Electronics & Appliances",
        "badge_icon": "fa-tv",
        "theme_color": "#a855f7",
        "company_example": "Samsung Electronics / Apple Distribution Hub",
        "operating_mode": "DEDICATED",
        "description": "Smart TVs, smartphone master cartons, lithium battery crates, and ESD-safe cleanroom staging.",
        "skus": [
            {
                "sku_id": "ELEC-TV-55",
                "name": "55-Inch 4K UHD Smart QLED TV",
                "category": "Display Panels",
                "description": "Ultra-slim 55-inch display television in reinforced shock-cushioned retail carton.",
                "unit_weight": 18.2,
                "unit_volume": 0.18,
                "uom": "EA",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 12,
                "bundle_name": "TV Master Carton",
                "visual_color": (40, 50, 75)
            },
            {
                "sku_id": "ELEC-PHN-S24",
                "name": "Galaxy Smartphone Master Carton (20pk)",
                "category": "Mobile Devices",
                "description": "Tamper-evident security master carton containing 20 retail smartphone boxes.",
                "unit_weight": 5.2,
                "unit_volume": 0.025,
                "uom": "Carton",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 48,
                "bundle_name": "Security Shipper",
                "visual_color": (60, 60, 90)
            },
            {
                "sku_id": "ELEC-BATT-LION",
                "name": "Lithium-Ion Battery Pack Module (48V)",
                "category": "Energy & Batteries",
                "description": "UN3480 certified Class 9 hazardous goods lithium-ion energy module.",
                "unit_weight": 14.5,
                "unit_volume": 0.04,
                "uom": "Pack",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 24,
                "bundle_name": "UN3480 Hazmat Crate",
                "visual_color": (160, 90, 30)
            },
            {
                "sku_id": "ELEC-PCB-REEL",
                "name": "SMD High-Density Component Reel (5000ct)",
                "category": "SMD Components",
                "description": "Anti-static tape-and-reel surface mount resistors and chips for pick-and-place lines.",
                "unit_weight": 0.8,
                "unit_volume": 0.003,
                "uom": "Reel",
                "units_per_bundle": 5,
                "target_bundles_per_pallet": 100,
                "bundle_name": "ESD Reel Pack",
                "visual_color": (30, 110, 100)
            }
        ],
        "vision_classes": [
            ("BOX", "Electronics Master Carton", "TV cartons, phone shippers, and component boxes"),
            ("PALLET", "Cleanroom Plastic Pallet", "Anti-static plastic pallets for high-tech cleanrooms"),
            ("BIN", "ESD Storage Tote", "Conductive carbon-fiber black and blue electronics totes"),
            ("WORKER", "Technician / Operator", "ESD smock personnel and cleanroom logistics staff"),
            ("TRUCK", "Air Freight Bonded Truck", "Temperature-controlled air freight express trailers"),
            ("FORKLIFT", "Electric Reach Truck", "Zero-emission electric warehouse reach trucks"),
            ("LICENSE_PLATE", "License Plate", "High-security bonded transport gate access")
        ],
        "zones": [
            ("TB-ELEC", "Gate 01 Security Inbound Bay", "TRUCK_BAY", "High-security biometric and ANPR gate bay"),
            ("DOCK-ELEC", "Air-Freight Unloading Dock 01", "DOCK", "Sealed dock shelter for humidity-controlled inbound freight"),
            ("ESD-SAFE", "ESD Cleanroom Sorting Bay", "SORTING", "Static-dissipative floor area for component breakdown"),
            ("CAGE-HIGHVAL", "Biometric High-Value Vault", "STORAGE", "Restricted-access security cage for flagship smartphones"),
            ("RACK-TV", "Vertical Bulk TV Pallet Racks", "STORAGE", "Narrow-aisle racking for large screen displays")
        ],
        "deliveries": [
            {
                "po_number": "PO-LG-DISP-401",
                "plate": "TN-09-CQ-3301",
                "vendor": "LG Display Logistics",
                "load": "24x 55-inch Smart TV Pallets",
                "sku": "ELEC-TV-55",
                "expected": 24
            },
            {
                "po_number": "PO-CORNING-109",
                "plate": "KA-03-MK-7720",
                "vendor": "Corning Gorilla Glass Logistics",
                "load": "48x Mobile Component Master Cartons",
                "sku": "ELEC-PHN-S24",
                "expected": 48
            }
        ]
    },

    "pharma": {
        "key": "pharma",
        "name": "Pharmaceuticals & Cold-Chain Logistics",
        "badge_icon": "fa-prescription-bottle-medical",
        "theme_color": "#10b981",
        "company_example": "Pfizer / Sun Pharma Global Distribution",
        "operating_mode": "DEDICATED",
        "description": "Ultra-cold vaccine storage (-20°C), sterile blister packs, tamper-evident shippers, and strict compliance.",
        "skus": [
            {
                "sku_id": "PHRM-VAC-VIAL",
                "name": "Cold-Chain Vaccine Vial Tray (-20°C)",
                "category": "Vaccines & Biologics",
                "description": "Insulated vacuum-panel dry-ice shipper containing 100 sterile vaccine vials.",
                "unit_weight": 2.4,
                "unit_volume": 0.009,
                "uom": "Tray",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 60,
                "bundle_name": "Dry-Ice Shipper",
                "visual_color": (30, 130, 140)
            },
            {
                "sku_id": "PHRM-BLIST-CART",
                "name": "Antibiotic Blister Shipper Carton (1000ct)",
                "category": "Solid Orals",
                "description": "Tamper-sealed serialized shipper carton with 1,000 unit-dose blister strips.",
                "unit_weight": 4.5,
                "unit_volume": 0.02,
                "uom": "Carton",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 40,
                "bundle_name": "Shipper Carton",
                "visual_color": (40, 110, 80)
            },
            {
                "sku_id": "PHRM-IV-DRIP",
                "name": "Sterile Saline IV Infusion (500ml 24pk)",
                "category": "Large Volume Parenterals",
                "description": "Corrugated master case containing 24 sterile 0.9% saline infusion bags.",
                "unit_weight": 13.0,
                "unit_volume": 0.028,
                "uom": "Case",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 32,
                "bundle_name": "Infusion Shipper",
                "visual_color": (50, 120, 170)
            }
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
            {
                "po_number": "PO-PFIZER-1090",
                "plate": "MH-01-AX-9912",
                "vendor": "Thermo King Reefer Logistics",
                "load": "60x Cold-Chain Vaccine Crates",
                "sku": "PHRM-VAC-VIAL",
                "expected": 60
            }
        ]
    },

    "metals": {
        "key": "metals",
        "name": "Heavy Metals & Industrial Profiles",
        "badge_icon": "fa-layer-group",
        "theme_color": "#eab308",
        "company_example": "Tata Steel / Jindal Steel & Power Hub",
        "operating_mode": "DEDICATED",
        "description": "Bundled hollow steel pipes (circular packs of 48/84), galvanized C-studs, rebar, and crane staging.",
        "skus": [
            {
                "sku_id": "STL-TUBE-50",
                "name": "50mm OD Carbon Steel Pipes (Bundle of 48)",
                "category": "Hollow Sections",
                "description": "Heavy-wall circular structural steel pipes strapped with high-tensile steel bands.",
                "unit_weight": 320.0,
                "unit_volume": 0.35,
                "uom": "Bundle",
                "units_per_bundle": 48,
                "target_bundles_per_pallet": 4,
                "bundle_name": "Hexagonal Pipe Bundle",
                "visual_color": (80, 85, 95)
            },
            {
                "sku_id": "STL-CSTUD-75",
                "name": "75mm Galvanized C-Stud Framing (Pack 36)",
                "category": "Framing Channels",
                "description": "Cold-rolled galvanized structural steel drywall framing channels.",
                "unit_weight": 180.0,
                "unit_volume": 0.28,
                "uom": "Bundle",
                "units_per_bundle": 36,
                "target_bundles_per_pallet": 6,
                "bundle_name": "Strapped C-Stud Pack",
                "visual_color": (120, 125, 135)
            },
            {
                "sku_id": "STL-REBAR-12",
                "name": "12mm TMT High-Yield Rebar (Bundle of 84)",
                "category": "Concrete Reinforcement",
                "description": "Fe-550D seismic resistant ribbed reinforcement bars bundled in full lengths.",
                "unit_weight": 448.0,
                "unit_volume": 0.40,
                "uom": "Bundle",
                "units_per_bundle": 84,
                "target_bundles_per_pallet": 2,
                "bundle_name": "Heavy Rebar Pack",
                "visual_color": (95, 75, 65)
            }
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
            {
                "po_number": "PO-TATA-STL-904",
                "plate": "JH-05-CB-7810",
                "vendor": "Tata Steel Jamshedpur Works",
                "load": "4x Hexagonal Pipe Bundles (192 tubes)",
                "sku": "STL-TUBE-50",
                "expected": 4
            }
        ]
    },

    "3pl": {
        "key": "3pl",
        "name": "3PL Commercial Multi-Client Hub",
        "badge_icon": "fa-cubes-stacked",
        "theme_color": "#06b6d4",
        "company_example": "Skandha Global 3PL & CFS Logistics Hub",
        "operating_mode": "3PL",
        "description": "Shared commercial facility storing mixed goods for multiple clients (Electronics, Auto, FMCG, Packaging).",
        "skus": [
            {
                "sku_id": "3PL-SAMS-TV",
                "name": "[Samsung] 55-inch 4K Display Panel",
                "category": "Client: Samsung Electronics",
                "description": "Commercial multi-client client inventory for regional electronics distribution.",
                "unit_weight": 18.0,
                "unit_volume": 0.18,
                "uom": "Carton",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 12,
                "bundle_name": "TV Shipper",
                "visual_color": (40, 50, 80)
            },
            {
                "sku_id": "3PL-TATA-PARTS",
                "name": "[Tata] Tier-1 High-Tensile Rod Pack",
                "category": "Client: Tata AutoComp",
                "description": "Steering and suspension components stored under 3PL consignment agreement.",
                "unit_weight": 1.4,
                "unit_volume": 0.008,
                "uom": "Bundle",
                "units_per_bundle": 48,
                "target_bundles_per_pallet": 6,
                "bundle_name": "Tie Rod Bundle",
                "visual_color": (80, 95, 115)
            },
            {
                "sku_id": "3PL-NESTLE-BOX",
                "name": "[Nestle] Dry Grocery Master Shipper",
                "category": "Client: Nestle FMCG",
                "description": "Corrugated shipper carton containing packaged consumer goods.",
                "unit_weight": 7.2,
                "unit_volume": 0.016,
                "uom": "Case",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 72,
                "bundle_name": "Shipper Case",
                "visual_color": (150, 40, 40)
            }
        ],
        "vision_classes": [
            ("BOX", "Box / Carton", "Multi-client consumer boxes and master shippers"),
            ("PALLET", "Storage Pallet", "Standard GMA and Euro warehouse pallets"),
            ("BUNDLE", "Bundled Goods / Pack", "Strapped industrial packs and shrinkwraps"),
            ("BIN", "Storage Bin / Tote", "Shared rack storage bin locations"),
            ("WORKER", "Logistics Staff", "3PL warehouse dock loaders and supervisors"),
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
            {
                "po_number": "PO-SAMS-8820",
                "plate": "KA-03-KY-0875",
                "vendor": "Samsung Supply Chain Logistics",
                "load": "12x 55-inch Smart TV Pallets",
                "sku": "3PL-SAMS-TV",
                "expected": 12
            },
            {
                "po_number": "PO-TATA-3101",
                "plate": "MH-12-DE-1432",
                "vendor": "Tata AutoComp Delivery Fleet",
                "load": "6x Tier-1 Rod Packs",
                "sku": "3PL-TATA-PARTS",
                "expected": 6
            }
        ]
    }
}


# ----------------------------------------------------------------------
# 2. BLUEPRINT CATALOG & PRESET INTROSPECTION
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# 3. PROCEDURAL IMAGE ASSET GENERATOR
# ----------------------------------------------------------------------

def generate_sku_thumbnail(sku_id: str, sku_name: str, category: str, bg_color: tuple) -> str:
    """
    Renders a high-resolution, modern technical product card thumbnail
    and saves it to static/uploads/sku_images/<sku_id>.png
    """
    filename = f"{sku_id}.png"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # 400x300 canvas
    img = np.zeros((300, 400, 3), dtype=np.uint8)
    b, g, r = bg_color
    img[:] = (int(b * 0.4), int(g * 0.4), int(r * 0.4))

    # Gradient highlight
    cv2.rectangle(img, (15, 15), (385, 285), (int(b * 0.8), int(g * 0.8), int(r * 0.8)), -1)
    cv2.rectangle(img, (15, 15), (385, 285), (200, 220, 240), 2)

    # Central geometric product icon box
    cv2.rectangle(img, (80, 50), (320, 190), (int(b * 1.2), int(g * 1.2), int(r * 1.2)), -1)
    cv2.rectangle(img, (80, 50), (320, 190), (255, 255, 255), 2)
    cv2.line(img, (80, 120), (320, 120), (255, 255, 255), 1)

    # Draw simulated barcode lines
    for x in range(100, 300, 7):
        thick = 2 if (x % 14 == 0) else 1
        cv2.line(img, (x, 135), (x, 175), (255, 255, 255), thick)

    # SKU ID & Title text
    cv2.putText(img, sku_id, (30, 225), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 230, 255), 2)
    short_name = sku_name[:28] + ("..." if len(sku_name) > 28 else "")
    cv2.putText(img, short_name, (30, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.putText(img, f"[{category.upper()}]", (30, 272), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 210, 240), 1)

    cv2.imwrite(filepath, img)
    return f"/static/uploads/sku_images/{filename}"


# ----------------------------------------------------------------------
# 4. BLUEPRINT APPLICATION ENGINE
# ----------------------------------------------------------------------

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
    1. Re-seeds SKUs with realistic industry items and procedural image assets.
    2. Updates object_classes and camera enabled classes for YOLO vision.
    3. Reconfigures warehouse zones for the industry workflow.
    4. Populates matching realistic inbound deliveries with valid plates.
    """
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), "skandha_wms.db")

    c_name = custom_company_name or custom_industry_name
    bp_key = (blueprint_key or "").strip().lower()

    bp = INDUSTRY_BLUEPRINTS.get(bp_key)
    if not bp and (bp_key == "custom" or not bp_key) and custom_prompt:
        bp = _synthesize_custom_blueprint(custom_prompt, c_name)
    elif not bp:
        bp = INDUSTRY_BLUEPRINTS["automotive"]

    company_name = c_name.strip() if c_name and c_name.strip() else bp["company_example"]
    operating_mode = bp.get("operating_mode", "DEDICATED")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # 1. Update Company & Warehouse Master
        target_wh_code = (warehouse_code or "").strip().upper()
        
        if not target_wh_code:
            # Generate a new warehouse code based on the blueprint key
            prefix = bp.get("key", "IND")[:4].upper()
            target_wh_code = f"WH-{prefix}"
            cur.execute("""
                INSERT INTO warehouses (code, name, city, operating_mode, industry, status, is_active)
                VALUES (?, ?, 'Bengaluru Facility', ?, ?, 'Active', 1)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    operating_mode = excluded.operating_mode,
                    industry = excluded.industry,
                    is_active = 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (target_wh_code, company_name, operating_mode, bp["name"]))
        else:
            cur.execute("""
                UPDATE warehouses
                SET name = ?, operating_mode = ?, industry = ?, updated_at = CURRENT_TIMESTAMP
                WHERE UPPER(code) = UPPER(?)
            """, (company_name, operating_mode, bp["name"], target_wh_code))

        # Ensure active facility flag is synchronized
        cur.execute("UPDATE warehouses SET is_active = 0")
        cur.execute("UPDATE warehouses SET is_active = 1 WHERE UPPER(code) = UPPER(?)", (target_wh_code,))

        # Fetch active warehouse details
        cur.execute("SELECT code, name, city, operating_mode, industry FROM warehouses WHERE UPPER(code) = UPPER(?)", (target_wh_code,))
        wh_row = cur.fetchone()
        wh_dict = {
            "code": wh_row[0] if wh_row else target_wh_code,
            "name": wh_row[1] if wh_row else company_name,
            "city": wh_row[2] if wh_row else "Bengaluru",
            "operating_mode": wh_row[3] if wh_row else operating_mode,
            "industry": wh_row[4] if wh_row else bp["name"]
        }

        # 2. Reset and Populate SKU Master
        cur.execute("DELETE FROM skus")
        created_skus = []
        for item in bp["skus"]:
            sku_id = item["sku_id"]
            img_url = generate_sku_thumbnail(
                sku_id=sku_id,
                sku_name=item["name"],
                category=item["category"],
                bg_color=item.get("visual_color", (50, 80, 110))
            )

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
            created_skus.append({**item, "image_url": img_url})

        # 3. Synchronize AI Vision Object Classes
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
                "desc": d["load"],
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
                d["load"],
                d["plate"],
                sheet_json
            ))
            created_deliveries.append(d)

        conn.commit()

        # Update dynamic zero-shot classes on active YOLO detector if available
        try:
            from detection_service import get_detection_engine
            engine = get_detection_engine()
            if engine and getattr(engine, 'model', None) and 'world' in getattr(engine, 'model_name', '').lower():
                custom_names = [c[1].lower() for c in bp["vision_classes"]]
                engine.model.set_classes(custom_names)
                logger.info(f"Updated YOLO-World zero-shot classes for '{bp['name']}': {custom_names}")
        except Exception as det_err:
            logger.warning(f"Could not dynamic-update YOLO-World classes: {det_err}")

        logger.info(f"Successfully applied '{bp['name']}' blueprint for '{company_name}'.")

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
        logger.error(f"Error applying industry blueprint '{blueprint_key}': {e}")
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        conn.close()


def _synthesize_custom_blueprint(prompt: str, company_name: Optional[str]) -> Dict[str, Any]:
    """
    Intelligently synthesizes a custom industry blueprint from a user prompt.
    E.g. 'Solar Panel Manufacturer' -> Solar Modules, Junction Boxes, Inverter Crates.
    """
    clean_p = prompt.strip().title()
    comp = company_name.strip() if company_name else f"{clean_p} Enterprise Hub"
    slug = re.sub(r'[^A-Z0-9]', '', clean_p.upper())[:6] or "CUST"

    return {
        "key": "custom",
        "name": f"{clean_p} Industry Hub",
        "badge_icon": "fa-wand-magic-sparkles",
        "theme_color": "#f59e0b",
        "company_example": comp,
        "operating_mode": "DEDICATED",
        "description": f"Specialized warehouse intralogistics for {clean_p} products, components, and automated sorting.",
        "skus": [
            {
                "sku_id": f"{slug}-UNIT-01",
                "name": f"{clean_p} Primary Finished Unit",
                "category": "Finished Goods",
                "description": f"Standard manufactured {clean_p} unit packaged in industrial protective shipper.",
                "unit_weight": 16.5,
                "unit_volume": 0.08,
                "uom": "EA",
                "units_per_bundle": 1,
                "target_bundles_per_pallet": 20,
                "bundle_name": "Finished Goods Pack",
                "visual_color": (50, 100, 160)
            },
            {
                "sku_id": f"{slug}-COMP-02",
                "name": f"{clean_p} Heavy Component Module",
                "category": "Sub-Assemblies",
                "description": f"High-grade component assembly for {clean_p} integration.",
                "unit_weight": 8.0,
                "unit_volume": 0.035,
                "uom": "Set",
                "units_per_bundle": 4,
                "target_bundles_per_pallet": 32,
                "bundle_name": "Assembly Stillage",
                "visual_color": (80, 120, 80)
            },
            {
                "sku_id": f"{slug}-RAW-03",
                "name": f"{clean_p} Raw Material Feedstock (Pack 50)",
                "category": "Raw Materials",
                "description": f"Inbound bulk material feed pack for continuous manufacturing.",
                "unit_weight": 2.5,
                "unit_volume": 0.012,
                "uom": "Bundle",
                "units_per_bundle": 50,
                "target_bundles_per_pallet": 12,
                "bundle_name": "Feedstock Bundle",
                "visual_color": (140, 90, 40)
            }
        ],
        "vision_classes": [
            ("BOX", "Finished Goods Carton", "Standard manufactured product cases"),
            ("BUNDLE", "Component Bundle", "Material and sub-assembly strapped bundles"),
            ("PALLET", "Storage Pallet", "Heavy wooden/plastic handling pallets"),
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
                "load": f"20x {clean_p} Finished Goods Packs",
                "sku": f"{slug}-UNIT-01",
                "expected": 20
            }
        ]
    }
