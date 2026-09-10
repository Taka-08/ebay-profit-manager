"""Offline-safe generation boundary. No network, credentials or marketplace calls."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Protocol


@dataclass(frozen=True)
class DraftGenerationPolicy:
    title_limit: int = 80
    prompt_version: str = "ebay_listing_v1"
    ship_from: str = "Japan"
    blocked_title_words: tuple[str, ...] = ("rare", "authentic")


def evidence(value, source="product_master", *, review=False):
    if value is None or value == "":
        return {"value": None, "confidence": "unknown", "source": "none", "needs_review": True}
    return {"value": value, "confidence": "high", "source": source, "needs_review": review}


class ImageInputAdapter(Protocol):
    def prepare(self, images: list[dict]) -> list[dict]: ...


class MetadataImageAdapter:
    def prepare(self, images):
        keys = ("image_id", "storage_provider", "storage_key", "url", "file_name", "is_primary", "sort_order")
        return [{key: image.get(key) for key in keys} for image in images]


class AIProvider(Protocol):
    model: str

    def generate(self, context: dict, prompt: str, policy: DraftGenerationPolicy) -> dict | str: ...


def english_text(value):
    text = " ".join(str(value or "").split())
    return text if text and text.isascii() and not any(c in text for c in "<>") else None


def make_title(parts, policy):
    words, seen = [], set()
    for part in parts:
        for word in (english_text(part) or "").split():
            normalized = word.casefold().strip(".,!?:;()")
            if normalized in seen or normalized in policy.blocked_title_words:
                continue
            if len(" ".join([*words, word])) <= policy.title_limit:
                words.append(word)
                seen.add(normalized)
    return " ".join(words) or "Item"


class LocalDeterministicProvider:
    """Honest fallback, not an LLM: formats explicit English facts only."""

    model = "local-deterministic-v1"

    def generate(self, context, prompt, policy):
        product = context["product"]
        name = english_text(product.get("product_name"))
        title = make_title([product.get("brand"), name, product.get("model_number")], policy)
        specifics = {
            "Brand": evidence(product.get("brand")),
            "Model": evidence(product.get("model_number")),
            "MPN": evidence(None),
            "Type": evidence(None),
            "Country/Region of Manufacture": evidence(product.get("country_of_origin")),
            "Material": evidence(None), "Product size": evidence(None),
            "Included items": evidence(None), "Compatibility": evidence(None),
        }
        for key in ("jan", "ean", "upc"):
            specifics[key.upper()] = evidence(product.get(key))
        known = [f"{key}: {english_text(item['value'])}" for key, item in specifics.items()
                 if english_text(item["value"])]
        description = (
            f"Overview\n{name or 'Item name: UNKNOWN - English translation required.'}\n\n"
            "Condition\nUNKNOWN - inspect wear, operation, damage and missing parts.\n\n"
            "Specifications\n" + ("\n".join(known) or "UNKNOWN - details require confirmation.") +
            "\n\nIncluded items\nUNKNOWN - confirm included accessories.\n\n"
            f"Shipping origin\n{policy.ship_from}\n\n"
            "Notes\nDraft only. Verify all details before publishing."
        )
        return {
            "title": evidence(title, "local_template", review=True),
            "description": evidence(description, "local_template", review=True),
            "category_name": evidence(product.get("category"), "local_candidate", review=True),
            "condition_name": evidence(None),
            "condition_candidates": ["New", "Used"],
            "item_specifics": specifics,
            "notes": ["ローカル生成です。翻訳・画像解析・eBayカテゴリ照合は行っていません。",
                      "状態・素材・付属品・互換性、出品数量と販売価格を確認してください。",
                      "仕入先URLと画像は参照情報のみです。内容は取得していません。"],
        }


class GenerationError(ValueError):
    pass


class AIListingGenerator:
    def __init__(self, provider=None, policy=None, image_adapter=None):
        self.provider = provider or LocalDeterministicProvider()
        self.policy = policy or DraftGenerationPolicy()
        self.image_adapter = image_adapter or MetadataImageAdapter()

    def generate(self, context):
        try:
            if not re.fullmatch(r"[a-z0-9_]+", self.policy.prompt_version):
                raise ValueError("Invalid prompt version")
            prompt = (Path(__file__).parent / "prompts" / (self.policy.prompt_version + ".txt")).read_text(encoding="utf-8")
            result = self.provider.generate(context, prompt, self.policy)
            if isinstance(result, str):
                result = json.loads(result)
            # Round-trip rejects non-JSON and NaN before any transaction begins.
            result = json.loads(json.dumps(result, allow_nan=False))
            required = {"title", "description", "category_name", "condition_name", "item_specifics", "notes"}
            if not isinstance(result, dict) or not required <= result.keys():
                raise ValueError("Incomplete output")
            if set(result) - required - {"condition_candidates"}:
                raise ValueError("Unexpected generated fields")
            if not isinstance(result["item_specifics"], dict) or not isinstance(result["notes"], list):
                raise ValueError("Invalid output structure")
            for field in [*(result[key] for key in ("title", "description", "category_name", "condition_name")),
                          *result["item_specifics"].values()]:
                if not isinstance(field, dict) or set(field) != {"value", "confidence", "source", "needs_review"}:
                    raise ValueError("Missing evidence")
                if field["value"] is not None and not isinstance(field["value"], str):
                    raise ValueError("Invalid value")
                if field["confidence"] not in {"high", "medium", "low", "unknown"} or not isinstance(field["needs_review"], bool) or not isinstance(field["source"], str):
                    raise ValueError("Invalid evidence")
                if not field["value"] and (not field["needs_review"] or field["confidence"] != "unknown"):
                    raise ValueError("Unknown field presented as fact")
            title, description = result["title"]["value"], result["description"]["value"]
            if not title or len(title) > self.policy.title_limit or not description:
                raise ValueError("Invalid text")
            if any(word in {w.casefold().strip('.,!?:;()') for w in title.split()} for word in self.policy.blocked_title_words):
                raise ValueError("Unsupported title claim")
            if not all(isinstance(note, str) for note in result["notes"]):
                raise ValueError("Invalid notes")
            return result
        except Exception as exc:
            # Never leak a provider exception which may contain credentials/payloads.
            raise GenerationError("下書き生成に失敗しました。既存内容は保持されています。再試行してください。") from exc
