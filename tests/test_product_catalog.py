from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app_database import ClosingSQLiteConnection, RemoteCompatibleConnection
from integrated_ebay.migrations import run_schema_migrations
from integrated_ebay.services import (
    ListingRegistrationService,
    ProductCatalogService,
    available_quantity,
)


class ProductCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "catalog.sqlite3"

        def factory():
            connection = sqlite3.connect(
                self.path, factory=ClosingSQLiteConnection
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        self.factory = factory
        with self.factory() as connection:
            connection.execute(
                "CREATE TABLE listings ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, product_name TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO listings(product_name) VALUES (?)",
                [(f"Legacy {index}",) for index in range(94)],
            )
        run_schema_migrations(self.factory)
        self.service = ProductCatalogService(self.factory)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def product_values(self, **overrides):
        values = {
            "product_name": "Camera",
            "platform": "eBay",
            "sku": "CAM-001",
            "jan": "490000000001",
            "ean": "400000000001",
            "upc": "700000000001",
            "brand": "Example",
            "model_number": "EX-1",
            "category": "Camera",
            "notes": "Master note",
            "country_of_origin": "JP",
            "hs_code": "9006",
            "hts_code": "9006000000",
            "weight_g": 750,
            "length_cm": 20,
            "width_cm": 15,
            "height_cm": 10,
            "purchase_price": 12000,
            "purchase_currency": "JPY",
            "status": "ACTIVE",
        }
        values.update(overrides)
        return values

    def test_migration_is_additive_idempotent_and_preserves_94_legacy_rows(self) -> None:
        self.assertEqual(run_schema_migrations(self.factory), ())
        with self.factory() as connection:
            migrations = connection.execute(
                "SELECT migration_id FROM schema_migrations ORDER BY migration_id"
            ).fetchall()
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            count = connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            linked = connection.execute(
                "SELECT COUNT(*) FROM listings WHERE product_id IS NOT NULL"
            ).fetchone()[0]
        self.assertEqual(
            [row[0] for row in migrations],
            ["0001_integrated_foundation", "0002_product_catalog_inventory"],
        )
        self.assertTrue({"product_sources", "inventory", "product_images"} <= tables)
        self.assertEqual(count, 94)
        self.assertEqual(linked, 0)

    def test_product_create_update_archive_and_identifiers(self) -> None:
        product_id = self.service.create_product(self.product_values())
        self.assertTrue(product_id.startswith("prd_"))
        product = self.service.get_product(product_id)
        self.assertEqual(product["sku"], "CAM-001")
        self.assertEqual(product["jan"], "490000000001")
        self.assertEqual(product["ean"], "400000000001")
        self.assertEqual(product["upc"], "700000000001")
        self.assertEqual(product["weight_g"], 750)
        self.assertEqual(product["inventory"]["stock_mode"], "IN_STOCK")

        self.service.update_product(
            product_id, self.product_values(product_name="Updated", status="INACTIVE")
        )
        self.assertEqual(self.service.get_product(product_id)["product_name"], "Updated")
        self.service.archive_product(product_id)
        self.assertEqual(self.service.get_product(product_id)["status"], "ARCHIVED")

        with self.factory() as connection:
            actions = [
                row[0] for row in connection.execute(
                    "SELECT action FROM audit_logs WHERE entity_id = ? ORDER BY created_at, audit_id",
                    (product_id,),
                )
            ]
        self.assertEqual(
            actions, ["product.created", "product.updated", "product.archived"]
        )

    def test_duplicate_candidates_warn_without_merging(self) -> None:
        first = self.service.create_product(self.product_values())
        candidates = self.service.duplicate_candidates(
            self.product_values(product_name="Another")
        )
        self.assertEqual([item["product_id"] for item in candidates], [first])
        second = self.service.create_product(self.product_values(product_name="Another"))
        self.assertNotEqual(first, second)

    def test_multiple_sources_keep_one_primary_and_are_editable(self) -> None:
        product_id = self.service.create_product(self.product_values())
        amazon = self.service.add_source(product_id, {
            "source_type": "AMAZON", "source_name": "Amazon",
            "source_url": "https://example.com/a", "source_item_id": "A1",
            "price": 100, "currency": "USD", "stock_status": "IN_STOCK",
            "is_primary": True,
        })
        rakuten = self.service.add_source(product_id, {
            "source_type": "RAKUTEN", "source_name": "Rakuten",
            "source_url": "https://example.com/r", "price": 15000,
            "currency": "JPY", "stock_status": "LIMITED", "is_primary": True,
        })
        sources = self.service.get_product(product_id)["sources"]
        self.assertEqual(len(sources), 2)
        self.assertEqual([row["source_id"] for row in sources if row["is_primary"]], [rakuten])
        self.service.update_source(product_id, amazon, {
            "source_type": "AMAZON", "source_name": "Amazon JP",
            "source_url": "https://example.com/a2", "source_item_id": "A2",
            "price": 110, "currency": "CAD", "stock_status": "UNKNOWN",
            "is_primary": True,
        })
        sources = self.service.get_product(product_id)["sources"]
        self.assertEqual([row["source_id"] for row in sources if row["is_primary"]], [amazon])
        self.assertEqual(next(row for row in sources if row["source_id"] == amazon)["currency"], "CAD")

    def test_inventory_modes_and_available_quantity(self) -> None:
        product_id = self.service.create_product(self.product_values())
        self.service.update_inventory(product_id, {
            "stock_mode": "IN_STOCK", "on_hand_quantity": 10,
            "reserved_quantity": 3, "reorder_point": 2, "storage_location": "A-1",
        })
        product = self.service.get_product(product_id)
        self.assertEqual(product["available_quantity"], 7)
        self.assertNotIn("available_quantity", product["inventory"])
        self.service.update_inventory(product_id, {
            "stock_mode": "DROPSHIP", "on_hand_quantity": 0,
            "reserved_quantity": 0, "reorder_point": 0, "storage_location": "",
        })
        self.assertIsNone(self.service.get_product(product_id)["available_quantity"])
        self.assertIsNone(available_quantity({"stock_mode": "DROPSHIP"}))

    def test_image_metadata_uses_reference_not_blob_and_one_primary(self) -> None:
        product_id = self.service.create_product(self.product_values())
        first = self.service.add_image(product_id, {
            "storage_provider": "development", "storage_key": "products/a.jpg",
            "file_name": "a.jpg", "sort_order": 1, "is_primary": True,
        })
        second = self.service.add_image(product_id, {
            "storage_provider": "external", "url": "https://example.com/b.jpg",
            "file_name": "b.jpg", "sort_order": 2, "is_primary": True,
        })
        images = self.service.get_product(product_id)["images"]
        self.assertEqual({row["image_id"] for row in images}, {first, second})
        self.assertEqual([row["image_id"] for row in images if row["is_primary"]], [second])
        with self.factory() as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(product_images)")}
        self.assertNotIn("blob", columns)
        self.assertNotIn("image_data", columns)

    def test_existing_product_can_receive_listing_without_duplicate_product(self) -> None:
        product_id = self.service.create_product(self.product_values())
        result = ListingRegistrationService(self.factory).register(
            listing_data={"product_name": "Camera listing"},
            product_name="Camera", platform="eBay", sku="CAM-001",
            product_id=product_id,
        )
        self.assertEqual(result.product_id, product_id)
        product = self.service.get_product(product_id)
        self.assertEqual(len(product["listings"]), 1)
        with self.factory() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0], 95)

    def test_foreign_keys_and_currency_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.service.create_product(self.product_values(purchase_currency="EUR"))
        with self.assertRaises(ValueError):
            self.service.add_source("prd_missing", {
                "source_type": "AMAZON", "currency": "JPY"
            })

    def test_remote_compatible_connection_path(self) -> None:
        remote_path = Path(self.temporary.name) / "remote.sqlite3"

        def remote_factory():
            raw = sqlite3.connect(remote_path)
            return RemoteCompatibleConnection(raw)

        run_schema_migrations(remote_factory)
        remote_service = ProductCatalogService(remote_factory)
        product_id = remote_service.create_product(
            self.product_values(product_name="Remote product", sku="REMOTE")
        )
        self.assertEqual(remote_service.get_product(product_id)["sku"], "REMOTE")

    def test_audit_payloads_are_valid_json(self) -> None:
        product_id = self.service.create_product(self.product_values())
        self.service.update_inventory(product_id, {
            "stock_mode": "IN_STOCK", "on_hand_quantity": 2,
            "reserved_quantity": 1, "reorder_point": 1, "storage_location": "B",
        })
        with self.factory() as connection:
            rows = connection.execute(
                "SELECT after_json FROM audit_logs WHERE after_json IS NOT NULL"
            ).fetchall()
        self.assertTrue(rows)
        for row in rows:
            self.assertIsInstance(json.loads(row[0]), dict)


if __name__ == "__main__":
    unittest.main()
