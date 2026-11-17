"""
Ownership backfill for existing rows (RBAC plan, "Migration" steps 6-8; Phase 3A).

propose(conn)  -> evidence-based proposal: every row of every scoped table gets a company
                  (and a warehouse for warehouse-level tables) or stays unassigned (NULL:
                  visible to the Platform Admin only). Nothing is written.
approve(conn)  -> stores the proposal as approved (table rbac_ownership_approval).
apply(conn)    -> run by migration step 007 only when an approval exists: writes exactly the
                  approved assignments; rows created after the approval get the same rules.

Rules (first match wins, the evidence is recorded per row)
  * template copies: a SKU, object class, zone or delivery whose code comes from an industry
    template belongs to the one warehouse recorded with that template's industry
  * dependent rows follow their parent: SKU images and stock follow the SKU, gate passes follow
    their delivery (PO or plate), vehicle log and invoices follow the gate pass, pallets and
    counting submissions follow their SKU or pallet, bins follow the stock they hold, cameras
    follow the zones/classes linked to them
  * gate passes with no link to any delivery are early test records: they go to the platform
    owner's default warehouse and are marked legacy_test = 1
  * template sample deliveries and pallets are marked is_demo = 1
  * anything else stays unassigned
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import rbac_scope

APPROVAL_TABLE = """
CREATE TABLE IF NOT EXISTS rbac_ownership_approval (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_json TEXT NOT NULL,
    proposal_sha256 TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    applied_at TIMESTAMP
)
"""


def _templates() -> Dict[str, Dict[str, Any]]:
    from industry_blueprint_service import INDUSTRY_BLUEPRINTS
    out = {}
    for key, bp in INDUSTRY_BLUEPRINTS.items():
        out[key] = {
            "name": bp["name"],
            "skus": {s["sku_id"] for s in bp.get("skus", [])},
            "classes": {c[0] for c in bp.get("vision_classes", [])},
            "zones": {z[0] for z in bp.get("zones", [])},
            "pos": {d["po_number"] for d in bp.get("deliveries", [])},
            "plates": {re.sub(r"[^A-Z0-9]", "", str(d.get("plate", "")).upper()) for d in bp.get("deliveries", [])},
        }
    return out


class _Ctx:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.templates = _templates()
        self.wh = {r[0]: {"code": r[1], "company_id": r[2], "industry": r[3]}
                   for r in conn.execute("SELECT id, code, company_id, industry FROM warehouses")}
        # template key -> the single warehouse recorded with that industry (or None if 0 / several)
        self.template_wh: Dict[str, Optional[int]] = {}
        for key, t in self.templates.items():
            ids = [wid for wid, w in self.wh.items() if (w["industry"] or "").strip() == t["name"]]
            self.template_wh[key] = ids[0] if len(ids) == 1 else None

    LABELS = {"skus": "SKU", "classes": "object class", "zones": "zone", "pos": "delivery"}

    def dominant_template(self, kind: str, codes) -> Optional[str]:
        """The one template (with a recorded warehouse) that contains every code present."""
        codes = set(codes)
        if not codes:
            return None
        keys = [k for k, t in self.templates.items() if codes <= t[kind] and self.template_wh[k]]
        return keys[0] if len(keys) == 1 else None

    def wh_for_code(self, kind: str, code: str, dominant: Optional[str] = None) -> Tuple[Optional[int], str]:
        label = self.LABELS[kind]
        if dominant and code in self.templates[dominant][kind]:
            wid = self.template_wh[dominant]
            return wid, (f"{label} '{code}': the whole current set matches the {self.wh[wid]['industry']} "
                         f"template applied to {self.wh[wid]['code']}")
        hits = {self.template_wh[k] for k, t in self.templates.items() if code in t[kind] and self.template_wh[k]}
        if len(hits) == 1:
            wid = hits.pop()
            return wid, f"{label} '{code}' comes from the {self.wh[wid]['industry']} template applied to {self.wh[wid]['code']}"
        return None, ""

    def company_of(self, wid: Optional[int]) -> Optional[int]:
        return self.wh[wid]["company_id"] if wid in self.wh else None

    def owner_default_warehouse(self) -> Optional[int]:
        row = self.conn.execute("""
            SELECT w.id FROM users u JOIN warehouses w ON UPPER(w.code) = UPPER(u.assigned_warehouse_code)
            WHERE u.is_platform_admin = 1 ORDER BY u.id LIMIT 1
        """).fetchone()
        return row[0] if row else None


def _cols(conn, table) -> List[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def propose(conn: sqlite3.Connection) -> Dict[str, Any]:
    ctx = _Ctx(conn)
    plan: Dict[str, List[Dict[str, Any]]] = {}

    def add(table, rowid, key, wid=None, company=None, evidence="", **flags):
        company = company if company is not None else ctx.company_of(wid)
        plan.setdefault(table, []).append({
            "rowid": rowid, "key": key, "company_id": company,
            "warehouse_id": wid if table in rbac_scope.WAREHOUSE_TABLES else None,
            "evidence": evidence or "no evidence: left unassigned (Platform Admin only)",
            **flags})

    sku_wh: Dict[str, Optional[int]] = {}
    dom = ctx.dominant_template("skus", [r[0] for r in conn.execute("SELECT sku_id FROM skus")])
    for rowid, sku in conn.execute("SELECT rowid, sku_id FROM skus"):
        wid, ev = ctx.wh_for_code("skus", sku, dom)
        sku_wh[sku] = wid
        add("skus", rowid, sku, company=ctx.company_of(wid), evidence=ev)
    for rowid, sku in conn.execute("SELECT rowid, sku_id FROM sku_images"):
        wid = sku_wh.get(sku)
        add("sku_images", rowid, sku, company=ctx.company_of(wid), evidence=f"image of SKU {sku}" if wid else "")

    class_wh: Dict[str, Optional[int]] = {}
    dom = ctx.dominant_template("classes", [r[0] for r in conn.execute("SELECT code FROM object_classes")])
    for rowid, code in conn.execute("SELECT rowid, code FROM object_classes"):
        wid, ev = ctx.wh_for_code("classes", code, dom)
        class_wh[code] = wid
        add("object_classes", rowid, code, company=ctx.company_of(wid), evidence=ev)

    glass_wh = ctx.template_wh.get("glass")
    for rowid, pid in conn.execute("SELECT rowid, id FROM glass_measurement_profiles"):
        add("glass_measurement_profiles", rowid, pid, company=ctx.company_of(glass_wh),
            evidence="glass measurement profile: belongs to the glass industry workspace" if glass_wh else "")
    for rowid, code in conn.execute("SELECT rowid, worker_code FROM trained_workers"):
        add("trained_workers", rowid, code)

    zone_wh: Dict[int, Optional[int]] = {}
    dom = ctx.dominant_template("zones", [r[0] for r in conn.execute("SELECT zone_code FROM vision_zones")])
    for rowid, zid, code in conn.execute("SELECT rowid, id, zone_code FROM vision_zones"):
        wid, ev = ctx.wh_for_code("zones", code, dom)
        zone_wh[zid] = wid
        add("vision_zones", rowid, code, wid, evidence=ev)

    po_wh: Dict[str, Optional[int]] = {}
    plate_wh: Dict[str, Optional[int]] = {}
    for rowid, po, plate in conn.execute("SELECT rowid, po_number, plate FROM expected_deliveries"):
        wid, ev = ctx.wh_for_code("pos", po)
        po_wh[po] = wid
        if plate and wid:
            plate_wh[re.sub(r"[^A-Z0-9]", "", plate.upper())] = wid
        add("expected_deliveries", rowid, po, wid, evidence=ev, is_demo=1 if wid else None)

    gp_wh: Dict[str, Tuple[Optional[int], bool]] = {}
    owner_wh = ctx.owner_default_warehouse()
    for rowid, gid, po, plate in conn.execute("SELECT rowid, id, po_number, plate FROM gate_passes"):
        clean = re.sub(r"[^A-Z0-9]", "", str(plate or "").upper())
        if po and po_wh.get(po):
            wid, ev, legacy = po_wh[po], f"gate pass for delivery {po}", False
        elif clean and plate_wh.get(clean):
            wid, ev, legacy = plate_wh[clean], f"gate pass for plate {plate} of a delivery", False
        else:
            wid, legacy = owner_wh, True
            ev = ("no link to any delivery: early test record, kept with the platform owner's default "
                  "warehouse and marked legacy_test") if owner_wh else ""
        gp_wh[gid] = (wid, legacy)
        add("gate_passes", rowid, gid, wid, evidence=ev, legacy_test=1 if legacy and wid else None)
    for table in ("vehicle_log", "invoices"):
        for rowid, rid, gp in conn.execute(f"SELECT rowid, id, gp_id FROM {table}"):
            wid, legacy = gp_wh.get(gp, (None, False))
            flags = {"legacy_test": 1} if table == "vehicle_log" and legacy and wid else {}
            add(table, rowid, rid, wid, evidence=f"follows gate pass {gp}" if wid else "", **flags)

    company_template_wh = {ctx.company_of(w): w for w in ctx.template_wh.values() if w}

    def wh_for_sku(sku):
        wid = sku_wh.get(sku)
        return wid if wid else None

    pallet_wh: Dict[str, Optional[int]] = {}
    for rowid, pid, sku, name in conn.execute("SELECT rowid, pallet_id, sku_id, name FROM pallets"):
        wid = wh_for_sku(sku)
        pallet_wh[pid] = wid
        demo = bool(wid) and re.fullmatch(r"Pallet PLT-\d{6}-\d+ \(.+\)", str(name or "")) is not None
        add("pallets", rowid, pid, wid, evidence=f"pallet of SKU {sku}" if wid else "", is_demo=1 if demo else None)

    bin_wh: Dict[str, set] = {}
    for rowid, iid, bin_id, sku in conn.execute("SELECT rowid, id, bin_id, sku_id FROM inventory"):
        wid = wh_for_sku(sku)
        if wid:
            bin_wh.setdefault(bin_id, set()).add(wid)
        add("inventory", rowid, iid, wid, evidence=f"stock of SKU {sku}" if wid else "")
    for rowid, bin_id in conn.execute("SELECT rowid, bin_id FROM bins"):
        whs = bin_wh.get(bin_id, set())
        wid = next(iter(whs)) if len(whs) == 1 else None
        add("bins", rowid, bin_id, wid, evidence=f"holds stock of {ctx.wh[wid]['code']}" if wid else "")
    bin_owner = {}
    for b, whs in bin_wh.items():
        if len(whs) == 1:
            bin_owner[b] = next(iter(whs))
    for rowid, sid, sku, pal, b in conn.execute(
            "SELECT rowid, id, sku_id, pallet_id, bin_id FROM vision_counting_submissions"):
        if wh_for_sku(sku):
            wid, ev = wh_for_sku(sku), f"count for SKU {sku}"
        elif pallet_wh.get(pal):
            wid, ev = pallet_wh[pal], f"count for pallet {pal}"
        elif bin_owner.get(b):
            wid, ev = bin_owner[b], f"count recorded against bin {b}, which belongs to {ctx.wh[bin_owner[b]]['code']}"
        else:
            wid, ev = None, ""
        add("vision_counting_submissions", rowid, sid, wid, evidence=ev)

    cam_links: Dict[str, set] = {}
    for cid, zid in conn.execute("SELECT camera_id, zone_id FROM vision_zone_cameras"):
        if zone_wh.get(zid):
            cam_links.setdefault(cid, set()).add(zone_wh[zid])
    for cid, code in conn.execute("SELECT camera_id, class_code FROM vision_camera_object_classes"):
        if class_wh.get(code):
            cam_links.setdefault(cid, set()).add(class_wh[code])
    for rowid, cid in conn.execute("SELECT rowid, camera_id FROM cameras"):
        whs = cam_links.get(cid, set())
        wid = next(iter(whs)) if len(whs) == 1 else None
        add("cameras", rowid, cid, wid,
            evidence=f"linked only to {ctx.wh[wid]['code']} zones/classes (please confirm)" if wid else "",
            confirm=1 if wid else None)

    for table in ("violations_log", "outbound_orders"):
        for rowid, rid in conn.execute(f"SELECT rowid, id FROM {table}"):
            add(table, rowid, rid)

    for t in plan.values():
        for r in t:
            for k in [k for k, v in r.items() if v is None and k in ("is_demo", "legacy_test", "confirm")]:
                del r[k]
    return {"version": 1, "tables": plan, "warehouses": {str(k): v["code"] for k, v in ctx.wh.items()}}


def summarize(proposal: Dict[str, Any]) -> List[str]:
    wh = proposal["warehouses"]
    lines = []
    for table, rows in sorted(proposal["tables"].items()):
        if not rows:
            continue
        groups: Dict[str, int] = {}
        for r in rows:
            target = wh.get(str(r["warehouse_id"])) if r.get("warehouse_id") else (
                f"company {r['company_id']}" if r.get("company_id") else "UNASSIGNED")
            tag = target + ("".join(f" +{k}" for k in ("is_demo", "legacy_test", "confirm") if r.get(k)))
            groups[tag] = groups.get(tag, 0) + 1
        lines.append(f"{table}: " + ", ".join(f"{n} -> {g}" for g, n in sorted(groups.items())))
    return lines


def _sha(proposal) -> str:
    return hashlib.sha256(json.dumps(proposal, sort_keys=True).encode()).hexdigest()


def approve(conn: sqlite3.Connection, approved_by: str) -> Dict[str, Any]:
    proposal = propose(conn)
    conn.execute(APPROVAL_TABLE)
    conn.execute("INSERT INTO rbac_ownership_approval (proposal_json, proposal_sha256, approved_by) VALUES (?, ?, ?)",
                 (json.dumps(proposal, sort_keys=True), _sha(proposal), approved_by))
    return proposal


def approved_proposal(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    conn.execute(APPROVAL_TABLE)
    row = conn.execute("SELECT proposal_json FROM rbac_ownership_approval ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None


def apply(conn: sqlite3.Connection, proposal: Dict[str, Any]) -> Dict[str, int]:
    """Writes the approved assignments. Rows that appeared after approval get the same rules."""
    current = propose(conn)
    counts = {"assigned": 0, "unassigned": 0, "added_after_approval": 0}
    for table, cur_rows in current["tables"].items():
        approved = {r["rowid"]: r for r in proposal["tables"].get(table, [])}
        cols = _cols(conn, table)
        for row in cur_rows:
            r = approved.get(row["rowid"])
            if r is None or str(r.get("key")) != str(row.get("key")):
                r = row
                counts["added_after_approval"] += 1
            sets, params = [], []
            if r.get("company_id") is not None:
                sets.append("company_id = ?"); params.append(r["company_id"])
            if table in rbac_scope.WAREHOUSE_TABLES and r.get("warehouse_id") is not None:
                sets.append("warehouse_id = ?"); params.append(r["warehouse_id"])
            for flag in ("is_demo", "legacy_test"):
                if r.get(flag) and flag in cols:
                    sets.append(f"{flag} = 1")
            if sets:
                conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE rowid = ?", params + [row["rowid"]])
                counts["assigned"] += 1
            else:
                counts["unassigned"] += 1
    conn.execute("UPDATE rbac_ownership_approval SET applied_at = CURRENT_TIMESTAMP "
                 "WHERE id = (SELECT MAX(id) FROM rbac_ownership_approval)")
    return counts
