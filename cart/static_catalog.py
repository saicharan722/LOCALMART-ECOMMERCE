import hashlib
import json
import logging
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path


logger = logging.getLogger(__name__)


class StaticCatalogError(RuntimeError):
    pass


def _price(value):
    try:
        price = Decimal(str(value).replace(",", "").replace("₹", "").strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not price.is_finite() or price < 0:
        return None
    return price.quantize(Decimal("0.01"))


def _normalize(value):
    return " ".join(str(value or "").split()).casefold()


def _catalog_key(item):
    identity = [
        item["name"],
        item["category"],
        item["brand"],
        format(item["price"], ".2f"),
        item["image"],
    ]
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"static:{digest}"


@lru_cache(maxsize=1)
def static_catalog():
    project_root = Path(__file__).resolve().parents[1]
    catalog_paths = (
        project_root / "ecommerce" / "admin_catalog.json",
        Path(__file__).with_name("local_catalog.json"),
    )
    products = {}

    for path in catalog_paths:
        try:
            with path.open(encoding="utf-8") as catalog_file:
                rows = json.load(catalog_file)
        except (OSError, json.JSONDecodeError) as error:
            raise StaticCatalogError(f"Unable to load static product catalog: {path.name}") from error
        if not isinstance(rows, list):
            raise StaticCatalogError(f"Static product catalog must be a list: {path.name}")

        for row in rows:
            if not isinstance(row, dict):
                logger.warning("Skipping malformed static catalog row in %s", path.name)
                continue
            name = str(row.get("name") or "").strip()
            category = str(row.get("category") or "").strip()
            price = _price(row.get("price"))
            if not name or not category or price is None:
                logger.warning(
                    "Skipping incomplete static catalog product from %s: %s",
                    path.name,
                    name or "(unnamed)",
                )
                continue

            raw_stock = row.get("stock")
            if raw_stock is None:
                stock_tracked = False
                stock = 0
            elif isinstance(raw_stock, bool):
                logger.warning("Skipping static catalog product with invalid stock: %s", name)
                continue
            else:
                try:
                    stock = int(raw_stock)
                except (TypeError, ValueError):
                    logger.warning("Skipping static catalog product with invalid stock: %s", name)
                    continue
                if stock < 0:
                    logger.warning("Skipping static catalog product with invalid stock: %s", name)
                    continue
                stock_tracked = True

            product = {
                "name": name,
                "category": category[:120],
                "brand": str(row.get("brand") or "").strip(),
                "price": price,
                "stock": stock,
                "stock_tracked": stock_tracked,
                "image": str(row.get("image") or "").strip(),
            }
            if len(product["name"]) > 255 or len(product["image"]) > 1000:
                logger.warning("Skipping oversized static catalog product: %s", name)
                continue
            products.setdefault(_catalog_key(product), product)

    return tuple(
        {**product, "catalog_key": key}
        for key, product in products.items()
    )


def resolve_static_catalog_item(payload):
    name = _normalize(payload.get("name"))
    price = _price(payload.get("price"))
    if not name or price is None:
        return None

    candidates = [
        product
        for product in static_catalog()
        if _normalize(product["name"]) == name and product["price"] == price
    ]
    if not candidates:
        return None

    category = _normalize(payload.get("category"))
    if category:
        category_matches = [
            product
            for product in candidates
            if category in {
                _normalize(part)
                for part in product["category"].split("/")
            }
            or category in _normalize(product["category"])
        ]
        if category_matches:
            candidates = category_matches

    image = str(payload.get("image") or "").strip()
    if image:
        image_matches = [
            product for product in candidates if product["image"] == image
        ]
        if image_matches:
            candidates = image_matches

    brand = _normalize(payload.get("brand"))
    if brand:
        brand_matches = [
            product for product in candidates if _normalize(product["brand"]) == brand
        ]
        if brand_matches:
            candidates = brand_matches

    unique_products = {product["catalog_key"]: product for product in candidates}
    if len(unique_products) != 1:
        return None
    return next(iter(unique_products.values()))
