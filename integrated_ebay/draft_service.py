"""Product-linked drafts, atomic revisions and internal human approval only."""

import json
import math

from .ai_listing import AIListingGenerator
from .draft_repository import ListingDraftRepository, encode
from .ids import generate_entity_id
from .migrations import utc_now
from .repositories import AuditLogRepository, InventoryRepository, ProductRepository, ListingRepository
from .publication_repository import PublicationRepository
from .publication_validation import validate_publication
from .services import ProductCatalogService, available_quantity


DRAFT_STATUSES = ("DRAFT", "READY_FOR_REVIEW", "APPROVED", "REJECTED", "ARCHIVED")
DRAFT_CURRENCIES = ("USD", "CAD", "GBP", "AUD", "EUR", "JPY")
DRAFT_SITES = ("EBAY_US", "EBAY_CA", "EBAY_GB", "EBAY_AU", "EBAY_DE", "EBAY_FR", "EBAY_IT", "EBAY_ES")
EDIT_FIELDS = {"title", "description", "category_id", "category_name", "condition_id",
               "condition_name", "price", "currency", "quantity", "site",
               "item_specifics_json", "shipping_profile_json", "review_notes_json", "publication_input_json"}


class DraftConflict(ValueError):
    pass


class ListingDraftService:
    def __init__(self, connection_factory, generator=None):
        self.connection_factory = connection_factory
        self.generator = generator or AIListingGenerator()
        self.catalog = ProductCatalogService(connection_factory)

    @staticmethod
    def _actor(actor_id):
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("操作者名を入力してください。")
        return actor_id.strip()

    def get(self, draft_id):
        with self.connection_factory() as connection:
            result = ListingDraftRepository(connection).get(draft_id)
        if result is None:
            raise ValueError("下書きが見つかりません。")
        return result

    def list(self, product_id=None, status=None):
        with self.connection_factory() as connection:
            return ListingDraftRepository(connection).list(product_id, status)

    def revisions(self, draft_id):
        with self.connection_factory() as connection:
            return ListingDraftRepository(connection).revisions(draft_id)

    def saved_calculations(self, product_id):
        with self.connection_factory() as connection:
            return [row for row in ListingDraftRepository(connection).saved_calculations(product_id)
                    if str(row.get("platform", "eBay")).lower() == "ebay"]

    def context(self, product_id):
        product = self.catalog.get_product(product_id)
        if product is None:
            raise ValueError("商品が見つかりません。")
        scalar_keys = ("product_id", "product_name", "sku", "jan", "ean", "upc", "brand",
                       "model_number", "category", "notes", "country_of_origin", "hs_code",
                       "hts_code", "weight_g", "length_cm", "width_cm", "height_cm",
                       "purchase_price", "purchase_currency", "status", "updated_at")
        return {
            "product": {key: product.get(key) for key in scalar_keys},
            "inventory": product.get("inventory"),
            "available_quantity": product.get("available_quantity"),
            "sources": product.get("sources", []),
            "images": self.generator.image_adapter.prepare(product.get("images", [])),
            "ship_from": self.generator.policy.ship_from,
            "image_analysis": False,
            "source_urls_fetched": False,
        }

    @staticmethod
    def _check_product(connection, product_id):
        product = ProductRepository(connection).get(product_id)
        if not product:
            raise ValueError("商品が見つかりません。")
        if str(product["status"]).upper() == "ARCHIVED":
            raise ValueError("アーカイブ済みの商品は下書きを変更できません。")
        return product

    def _validate(self, draft):
        if draft["currency"] not in DRAFT_CURRENCIES or draft["site"] not in DRAFT_SITES:
            raise ValueError("通貨またはeBayサイトが不正です。")
        for key in ("title", "description", "category_id", "category_name", "condition_id", "condition_name"):
            if draft[key] is not None and not isinstance(draft[key], str):
                raise ValueError(f"{key}: 文字列を入力してください。")
        if len(draft["title"]) > self.generator.policy.title_limit:
            raise ValueError(f"Titleは{self.generator.policy.title_limit}文字以内にしてください。")
        price, quantity = draft["price"], draft["quantity"]
        if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0):
            raise ValueError("価格は0以上の有限数を入力してください。")
        if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0):
            raise ValueError("数量は0以上の整数を入力してください。")
        for key, expected in (("item_specifics_json", dict), ("shipping_profile_json", dict), ("review_notes_json", list), ("publication_input_json", dict)):
            value = json.loads(draft[key])
            if not isinstance(value, expected):
                raise ValueError(f"{key}: JSONの形式が不正です。")
            encode(value)

    def _record(self, connection, before, after, action, actor_type, actor_id):
        repo = ListingDraftRepository(connection)
        repo.record_revision(after, action, actor_type, actor_id)
        AuditLogRepository(connection).append(
            entity_type="listing_draft", entity_id=after["listing_draft_id"],
            action=action, actor_type=actor_type, actor_id=actor_id,
            before=before, after=after, timestamp=after["updated_at"],
            metadata={"product_id": after["product_id"], "revision": after["revision"]},
        )

    def create(self, product_id, *, actor_id, site="EBAY_US", currency="USD", price=None,
               calculation_id=None):
        actor_id = self._actor(actor_id)
        context = self.context(product_id)
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._check_product(connection, product_id)
            inventory = InventoryRepository(connection).get(product_id)
            quantity = available_quantity(inventory) if inventory else None
            profile = {}
            if calculation_id is not None:
                rows = ListingDraftRepository(connection).saved_calculations(product_id)
                selected = next((row for row in rows if row["id"] == calculation_id and
                                 str(row.get("platform", "eBay")).lower() == "ebay"), None)
                if selected is None:
                    raise ValueError("この商品に紐付いたeBay計算結果がありません。")
                price = selected.get("listing_price_usd")
                if price is None:
                    price = selected.get("listing_price")
                currency = selected.get("currency_code") or "USD"
                profile = {"source_listing_id": calculation_id,
                           "shipping_breakdown_json": selected.get("shipping_breakdown_json")}
                context["selected_calculation"] = ListingRepository(connection).get(calculation_id)
            now, draft_id = utc_now(), generate_entity_id("listing_draft")
            values = {
                "listing_draft_id": draft_id, "product_id": product_id, "marketplace": "eBay",
                "site": site, "currency": currency, "price": price, "quantity": quantity,
                "shipping_profile_json": encode(profile), "generation_input_json": encode(context),
                "created_by": actor_id, "created_at": now, "updated_at": now,
            }
            repo = ListingDraftRepository(connection)
            repo.insert(values)
            draft = repo.get(draft_id)
            self._validate(draft)
            self._record(connection, None, draft, "listing_draft.created", "human", actor_id)
        return draft_id

    def _mutate(self, draft_id, expected_revision, actor_id, action, actor_type, mutate):
        actor_id = self._actor(actor_id)
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            repo = ListingDraftRepository(connection)
            before = repo.get(draft_id)
            if not before:
                raise ValueError("下書きが見つかりません。")
            if before["revision"] != expected_revision:
                raise DraftConflict("別の操作で更新されています。最新の下書きを読み直してください。")
            if before["status"] == "ARCHIVED":
                raise ValueError("アーカイブ済みの下書きは変更できません。新しい下書きを作成してください。")
            publication = PublicationRepository(connection).guard_edit(draft_id)
            # Archiving remains available even when the parent product is archived.
            if action != "listing_draft.archived":
                self._check_product(connection, before["product_id"])
            after = dict(before)
            mutate(after, connection)
            if publication and after['status'] != 'APPROVED':
                PublicationRepository(connection).update(publication['publication_id'], status='CANCELLED', updated_at=utc_now())
                AuditLogRepository(connection).append(entity_type='publication', entity_id=publication['publication_id'],
                    action='publication.cancelled', actor_type='human', actor_id=actor_id,
                    before=publication, after={'status': 'CANCELLED'})
            after.update(revision=before["revision"] + 1, updated_at=utc_now(), last_actor_type=actor_type)
            self._validate(after)
            repo.replace(after)
            self._record(connection, before, after, action, actor_type, actor_id)
        return after

    def update(self, draft_id, values, *, expected_revision, actor_id):
        if set(values) - EDIT_FIELDS:
            raise ValueError("変更できない下書き項目が含まれています。")

        def edit(draft, connection):
            draft.update(values)
            draft.update(status="DRAFT", approved_at=None, approved_by=None)

        return self._mutate(draft_id, expected_revision, actor_id, "listing_draft.updated", "human", edit)

    def generate(self, draft_id, *, expected_revision, actor_id):
        actor_id = self._actor(actor_id)
        before = self.get(draft_id)
        with self.connection_factory() as connection:
            PublicationRepository(connection).guard_edit(draft_id)
        if before["revision"] != expected_revision or before["status"] == "ARCHIVED":
            raise DraftConflict("下書きの状態が変わっています。最新情報を読み直してください。")
        context = self.context(before["product_id"])
        context["draft_input"] = {key: before[key] for key in ("site", "currency", "price", "quantity", "shipping_profile_json")}
        context["requested_by"] = actor_id
        # Provider runs outside the write transaction; a concurrent edit wins over stale output.
        result = self.generator.generate(context)

        def apply(draft, connection):
            for key in ("title", "description", "category_name", "condition_name"):
                draft[key] = result[key]["value"]
            draft.update(category_id=None, condition_id=None,
                         item_specifics_json=encode(result["item_specifics"]),
                         review_notes_json=encode(result["notes"]),
                         generation_input_json=encode(context), generation_output_json=encode(result),
                         ai_model=self.generator.provider.model,
                         prompt_version=self.generator.policy.prompt_version,
                         status="READY_FOR_REVIEW", approved_at=None, approved_by=None)

        return self._mutate(draft_id, expected_revision, actor_id, "listing_draft.ai_generated", "ai", apply)

    def transition(self, draft_id, status, *, expected_revision, actor_id, reviewed=False):
        if status not in {"READY_FOR_REVIEW", "APPROVED", "REJECTED", "ARCHIVED"}:
            raise ValueError("不正な状態変更です。")
        action = {"READY_FOR_REVIEW": "updated", "APPROVED": "approved", "REJECTED": "rejected", "ARCHIVED": "archived"}[status]

        def change(draft, connection):
            allowed = {
                'DRAFT': {'READY_FOR_REVIEW', 'REJECTED', 'ARCHIVED'},
                'READY_FOR_REVIEW': {'APPROVED', 'REJECTED', 'ARCHIVED'},
                'APPROVED': {'REJECTED', 'ARCHIVED'},
                'REJECTED': {'READY_FOR_REVIEW', 'ARCHIVED'},
            }
            if status not in allowed.get(draft['status'], set()):
                raise ValueError('この状態からの遷移は許可されていません。編集・保存後にレビューしてください。')
            if status == "APPROVED":
                if draft["status"] != "READY_FOR_REVIEW" or not reviewed:
                    raise ValueError("レビュー待ちにして、内容確認にチェックを入れてください。")
                required = ("title", "description", "category_name", "condition_name")
                if any(not draft[key] or draft[key].strip().upper() == "UNKNOWN" for key in required):
                    raise ValueError("Title・Description・Category・Conditionを確認して保存してください。")
                if draft["price"] is None or draft["price"] <= 0 or draft["quantity"] is None or draft["quantity"] <= 0:
                    raise ValueError("販売価格と出品数量を確認して保存してください。")
                inventory = InventoryRepository(connection).get(draft["product_id"])
                if inventory is None:
                    raise ValueError("在庫情報がありません。商品マスターで確認してください。")
                available = available_quantity(inventory)
                if available is not None and draft["quantity"] > available:
                    raise ValueError("出品数量が現在の利用可能在庫を超えています。")
                inputs = validate_publication(connection, draft)
                draft.update(approved_at=utc_now(), approved_by=self._actor(actor_id))
                snapshot = dict(draft, status='APPROVED', revision=draft['revision'] + 1)
                publication_id = generate_entity_id('marketplace_listing')
                PublicationRepository(connection).insert({
                    'publication_id': publication_id, 'listing_draft_id': draft_id,
                    'product_id': draft['product_id'], 'approved_revision': snapshot['revision'],
                    'mode': 'MOCK', 'status': 'APPROVED', 'sku': str(inputs['sku']).strip(),
                    'marketplace': draft['site'], 'currency': draft['currency'], 'final_price': draft['price'],
                    'quantity': draft['quantity'], 'idempotency_key': f"publish:MOCK:{draft_id}:{snapshot['revision']}",
                    'approved_snapshot_json': encode(snapshot), 'approved_by': actor_id,
                    'created_at': draft['approved_at'], 'updated_at': draft['approved_at'],
                })
            else:
                draft.update(approved_at=None, approved_by=None)
            draft["status"] = status

        return self._mutate(draft_id, expected_revision, actor_id, "listing_draft." + action, "human", change)
