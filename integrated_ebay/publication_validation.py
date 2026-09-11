"""Local human-review checks, not a substitute for live eBay category metadata."""

import json
import math
import re
from urllib.parse import urlsplit


def publication_inputs(draft):
    context = json.loads(draft['generation_input_json'])
    product = context.get('product', {})
    source = context.get('selected_calculation', {})
    profile = json.loads(draft['shipping_profile_json'])
    result = {key: product.get(key) for key in (
        'sku', 'country_of_origin', 'hs_code', 'hts_code', 'weight_g', 'length_cm',
        'width_cm', 'height_cm', 'purchase_price', 'purchase_currency')}
    result['source_url'] = next((s.get('source_url', '') for s in context.get('sources', []) if s.get('is_primary')), '')
    for key, source_key in (('sku', 'sku'), ('country_of_origin', 'country_of_origin'), ('hts_code', 'hts_code'),
                            ('weight_g', 'package_weight_g'), ('length_cm', 'package_length_cm'),
                            ('width_cm', 'package_width_cm'), ('height_cm', 'package_height_cm'),
                            ('purchase_price', 'purchase_price_yen'), ('source_url', 'source_url')):
        if source.get(source_key) is not None:
            result[key] = source[source_key]
    for key, default in (('exchange_rate', None), ('usd_jpy_rate', None), ('ebay_fee_rate', 0),
                         ('promoted_listing_rate', 0), ('exchange_spread_rate', 0), ('fixed_fee_usd', 0),
                         ('buyer_shipping_usd', 0), ('domestic_shipping_yen', 0),
                         ('packaging_yen', 0), ('other_cost_yen', 0)):
        result[key] = source.get(key, default)
    result.update(shipping_carrier=source.get('expected_shipping_carrier', ''),
                  shipping_service=source.get('expected_shipping_service', ''),
                  shipping_yen=source.get('international_shipping_yen'),
                  required_specifics=[], specifics_reviewed=False)
    result.update(json.loads(draft.get('publication_input_json') or '{}'))
    result['shipping_breakdown_json'] = profile.get('shipping_breakdown_json')
    return result


def finite(value, *, positive=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float)) and
            math.isfinite(value) and (value > 0 if positive else value >= 0))


