"""Relational inventory model.

Quantity convention for stock_transactions (also documented in docs/DATABASE.md):

- ``quantity`` is the nonnegative number of pieces involved.
- ``quantity_delta`` is the signed change applied to the primary slot.
- ``quantity_before`` and ``quantity_after`` are that primary slot's quantity,
  not the part's aggregate total.
- The primary slot is the destination for INITIAL_STOCK, ADD, RESTOCK, and ADJUST,
  and the source for REMOVE and TRANSFER.
- TRANSFER also stores the destination slot's before/after quantities.
- Slot numbers and part names on a transaction are snapshots from write time.
  Renames do not rewrite history.
- Aggregate part quantity is the sum of slot_inventory.quantity. It is not
  stored as a second mutable column on the part.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    parts: Mapped[list[Part]] = relationship(back_populates="category")

    __table_args__ = (Index("uq_categories_name_lower", func.lower(name), unique=True),)


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manufacturer_part_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    specifications: Mapped[dict | None] = mapped_column("specifications_json", JSON, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="pcs")
    initial_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_stock_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    low_stock_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category: Mapped[Category | None] = relationship(back_populates="parts")
    allocations: Mapped[list[SlotInventory]] = relationship(back_populates="part")

    __table_args__ = (
        Index("uq_parts_sku_lower", func.lower(sku), unique=True),
        Index("ix_parts_category_id", "category_id"),
        Index("ix_parts_name", "name"),
        Index("ix_parts_archived_at", "archived_at"),
        CheckConstraint("initial_quantity >= 0", name="initial_nonnegative"),
        CheckConstraint(
            "low_stock_percent >= 0 AND low_stock_percent <= 100",
            name="low_percent_range",
        ),
        CheckConstraint(
            "low_stock_override IS NULL OR low_stock_override >= 0",
            name="override_nonnegative",
        ),
    )


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    allocations: Mapped[list[SlotInventory]] = relationship(back_populates="slot")

    __table_args__ = (
        Index("ix_slots_archived_at", "archived_at"),
        CheckConstraint("slot_number > 0", name="slot_number_positive"),
    )


class SlotInventory(Base):
    __tablename__ = "slot_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slot_id: Mapped[str] = mapped_column(ForeignKey("slots.id", ondelete="RESTRICT"), nullable=False)
    part_id: Mapped[str] = mapped_column(ForeignKey("parts.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    slot: Mapped[Slot] = relationship(back_populates="allocations")
    part: Mapped[Part] = relationship(back_populates="allocations")

    __table_args__ = (
        UniqueConstraint("slot_id", "part_id", name="uq_slot_inventory_slot_part"),
        CheckConstraint("quantity >= 0", name="quantity_nonnegative"),
        Index("ix_slot_inventory_part_id", "part_id"),
    )


class StockTransaction(Base):
    __tablename__ = "stock_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    part_id: Mapped[str] = mapped_column(ForeignKey("parts.id", ondelete="RESTRICT"), nullable=False)
    part_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    part_sku_snapshot: Mapped[str | None] = mapped_column(String(80), nullable=True)
    from_slot_id: Mapped[str | None] = mapped_column(
        ForeignKey("slots.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_slot_id: Mapped[str | None] = mapped_column(
        ForeignKey("slots.id", ondelete="SET NULL"),
        nullable=True,
    )
    from_slot_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_slot_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_before: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)
    dest_quantity_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dest_quantity_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("quantity_before >= 0", name="before_nonnegative"),
        CheckConstraint("quantity_after >= 0", name="after_nonnegative"),
        CheckConstraint(
            "dest_quantity_before IS NULL OR dest_quantity_before >= 0",
            name="dest_before_nonnegative",
        ),
        CheckConstraint(
            "dest_quantity_after IS NULL OR dest_quantity_after >= 0",
            name="dest_after_nonnegative",
        ),
        Index("ix_stock_transactions_part_id", "part_id"),
        Index("ix_stock_transactions_created_at", "created_at"),
        Index("ix_stock_transactions_type", "transaction_type"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    changes: Mapped[dict] = mapped_column("changes_json", JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_name: Mapped[str] = mapped_column(String(80), nullable=False)
    theme_preference: Mapped[str] = mapped_column(String(32), nullable=False)
    color_palette: Mapped[dict] = mapped_column("color_palette_json", JSON, nullable=False)
    default_low_stock_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    preferred_landing_page: Mapped[str] = mapped_column(String(32), nullable=False)
    display_preferences: Mapped[dict] = mapped_column(
        "display_preferences_json",
        JSON,
        nullable=False,
    )
    preferred_public_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(
            "default_low_stock_percent >= 0 AND default_low_stock_percent <= 100",
            name="default_percent_range",
        ),
    )
