"""
Inventory section API (menu: Inventory; also feeds Master Data Hub > Inventory Master).

  GET  /api/stock/overview         stock lines, per-product and per-bin totals, alerts   inventory.view
  GET  /api/stock/movements        stock history (filter by line / product / bin)        inventory.view
  POST /api/stock/adjust           set a line's quantity, with a reason                  inventory.adjust
  POST /api/stock/transfer         move a quantity to another bin in the same location   inventory.transfer
  PUT  /api/stock/min-level        minimum level of a product in this location           inventory.levels.manage
  GET  /api/stock/export.csv       current stock as CSV                                  inventory.export

Reads follow the location picked in the top bar (one location, or all locations read-only).
Changes are checked here in every RBAC mode (like Users & Access): they change stock
figures people rely on. Every change lands in the stock history (stock_ledger.py).
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, List

from flask import Blueprint, Response, g, jsonify, request

import db
import rbac_scope
import rbac_service
import stock_ledger

logger = logging.getLogger(__name__)

bp = Blueprint("stock", __name__)

ADJUST_REASONS = {
    "damaged": "Damaged / broken",
    "count_mismatch": "Physical count mismatch",
    "found": "Found stock",
    "expired": "Expired / scrapped",
    "other": "Other",
}
EXPIRY_WARN_DAYS = 30
BIN_FULL_PCT = 90


class StockError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@bp.errorhandler(StockError)
def _stock_error(e: StockError):
    return jsonify({"success": False, "error": e.message, "message": e.message, "error_code": e.code}), e.status


def _actor() -> str:
    return str((g.get("current_user") or {}).get("username") or "unknown")


def _need(key: str) -> None:
    if not g.get("current_user"):
        raise StockError(401, "login_required", "Please sign in.")
    if key not in rbac_service.effective_permissions():
        raise StockError(403, "permission_denied", "You don't have permission for this.")


def _write_scope():
    """The location a change is made in. The all-locations view is read-only."""
    scope = rbac_service.current_scope()
    if scope is not None and scope.read_only:
        raise StockError(403, "read_only_scope",
                         "All locations is a read-only view. Pick one location in the top bar to make changes.")
    return scope


def _int(value, field: str, minimum: int = 0) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise StockError(400, "invalid", f"{field} must be a whole number.")
    if n < minimum:
        raise StockError(400, "invalid", f"{field} can't be less than {minimum}.")
    if n > 10_000_000:
        raise StockError(400, "invalid", f"{field} is too large.")
    return n


def _load_line(conn, inventory_id: int):
    cond, params = rbac_scope.home_filter("inventory")
    row = conn.execute(f"SELECT * FROM inventory WHERE id = ?{cond}", (inventory_id,) + params).fetchone()
    if not row:
        raise StockError(404, "not_found", "That stock line was not found in this location.")
    scope = rbac_service.current_scope()
    if (scope is not None and scope.kind == "platform_full" and scope.warehouse_id is not None
            and row["warehouse_id"] is not None and row["warehouse_id"] != scope.warehouse_id):
        raise StockError(409, "other_location",
                         "This stock belongs to another location. Switch to that location in the top bar first.")
    return row


def recalc_bin(conn, bin_id: str) -> None:
    """Bin fill (volume / weight) from the stock now in it."""
    if not bin_id:
        return
    vol, wt = conn.execute("""
        SELECT COALESCE(SUM(i.quantity * COALESCE(s.unit_volume, 0)), 0),
               COALESCE(SUM(i.quantity * COALESCE(s.unit_weight, 0)), 0)
          FROM inventory i LEFT JOIN skus s ON s.sku_id = i.sku_id
         WHERE i.bin_id = ?""", (bin_id,)).fetchone()
    conn.execute("UPDATE bins SET current_volume = ?, current_weight = ?, last_updated = CURRENT_TIMESTAMP "
                 "WHERE bin_id = ?", (round(vol, 3), round(wt, 3), bin_id))


def _fill_pct(b: Dict[str, Any]) -> int:
    pcts = []
    for cur, mx in (("current_volume", "max_volume"), ("current_weight", "max_weight")):
        if (b.get(mx) or 0) > 0:
            pcts.append(100.0 * (b.get(cur) or 0) / b[mx])
    return int(round(max(pcts))) if pcts else 0


# ----------------------------------------------------------------------------- reads
@bp.route("/api/stock/overview", methods=["GET"])
def api_overview():
    conn = db.get_db()
    try:
        icond, iparams = rbac_scope.home_filter("inventory", "i")
        lines = [dict(r) for r in conn.execute(f"""
            SELECT i.id, i.bin_id, i.sku_id, i.quantity, i.batch_number, i.expiry_date, i.vendor,
                   i.received_date, COALESCE(i.is_demo, 0) AS is_demo, i.warehouse_id,
                   s.name AS sku_name, s.category, COALESCE(s.uom, 'EA') AS uom,
                   b.zone, w.name AS warehouse_name, w.code AS warehouse_code,
                   CASE WHEN i.expiry_date IS NOT NULL AND TRIM(i.expiry_date) != ''
                        THEN CAST(julianday(date(i.expiry_date)) - julianday(date('now')) AS INTEGER) END AS days_to_expiry
              FROM inventory i
              LEFT JOIN skus s ON s.sku_id = i.sku_id
              LEFT JOIN bins b ON b.bin_id = i.bin_id
              LEFT JOIN warehouses w ON w.id = i.warehouse_id
             WHERE 1 = 1{icond}
             ORDER BY s.name COLLATE NOCASE, i.bin_id, i.id""", iparams)]

        bcond, bparams = rbac_scope.home_filter("bins", "b")
        bins = []
        for r in conn.execute(f"""
                SELECT b.bin_id, b.zone, b.status, b.max_volume, b.current_volume, b.max_weight, b.current_weight,
                       b.warehouse_id, w.name AS warehouse_name
                  FROM bins b LEFT JOIN warehouses w ON w.id = b.warehouse_id
                 WHERE 1 = 1{bcond} ORDER BY b.zone, b.bin_id""", bparams):
            b = dict(r)
            b["fill_pct"] = _fill_pct(b)
            in_bin = [x for x in lines if x["bin_id"] == b["bin_id"]]
            b["lines"] = len(in_bin)
            b["quantity"] = sum(x["quantity"] or 0 for x in in_bin)
            b["products"] = len({x["sku_id"] for x in in_bin if (x["quantity"] or 0) > 0})
            bins.append(b)

        mcond, mparams = rbac_scope.home_filter("stock_min_levels", "m")
        mins = {r["sku_id"]: r["min_qty"] for r in conn.execute(
            f"SELECT m.sku_id, SUM(m.min_qty) AS min_qty FROM stock_min_levels m WHERE 1 = 1{mcond} GROUP BY m.sku_id",
            mparams)}

        products: Dict[str, Dict[str, Any]] = {}
        for x in lines:
            p = products.setdefault(x["sku_id"], {
                "sku_id": x["sku_id"], "sku_name": x["sku_name"] or x["sku_id"], "category": x["category"],
                "uom": x["uom"], "quantity": 0, "bins": set(), "lines": 0})
            p["quantity"] += x["quantity"] or 0
            p["lines"] += 1
            if (x["quantity"] or 0) > 0:
                p["bins"].add(x["bin_id"])
        # products with a minimum level but no stock here are "low" too
        missing = [s for s in mins if s not in products]
        if missing:
            scond, sparams = rbac_scope.home_filter("skus")
            marks = ",".join("?" * len(missing))
            for r in conn.execute(f"SELECT sku_id, name, category, COALESCE(uom, 'EA') AS uom FROM skus "
                                  f"WHERE sku_id IN ({marks}){scond}", tuple(missing) + sparams):
                products[r["sku_id"]] = {"sku_id": r["sku_id"], "sku_name": r["name"], "category": r["category"],
                                         "uom": r["uom"], "quantity": 0, "bins": set(), "lines": 0}
        for p in products.values():
            p["bins"] = sorted(b for b in p["bins"] if b)
            p["min_qty"] = mins.get(p["sku_id"])
            p["low"] = p["min_qty"] is not None and p["quantity"] < p["min_qty"]
        product_list = sorted(products.values(), key=lambda p: (str(p["sku_name"] or "").lower(), p["sku_id"]))

        low = [p for p in product_list if p["low"]]
        expiring = [x for x in lines if x["days_to_expiry"] is not None and x["days_to_expiry"] <= EXPIRY_WARN_DAYS
                    and (x["quantity"] or 0) > 0]
        full = [b for b in bins if b["fill_pct"] >= BIN_FULL_PCT]

        scope = rbac_service.current_scope()
        return jsonify({
            "success": True,
            "summary": {
                "total_qty": sum(x["quantity"] or 0 for x in lines),
                "products": sum(1 for p in product_list if p["quantity"] > 0),
                "bins_used": len({x["bin_id"] for x in lines if (x["quantity"] or 0) > 0}),
                "bins_total": len(bins),
                "alerts": len(low) + len(expiring) + len(full),
            },
            "lines": lines, "products": product_list, "bins": bins,
            "alerts": {"low": low, "expiring": expiring, "bins_full": full},
            "reasons": ADJUST_REASONS,
            "read_only": bool(scope is not None and scope.read_only),
            "all_locations": bool(scope is not None and scope.kind in ("company_all", "platform_all")),
            "thresholds": {"expiry_days": EXPIRY_WARN_DAYS, "bin_full_pct": BIN_FULL_PCT},
        })
    finally:
        conn.close()


@bp.route("/api/stock/movements", methods=["GET"])
def api_movements():
    try:
        limit = min(max(int(request.args.get("limit", 200) or 200), 1), 1000)
    except ValueError:
        limit = 200
    cond, params = rbac_scope.home_filter("stock_movements", "m")
    where, args = [], []
    for field, col in (("inventory_id", "m.inventory_id"), ("sku_id", "m.sku_id"), ("bin_id", "m.bin_id"),
                       ("type", "m.movement_type")):
        v = (request.args.get(field) or "").strip()
        if v:
            where.append(f" AND {col} = ?")
            args.append(v)
    q = (request.args.get("q") or "").strip()
    if q:
        where.append(" AND (m.sku_id LIKE ? OR m.bin_id LIKE ? OR m.actor LIKE ? OR m.reason LIKE ? OR s.name LIKE ?)")
        args += [f"%{q}%"] * 5
    conn = db.get_db()
    try:
        rows = [dict(r) for r in conn.execute(f"""
            SELECT m.id, m.ts, m.inventory_id, m.sku_id, m.bin_id, m.batch_number, m.qty_before, m.qty_after,
                   m.delta, m.movement_type, m.actor, m.source, m.reason, m.ref, s.name AS sku_name,
                   w.name AS warehouse_name
              FROM stock_movements m
              LEFT JOIN skus s ON s.sku_id = m.sku_id
              LEFT JOIN warehouses w ON w.id = m.warehouse_id
             WHERE 1 = 1{cond}{''.join(where)}
             ORDER BY m.id DESC LIMIT ?""", params + tuple(args) + (limit,))]
    finally:
        conn.close()
    for r in rows:
        r["type_label"] = stock_ledger.TYPE_LABELS.get(r["movement_type"], r["movement_type"])
        r["by"] = r["actor"] or "System"
    return jsonify({"success": True, "movements": rows})


@bp.route("/api/stock/export.csv", methods=["GET"])
def api_export():
    _need("inventory.export")
    conn = db.get_db()
    try:
        cond, params = rbac_scope.home_filter("inventory", "i")
        rows = conn.execute(f"""
            SELECT w.name AS location, i.sku_id, s.name AS product, s.category, i.bin_id, b.zone, i.batch_number,
                   i.quantity, COALESCE(s.uom, 'EA') AS uom, i.expiry_date, i.vendor, i.received_date
              FROM inventory i
              LEFT JOIN skus s ON s.sku_id = i.sku_id
              LEFT JOIN bins b ON b.bin_id = i.bin_id
              LEFT JOIN warehouses w ON w.id = i.warehouse_id
             WHERE 1 = 1{cond} ORDER BY s.name COLLATE NOCASE, i.bin_id""", params).fetchall()
    finally:
        conn.close()
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(["Location", "SKU", "Product", "Category", "Bin", "Zone", "Batch", "Quantity", "Unit",
                  "Expiry", "Vendor", "Received"])
    for r in rows:
        # neutralise spreadsheet formulas in text cells
        out.writerow([("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in tuple(r)])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=warlog_stock.csv"})


# ----------------------------------------------------------------------------- changes
@bp.route("/api/stock/adjust", methods=["POST"])
def api_adjust():
    _need("inventory.adjust")
    _write_scope()
    body = request.get_json(silent=True) or {}
    inv_id = _int(body.get("inventory_id"), "Stock line", 1)
    new_qty = _int(body.get("quantity"), "New quantity", 0)
    # `reason` is the full text (the screen sends "<chosen reason>: <note>"); the global
    # reason check (inventory.adjust is an exceptional action) reads the same field.
    code = str(body.get("reason_code") or "").strip()
    reason = str(body.get("reason") or "").strip()[:300]
    if code and code not in ADJUST_REASONS:
        raise StockError(400, "invalid", "Unknown reason.")
    if not reason or (code == "other" and reason == ADJUST_REASONS["other"]):
        raise StockError(400, "reason_required", "Please give a reason for the adjustment.")
    conn = db.get_db()
    try:
        with conn:
            line = _load_line(conn, inv_id)
            if (line["quantity"] or 0) == new_qty:
                raise StockError(400, "no_change", "The quantity is already that number.")
            mark = stock_ledger.mark(conn) or 0
            cur = conn.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_qty, inv_id))
            if not cur.rowcount:
                raise StockError(404, "not_found", "That stock line was not found in this location.")
            recalc_bin(conn, line["bin_id"])
            stock_ledger.stamp(conn, mark, _actor(), "Inventory screen", "adjust", reason, only_unowned=False)
    finally:
        conn.close()
    return jsonify({"success": True, "message": f"Stock updated: {line['quantity']} → {new_qty}.",
                    "inventory_id": inv_id, "quantity": new_qty})


@bp.route("/api/stock/transfer", methods=["POST"])
def api_transfer():
    _need("inventory.transfer")
    _write_scope()
    body = request.get_json(silent=True) or {}
    inv_id = _int(body.get("inventory_id"), "Stock line", 1)
    qty = _int(body.get("quantity"), "Quantity to move", 1)
    to_bin = str(body.get("to_bin") or "").strip()
    note = str(body.get("reason") or "").strip()[:300] or None
    if not to_bin:
        raise StockError(400, "invalid", "Please choose the bin to move the stock to.")
    conn = db.get_db()
    try:
        with conn:
            src = _load_line(conn, inv_id)
            have = src["quantity"] or 0
            if to_bin == src["bin_id"]:
                raise StockError(400, "invalid", "The stock is already in that bin.")
            if qty > have:
                raise StockError(400, "insufficient", f"Only {have} available in {src['bin_id']}.")
            bcond, bparams = rbac_scope.home_filter("bins")
            target = conn.execute(f"SELECT bin_id, warehouse_id, status FROM bins WHERE bin_id = ?{bcond}",
                                  (to_bin,) + bparams).fetchone()
            if not target or (src["warehouse_id"] is not None and target["warehouse_id"] != src["warehouse_id"]):
                raise StockError(404, "not_found", "That bin was not found in this location.")
            mark = stock_ledger.mark(conn) or 0
            dest = conn.execute("""SELECT id FROM inventory WHERE bin_id = ? AND sku_id = ?
                                    AND batch_number IS ? AND warehouse_id IS ? ORDER BY id LIMIT 1""",
                                (to_bin, src["sku_id"], src["batch_number"], src["warehouse_id"])).fetchone()
            if dest:
                conn.execute("UPDATE inventory SET quantity = quantity + ? WHERE id = ?", (qty, dest["id"]))
                dest_id = dest["id"]
            else:
                cur = conn.execute("""INSERT INTO inventory (bin_id, sku_id, quantity, batch_number, expiry_date, vendor,
                                          received_date, is_demo, company_id, warehouse_id)
                                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                   (to_bin, src["sku_id"], qty, src["batch_number"], src["expiry_date"], src["vendor"],
                                    src["received_date"], src["is_demo"] or 0, src["company_id"], src["warehouse_id"]))
                dest_id = cur.lastrowid
            conn.execute("UPDATE inventory SET quantity = quantity - ? WHERE id = ?", (qty, inv_id))
            if qty == have:
                conn.execute("DELETE FROM inventory WHERE id = ? AND COALESCE(quantity, 0) = 0", (inv_id,))
            recalc_bin(conn, src["bin_id"])
            recalc_bin(conn, to_bin)
            ref = f"TRF-{mark + 1}"
            conn.execute("""UPDATE stock_movements SET actor = ?, source = 'Inventory screen', reason = ?, ref = ?,
                                   movement_type = CASE WHEN inventory_id = ? THEN 'transfer_out' ELSE 'transfer_in' END
                             WHERE id > ?""", (_actor(), note, ref, inv_id, mark))
    finally:
        conn.close()
    return jsonify({"success": True, "message": f"Moved {qty} from {src['bin_id']} to {to_bin}.",
                    "from_inventory_id": inv_id, "to_inventory_id": dest_id, "ref": ref})