def validate_publication(connection, draft):
    p = publication_inputs(draft)
    errors = []
    for key, label in (('title', 'Title'), ('description', 'Description'),
                       ('category_id', 'Category ID'), ('condition_id', 'Condition ID')):
        if not str(draft.get(key) or '').strip():
            errors.append(label + 'が未入力です。')
    if not finite(draft['price'], positive=True):
        errors.append('販売価格は0より大きい金額が必要です。')
    if isinstance(draft['quantity'], bool) or not isinstance(draft['quantity'], int) or draft['quantity'] <= 0:
        errors.append('数量は1以上の整数が必要です。')
    for key, label in (('weight_g', '実重量'), ('length_cm', '長さ'), ('width_cm', '幅'), ('height_cm', '高さ'),
                       ('exchange_rate', '商品通貨/JPYレート')):
        if not finite(p.get(key), positive=True):
            errors.append(label + 'は0より大きい有限数が必要です。')
    for key in ('purchase_price', 'shipping_yen', 'buyer_shipping_usd', 'domestic_shipping_yen',
                'packaging_yen', 'other_cost_yen', 'ebay_fee_rate', 'promoted_listing_rate',
                'exchange_spread_rate', 'fixed_fee_usd'):
        if not finite(p.get(key)):
            errors.append(key + 'は0以上の有限数が必要です。')
    if p.get('purchase_currency') != 'JPY':
        errors.append('仕入価格は円換算額を入力し、仕入通貨をJPYにしてください（自動換算しません）。')
    if p.get('fixed_fee_usd') and not finite(p.get('usd_jpy_rate'), positive=True):
        errors.append('固定手数料換算用USD/JPYレートを入力してください。')
    if p.get('shipping_breakdown_json'):
        try:
            breakdown = json.loads(p['shipping_breakdown_json'])
            if not isinstance(breakdown, dict):
                raise ValueError()
            total = breakdown.get('total_shipping_yen')
            if total is not None and (not finite(total) or not finite(p['shipping_yen']) or abs(total - p['shipping_yen']) > 0.005):
                errors.append('送料内訳と予定送料合計が一致しません。保存済み送料見積を確認してください。')
        except (ValueError, TypeError):
            errors.append('送料スナップショットのJSONが不正です。')
    for key in ('ebay_fee_rate', 'promoted_listing_rate', 'exchange_spread_rate'):
        if finite(p.get(key)) and p[key] > 100:
            errors.append(key + 'は100%以下にしてください。')
    origin = str(p.get('country_of_origin') or '').strip().upper()
    if not re.fullmatch('[A-Z]{2}', origin):
        errors.append('原産国をISO2コードで入力してください。')
    for key, lengths in (('hs_code', (6, 8, 10)), ('hts_code', (10,))):
        value = str(p.get(key) or '').strip()
        if value and (not value.isascii() or not value.isdigit() or len(value) not in lengths):
            errors.append(key + 'の桁数・数字を確認してください。')
    for key in ('shipping_carrier', 'shipping_service'):
        if not str(p.get(key) or '').strip():
            errors.append('配送会社・配送サービスを入力してください。')
    if p.get('source_url'):
        try:
            url = urlsplit(p['source_url'])
            if url.scheme not in ('https', 'http') or not url.hostname or url.username:
                raise ValueError()
        except (ValueError, TypeError):
            errors.append('仕入元URLが不正です。')
    specifics = json.loads(draft['item_specifics_json'])
    required = p.get('required_specifics')
    if not isinstance(required, list) or not all(isinstance(k, str) and k.strip() for k in required):
        errors.append('必須Item Specificsは項目名のリストにしてください。')
        required = []
    if p.get('specifics_reviewed') is not True:
        errors.append('Categoryごとの必須Item Specificsを確認してください（eBay未照合）。')
    for key in required:
        value = specifics.get(key)
        if isinstance(value, dict):
            if value.get('needs_review'):
                errors.append(key + 'は要確認のままです。')
            value = value.get('value')
        if value is None or value == [] or not str(value).strip() or str(value).upper() == 'UNKNOWN':
            errors.append('必須Item Specifics不足: ' + key)
    sku = str(p.get('sku') or '').strip()
    if not sku or len(sku) > 50:
        errors.append('SKUを1〜50文字で入力してください。')
    if connection.execute('SELECT 1 FROM products WHERE trim(sku)=? COLLATE NOCASE AND product_id<>?',
                          (sku, draft['product_id'])).fetchone():
        errors.append('SKUが別の商品と重複しています。')
    if connection.execute("SELECT 1 FROM listing_publications WHERE status<>'CANCELLED' AND listing_draft_id<>? "
                          'AND (product_id=? OR sku=? COLLATE NOCASE)',
                          (draft['listing_draft_id'], draft['product_id'], sku)).fetchone():
        errors.append('同じ商品またはSKUに承認済み・公開中・公開済みの下書きがあります。')
    columns = {r[1] for r in connection.execute('PRAGMA table_info(listings)')}
    if 'product_url' in columns and 'product_id' in columns:
        clauses, params = ['product_id=?'], [draft['product_id']]
        if 'sku' in columns:
            clauses.append('trim(sku)=? COLLATE NOCASE')
            params.append(sku)
        for row in connection.execute('SELECT product_url FROM listings WHERE ' + ' OR '.join(clauses), params):
            try:
                parsed = urlsplit(str(row[0] or ''))
                if parsed.hostname and 'ebay.' in parsed.hostname and '/itm/' in parsed.path:
                    errors.append('既存出品にeBay商品URLがあります。重複出品を確認してください。')
            except ValueError:
                pass
    if errors:
        raise ValueError('\n'.join(dict.fromkeys(errors)))
    return p
