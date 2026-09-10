"""Draft persistence using the same SQLite/libSQL connection contract."""

import json


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class ListingDraftRepository:
    def __init__(self, connection):
        self.connection = connection

    def get(self, draft_id):
        row = self.connection.execute(
            "SELECT * FROM listing_drafts WHERE listing_draft_id = ?", (draft_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def list(self, product_id=None, status=None):
        clauses, params = [], []
        if product_id:
            clauses.append("d.product_id = ?")
            params.append(product_id)
        if status:
            clauses.append("d.status = ?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return [dict(row) for row in self.connection.execute(
            "SELECT d.*, p.product_name FROM listing_drafts d "
            "JOIN products p ON p.product_id = d.product_id" + where +
            " ORDER BY d.updated_at DESC, d.listing_draft_id", params
        ).fetchall()]

    def insert(self, values):
        self.connection.execute(
            "INSERT INTO listing_drafts (" + ",".join(values) + ") VALUES (" +
            ",".join("?" for _ in values) + ")", tuple(values.values())
        )

    def replace(self, values):
        # Column names originate only from a DB row, never from UI/AI input.
        fields = [key for key in values if key != "listing_draft_id"]
        self.connection.execute(
            "UPDATE listing_drafts SET " + ",".join(f"{key} = ?" for key in fields) +
            " WHERE listing_draft_id = ?",
            (*[values[key] for key in fields], values["listing_draft_id"]),
        )

    def record_revision(self, draft, action, actor_type, actor_id):
        self.connection.execute(
            "INSERT INTO listing_draft_revisions "
            "(listing_draft_id,revision,action,actor_type,actor_id,snapshot_json,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (draft["listing_draft_id"], draft["revision"], action, actor_type, actor_id,
             encode(draft), draft["updated_at"]),
        )

    def revisions(self, draft_id):
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM listing_draft_revisions WHERE listing_draft_id = ? ORDER BY revision DESC",
            (draft_id,),
        ).fetchall()]

    def saved_calculations(self, product_id):
        exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='listings'"
        ).fetchone()
        if not exists:
            return []
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(listings)")}
        if "product_id" not in columns:
            return []
        allowed = ("id", "product_id", "product_name", "platform", "currency_code",
                   "listing_price_usd", "listing_price", "shipping_breakdown_json")
        selected = [key for key in allowed if key in columns]
        return [dict(row) for row in self.connection.execute(
            "SELECT " + ",".join(selected) + " FROM listings WHERE product_id = ? ORDER BY id DESC",
            (product_id,),
        ).fetchall()]