@bp.route("/api/stock/min-level", methods=["PUT"])
def api_min_level():
    _need("inventory.levels.manage")
    scope = _write_scope()
    body = request.get_json(silent=True) or {}
    sku_id = str(body.get("sku_id") or "").strip()
    raw = body.get("min_qty")
    if not sku_id:
        raise StockError(400, "invalid", "Choose a product.")
    conn = db.get_db()
    try:
        scond, sparams = rbac_scope.home_filter("skus")
        if not conn.execute(f"SELECT 1 FROM skus WHERE sku_id = ?{scond}", (sku_id,) + sparams).fetchone():
            raise StockError(404, "not_found", "That product was not found.")
        wid = scope.warehouse_id if scope is not None else None
        if wid is None:
            raise StockError(400, "pick_location", "Pick a location in the top bar first.")
        with conn:
            if raw in (None, "") or str(raw).strip() == "":
                conn.execute("DELETE FROM stock_min_levels WHERE sku_id = ? AND warehouse_id = ?", (sku_id, wid))
                return jsonify({"success": True, "message": "Minimum level removed.", "min_qty": None})
            qty = _int(raw, "Minimum level", 0)
            conn.execute("""INSERT INTO stock_min_levels (sku_id, min_qty, updated_by, warehouse_id, company_id)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(warehouse_id, sku_id) DO UPDATE SET min_qty = excluded.min_qty,
                                updated_by = excluded.updated_by, updated_at = CURRENT_TIMESTAMP""",
                         (sku_id, qty, _actor(), wid, scope.company_id))
    finally:
        conn.close()
    return jsonify({"success": True, "message": f"Minimum level set to {qty}.", "min_qty": qty})
