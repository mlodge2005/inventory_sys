"""Request and response schemas for /api/v1.

Field names match the JSON documented in docs/API.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    color: str | None = None
    created_at: datetime
    updated_at: datetime


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    color: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    color: str | None = None


class SlotBrief(BaseModel):
    slot_id: str
    slot_number: int
    label: str | None = None
    location: str | None = None
    quantity: int


class PartOut(BaseModel):
    id: str
    sku: str | None = None
    name: str
    description: str | None = None
    category: CategoryOut | None = None
    manufacturer: str | None = None
    manufacturer_part_number: str | None = None
    specifications: dict = Field(default_factory=dict)
    unit: str
    initial_quantity: int
    low_stock_percent: int
    low_stock_override: int | None = None
    notes: str | None = None
    current_quantity: int
    threshold: int | None = None
    threshold_configured: bool
    baseline_state: Literal["OK", "BASELINE_NOT_SET"]
    status: Literal["OUT_OF_STOCK", "LOW_STOCK", "IN_STOCK"]
    slots: list[SlotBrief]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class AllocationIn(BaseModel):
    slot_number: int = Field(gt=0)
    quantity: int = Field(gt=0)
    reason: str | None = None


class PartCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "M3 x 10mm screw",
                    "sku": "M3-10",
                    "initial_quantity": 100,
                    "category_id": None,
                    "allocations": [{"slot_number": 110, "quantity": 100}],
                }
            ]
        }
    )

    name: str = Field(min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=80)
    description: str | None = None
    category_id: str | None = None
    manufacturer: str | None = None
    manufacturer_part_number: str | None = None
    specifications: dict | None = None
    unit: str = "pcs"
    initial_quantity: int = Field(default=0, ge=0)
    low_stock_percent: int | None = Field(default=None, ge=0, le=100)
    low_stock_override: int | None = Field(default=None, ge=0)
    notes: str | None = None
    allocations: list[AllocationIn] = Field(default_factory=list)


class PartUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str | None = None
    description: str | None = None
    category_id: str | None = None
    manufacturer: str | None = None
    manufacturer_part_number: str | None = None
    specifications: dict | None = None
    unit: str | None = None
    initial_quantity: int | None = Field(default=None, ge=0)
    low_stock_percent: int | None = Field(default=None, ge=0, le=100)
    low_stock_override: int | None = None
    notes: str | None = None


class SlotItem(BaseModel):
    part_id: str
    name: str
    sku: str | None = None
    unit: str
    quantity: int
    category_id: str | None = None


class SlotOut(BaseModel):
    id: str
    slot_number: int
    label: str | None = None
    description: str | None = None
    location: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    items: list[SlotItem]
    total_units: int


class SlotSummary(BaseModel):
    id: str
    slot_number: int
    label: str | None = None
    description: str | None = None
    location: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    total_units: int
    part_count: int


class SlotCreate(BaseModel):
    slot_number: int = Field(gt=0)
    label: str | None = None
    description: str | None = None
    location: str | None = None


class SlotUpdate(BaseModel):
    slot_number: int | None = Field(default=None, gt=0)
    label: str | None = None
    description: str | None = None
    location: str | None = None


class DisposeRequest(BaseModel):
    confirm_remove_stock: bool = False
    reason: str | None = None


class StockAdd(BaseModel):
    part_id: str
    slot_number: int = Field(gt=0)
    quantity: int = Field(gt=0)
    transaction_type: Literal["ADD", "RESTOCK", "INITIAL_STOCK"] = "ADD"
    reason: str | None = None


class StockRemove(BaseModel):
    part_id: str
    slot_number: int = Field(gt=0)
    quantity: int = Field(gt=0)
    reason: str | None = None


class StockTransfer(BaseModel):
    part_id: str
    from_slot: int = Field(gt=0)
    to_slot: int = Field(gt=0)
    quantity: int = Field(gt=0)
    reason: str | None = None


class StockAdjust(BaseModel):
    part_id: str
    slot_number: int = Field(gt=0)
    new_quantity: int = Field(ge=0)
    reason: str | None = None


class TransactionOut(BaseModel):
    id: str
    part_id: str
    part_name: str
    part_sku: str | None = None
    from_slot_id: str | None = None
    from_slot_number: int | None = None
    to_slot_id: str | None = None
    to_slot_number: int | None = None
    transaction_type: str
    quantity: int
    quantity_delta: int
    quantity_before: int
    quantity_after: int
    dest_quantity_before: int | None = None
    dest_quantity_after: int | None = None
    quantity_scope: Literal["slot"] = "slot"
    reason: str | None = None
    source: str
    created_at: datetime


class AuditOut(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    action: str
    changes: dict
    source: str
    created_at: datetime


class StatsOut(BaseModel):
    active_part_types: int
    occupied_slots: int
    total_units: int
    low_stock_part_types: int
    out_of_stock_part_types: int
    archived_part_types: int
    drawer_count: int


class DisplayPreferences(BaseModel):
    page_size: int = Field(default=25, ge=10, le=100)
    density: Literal["comfortable", "compact"] = "comfortable"
    show_sku: bool = True


class SettingsOut(BaseModel):
    application_name: str
    theme_preference: str
    color_palette: dict
    default_low_stock_percent: int
    preferred_landing_page: str
    display_preferences: DisplayPreferences
    preferred_public_url: str | None = None
    updated_at: datetime


class SettingsUpdate(BaseModel):
    application_name: str | None = None
    theme_preference: str | None = None
    color_palette: dict | None = None
    default_low_stock_percent: int | None = Field(default=None, ge=0, le=100)
    preferred_landing_page: str | None = None
    display_preferences: DisplayPreferences | None = None
    preferred_public_url: str | None = None


class ImportBundle(BaseModel):
    categories_csv: str | None = None
    slots_csv: str | None = None
    parts_csv: str | None = None
    allocations_csv: str | None = None
    mode: Literal["create_only", "update_metadata"] = "create_only"
    allocation_mode: Literal["add", "skip_existing"] = "add"


class HealthOut(BaseModel):
    status: str
    version: str
    database: str
    schema_revision: str | None = None
    frontend: bool


class DeleteResult(BaseModel):
    deleted: bool = True
