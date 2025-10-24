"""
Partner catalog ingestion utilities.

This module implements a simple adapter pattern to ingest product feeds from
external partners (resellers).  Partners may provide data in different
formats such as CSV or JSON.  Each adapter parses the incoming feed and
returns a list of product dictionaries.  A helper function then upserts
these products into the local catalogue using ``ProductDAO``.

Usage example:

    from dao import ProductDAO
    from partner_ingestion import ingest_partner_feed
    product_dao = ProductDAO()
    ingest_partner_feed('partner_feed.csv', product_dao)

The ingestion routine handles validation and transformation and will update
existing products (by name) or insert new ones if necessary.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, List, Dict, Any

from dao import ProductDAO


class PartnerAdapter:
    """Base class for partner feed adapters."""

    def parse(self, data: str) -> List[Dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError


class CSVPartnerAdapter(PartnerAdapter):
    """Parse a CSV feed.  Expected columns: name, price, stock, optional
    flash_sale_price, flash_sale_start, flash_sale_end."""

    def parse(self, data: str) -> List[Dict[str, Any]]:
        products: List[Dict[str, Any]] = []
        reader = csv.DictReader(data.splitlines())
        for row in reader:
            name = row.get("name", "").strip()
            if not name:
                continue
            try:
                price = float(row.get("price", 0))
                stock = int(row.get("stock", 0))
            except ValueError:
                # skip invalid rows
                continue
            p: Dict[str, Any] = {
                "name": name,
                "price": price,
                "stock": stock,
            }
            # Optional flash sale fields
            flash_price = row.get("flash_sale_price")
            if flash_price:
                try:
                    p["flash_sale_price"] = float(flash_price)
                except ValueError:
                    pass
            flash_start = row.get("flash_sale_start")
            if flash_start:
                p["flash_sale_start"] = flash_start
            flash_end = row.get("flash_sale_end")
            if flash_end:
                p["flash_sale_end"] = flash_end
            products.append(p)
        return products


class JSONPartnerAdapter(PartnerAdapter):
    """Parse a JSON feed.  The JSON must be an array of objects with keys
    matching those used by ``CSVPartnerAdapter``."""

    def parse(self, data: str) -> List[Dict[str, Any]]:
        try:
            items = json.loads(data)
        except json.JSONDecodeError:
            return []
        products: List[Dict[str, Any]] = []
        if not isinstance(items, list):
            return products
        for row in items:
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            try:
                price = float(row.get("price", 0))
                stock = int(row.get("stock", 0))
            except ValueError:
                continue
            p: Dict[str, Any] = {
                "name": name,
                "price": price,
                "stock": stock,
            }
            if "flash_sale_price" in row:
                try:
                    p["flash_sale_price"] = float(row["flash_sale_price"])
                except ValueError:
                    pass
            if "flash_sale_start" in row:
                p["flash_sale_start"] = str(row["flash_sale_start"])
            if "flash_sale_end" in row:
                p["flash_sale_end"] = str(row["flash_sale_end"])
            products.append(p)
        return products
    
class XMLPartnerAdapter(PartnerAdapter):
    """Simple XML feed parser: <products><product>...</product></products>"""
    def parse(self, data: str) -> list[dict[str, str]]:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(data)
        products = []
        for p in root.findall(".//product"):
            name = p.findtext("name") or "Unnamed"
            price = float(p.findtext("price") or 0)
            stock = int(p.findtext("stock") or 0)
            products.append({"name": name, "price": price, "stock": stock})
        return products


def select_adapter(file_path: str) -> PartnerAdapter:
    """Select an adapter based on the file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".csv":
        return CSVPartnerAdapter()
    if ext in {".json", ".jsn"}:
        return JSONPartnerAdapter()
    if ext == ".xml":
        return XMLPartnerAdapter()
    raise ValueError(f"Unsupported partner feed format: {ext}")


def ingest_partner_feed(file_path: str, product_dao: ProductDAO) -> None:
    """
    Ingest a partner feed file into the local catalogue.  This function will
    parse the file using the appropriate adapter, validate each product,
    and upsert it into the database via ``ProductDAO.upsert_product``.

    :param file_path: Path to the partner feed file (CSV or JSON)
    :param product_dao: An instance of ``ProductDAO`` used to insert/update products
    """
    adapter = select_adapter(file_path)
    path = Path(file_path)
    data = path.read_text(encoding="utf-8")
    products = adapter.parse(data)
    for prod in products:
        name = prod.get("name")
        price = prod.get("price", 0.0)
        stock = prod.get("stock", 0)
        flash_price = prod.get("flash_sale_price")
        flash_start = prod.get("flash_sale_start")
        flash_end = prod.get("flash_sale_end")
        product_dao.upsert_product(name, price, stock, flash_price, flash_start, flash_end)