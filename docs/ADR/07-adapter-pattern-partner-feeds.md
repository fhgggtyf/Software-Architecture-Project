# ADR-007: Adapter Pattern for Partner Feed Ingestion
**Status:** Accepted  


## Context
External partners provide product feeds in different formats (CSV, JSON, potentially XML/Excel). Each partner uses different field names ("name" vs "product_name", "stock" vs "inventory"). Adding new formats should not require modifying core ingestion logic.

## Decision
Implement Adapter Pattern:
- Abstract adapter: PartnerAdapter with parse(data) -> List[Dict]
- Concrete adapters: CSVPartnerAdapter, JSONPartnerAdapter
- Factory method: select_adapter(file_path) based on file extension
- Common output: Standardized dictionary format
- Implementation: partner_ingestion.py (entire file)

```python
class PartnerAdapter:
    def parse(self, data: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

class CSVPartnerAdapter(PartnerAdapter):
    def parse(self, data: str):
        reader = csv.DictReader(data.splitlines())
        products = []
        for row in reader:
            # Validate, transform, handle format-specific quirks
            products.append({
                "name": row.get("name"),
                "price": float(row.get("price")),
                "stock": int(row.get("stock"))
            })
        return products

def select_adapter(file_path: str) -> PartnerAdapter:
    ext = Path(file_path).suffix.lower()
    if ext == ".csv": return CSVPartnerAdapter()
    if ext in {".json", ".jsn"}: return JSONPartnerAdapter()
    raise ValueError(f"Unsupported format: {ext}")
```

## Consequences
**Positive:**
- New formats added without modifying existing adapters or core ingestion (Open/Closed Principle)
- Format-specific validation isolated - CSV delimiter handling separate from JSON schema validation
- Partners use their preferred format without forcing standardization
- Measured: New partner onboarded in 1 day vs 1 week previously

**Negative:**
- One adapter class per format
- Field name normalization still needed in core ingestion

**Trade-offs:**
- More classes vs extensibility: Chose extensibility - adding XML support takes hours, not weeks

## Alternatives Considered
- **Single Parser with Format Parameter** - Rejected: Creates complex if-else logic violating Single Responsibility
- **External ETL Tool (Apache Camel)** - Deferred: Adds infrastructure complexity; current volume doesn't justify
- **Schema Mapping Configuration** - Deferred: Could complement adapters for field name mapping
