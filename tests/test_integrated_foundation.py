from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_database
from integrated_ebay.ids import generate_entity_id
from integrated_ebay.migrations import run_schema_migrations
from integrated_ebay.repositories import (
    AuditLogRepository,
    OutboxRepository,
    ProductRepository,
)
from integrated_ebay.services import ListingRegistrationService


class IntegratedFoundationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="integrated-ebay-foundation-"
        )
        self.database_path = Path(self.temporary_directory.name) / "foundation.sqlite3"
        self.environment = patch.dict(
            os.environ,
            {"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""},
            clear=False,
        )
        self.secrets = patch.object(app_database, "_secret_value", return_value="")
        self.environment.start()
        self.secrets.start()
        self._create_legacy_listing_table(self.connection_factory)

    def tearDown(self) -> None:
        self.secrets.stop()
        self.environment.stop()
        self.temporary_directory.cleanup()

    def connection_factory(self):
        return app_database.get_database_connection(self.database_path)

    @staticmethod
    def _create_legacy_listing_table(connection_factory) -> None:
        with connection_factory() as connection:
            connection.execute(
                """
                CREATE TABLE listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    sku TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    shipping_breakdown_json TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                INSERT INTO listings (
                    product_name, platform, sku, status,
                    shipping_breakdown_json, created_at, updated_at
                ) VALUES ('Legacy product', 'eBay', '', 'active', '{}', '', '')
                """
            )

    def test_migrations_are_idempotent_and_do_not_backfill_legacy_rows(self) -> None:
        first = run_schema_migrations(self.connection_factory)
        second = run_schema_migrations(self.connection_factory)

        self.assertEqual(
            ("0001_integrated_foundation", "0002_product_catalog_inventory", "0003_listing_drafts", "0004_listing_publications"),
            first,
        )
        self.assertEqual((), second)
        with self.connection_factory() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(listings)")
            }
            legacy_product_id = connection.execute(
                "SELECT product_id FROM listings WHERE product_name = 'Legacy product'"
            ).fetchone()[0]
            migration_count = connection.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0]

        self.assertTrue(
            {
                "schema_migrations",
                "products",
                "outbox_events",
                "audit_logs",
            }.issubset(tables)
        )
        self.assertIn("product_id", columns)
        self.assertIsNone(legacy_product_id)
        self.assertEqual(4, migration_count)

    def test_product_ids_are_unique_and_primary_key_is_enforced(self) -> None:
        run_schema_migrations(self.connection_factory)
        generated = {generate_entity_id("product") for _ in range(500)}
        self.assertEqual(500, len(generated))
        self.assertTrue(all(value.startswith("prd_") for value in generated))

        explicit_id = next(iter(generated))
        with self.connection_factory() as connection:
            repository = ProductRepository(connection)
            repository.create(
                product_id=explicit_id,
                product_name="First",
                platform="eBay",
            )
            with self.assertRaises(sqlite3.IntegrityError):
                repository.create(
                    product_id=explicit_id,
                    product_name="Duplicate",
                    platform="eBay",
                )

    def test_registration_links_product_and_preserves_shipping_snapshot(self) -> None:
        run_schema_migrations(self.connection_factory)
        breakdown = {
            "carrier": "SpeedPAK / CPaSS",
            "service": "SpeedPAK Economy",
            "total_yen": 3905,
            "rate_book_version": "test-rate-book",
        }
        result = ListingRegistrationService(self.connection_factory).register(
            product_name="New product",
            platform="eBay",
            sku="SKU-001",
            listing_data={
                "product_name": "New product",
                "platform": "eBay",
                "sku": "SKU-001",
                "status": "active",
                "shipping_breakdown_json": json.dumps(
                    breakdown,
                    ensure_ascii=False,
                ),
                "created_at": "2026-09-08 00:00:00",
                "updated_at": "2026-09-08 00:00:00",
            },
            audit_metadata={"source": "test"},
        )

        with self.connection_factory() as connection:
            listing = connection.execute(
                "SELECT * FROM listings WHERE id = ?",
                (result.listing_id,),
            ).fetchone()
            product = connection.execute(
                "SELECT * FROM products WHERE product_id = ?",
                (result.product_id,),
            ).fetchone()
            audit = connection.execute(
                "SELECT * FROM audit_logs WHERE entity_id = ?",
                (str(result.listing_id),),
            ).fetchone()

        self.assertEqual(result.product_id, listing["product_id"])
        self.assertEqual("New product", product["product_name"])
        self.assertEqual("SKU-001", product["sku"])
        self.assertEqual(breakdown, json.loads(listing["shipping_breakdown_json"]))
        self.assertEqual("listing.registered", audit["action"])
        self.assertEqual("human", audit["actor_type"])
        self.assertEqual(
            result.product_id,
            json.loads(audit["after_json"])["product_id"],
        )

    def test_registration_failure_rolls_back_product_and_audit(self) -> None:
        run_schema_migrations(self.connection_factory)
        service = ListingRegistrationService(self.connection_factory)

        with self.assertRaises(sqlite3.IntegrityError):
            service.register(
                product_name="Will roll back",
                platform="eBay",
                listing_data={
                    "platform": "eBay",
                    "status": "active",
                },
            )

        with self.connection_factory() as connection:
            self.assertEqual(
                0,
                connection.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0],
            )

    def test_outbox_idempotency_and_state_updates(self) -> None:
        run_schema_migrations(self.connection_factory)
        with self.connection_factory() as connection:
            repository = OutboxRepository(connection)
            first = repository.enqueue(
                event_type="ebay.listing.create",
                aggregate_type="product",
                aggregate_id="prd_example",
                payload={"title": "First payload"},
                idempotency_key="create-listing:prd_example:v1",
            )
            duplicate = repository.enqueue(
                event_type="ebay.listing.create",
                aggregate_type="product",
                aggregate_id="prd_example",
                payload={"title": "Duplicate payload"},
                idempotency_key="  create-listing:prd_example:v1  ",
            )
            repository.record_failure(first.event_id)
            repository.mark_processed(first.event_id)

        with self.connection_factory() as connection:
            rows = connection.execute("SELECT * FROM outbox_events").fetchall()

        self.assertTrue(first.created)
        self.assertFalse(duplicate.created)
        self.assertEqual(first.event_id, duplicate.event_id)
        self.assertEqual(1, len(rows))
        self.assertEqual("processed", rows[0]["status"])
        self.assertEqual(1, rows[0]["attempt_count"])
        self.assertIsNotNone(rows[0]["processed_at"])
        self.assertEqual("First payload", json.loads(rows[0]["payload_json"])["title"])

    def test_audit_log_keeps_actor_and_before_after_values(self) -> None:
        run_schema_migrations(self.connection_factory)
        with self.connection_factory() as connection:
            audit_id = AuditLogRepository(connection).append(
                entity_type="product",
                entity_id="prd_example",
                action="product.price_reviewed",
                actor_type="ai",
                actor_id="agent-pricing",
                before={"price_yen": 1000},
                after={"price_yen": 1200},
                metadata={"approved": False},
            )

        with self.connection_factory() as connection:
            row = connection.execute(
                "SELECT * FROM audit_logs WHERE audit_id = ?",
                (audit_id,),
            ).fetchone()

        self.assertEqual("ai", row["actor_type"])
        self.assertEqual(1000, json.loads(row["before_json"])["price_yen"])
        self.assertEqual(1200, json.loads(row["after_json"])["price_yen"])
        self.assertFalse(json.loads(row["metadata_json"])["approved"])

    def test_remote_compatible_connection_uses_the_same_foundation_api(self) -> None:
        remote_path = Path(self.temporary_directory.name) / "remote-compatible.sqlite3"

        def remote_factory():
            raw = sqlite3.connect(remote_path, timeout=30)
            return app_database.RemoteCompatibleConnection(raw)

        self._create_legacy_listing_table(remote_factory)
        run_schema_migrations(remote_factory)
        result = ListingRegistrationService(remote_factory).register(
            product_name="Remote-compatible product",
            platform="eBay",
            listing_data={
                "product_name": "Remote-compatible product",
                "platform": "eBay",
                "status": "active",
                "shipping_breakdown_json": "{}",
                "created_at": "2026-09-08 00:00:00",
                "updated_at": "2026-09-08 00:00:00",
            },
        )

        with remote_factory() as connection:
            listing = connection.execute(
                "SELECT product_id FROM listings WHERE id = ?",
                (result.listing_id,),
            ).fetchone()
            product = ProductRepository(connection).get(result.product_id)

        self.assertEqual(result.product_id, listing["product_id"])
        self.assertEqual("Remote-compatible product", product["product_name"])


if __name__ == "__main__":
    unittest.main()
