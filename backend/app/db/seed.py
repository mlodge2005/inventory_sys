"""Idempotent reference data. Does not insert parts or quantities."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.defaults import (
    DEFAULT_APP_NAME,
    DEFAULT_CATEGORIES,
    DEFAULT_LANDING_PAGE,
    DEFAULT_LOW_STOCK_PERCENT,
)
from app.core.themes import preset_palette
from app.models import AppSetting, Category
from app.utils.ids import new_id
from app.utils.time import utcnow


def seed_reference_data(session: Session) -> None:
    for name, description, color in DEFAULT_CATEGORIES:
        existing = session.scalar(select(Category).where(Category.name == name))
        if existing is None:
            now = utcnow()
            session.add(
                Category(
                    id=new_id(),
                    name=name,
                    description=description,
                    color=color,
                    created_at=now,
                    updated_at=now,
                )
            )
    if session.get(AppSetting, 1) is None:
        palette = preset_palette("dark")
        assert palette is not None
        session.add(
            AppSetting(
                id=1,
                application_name=DEFAULT_APP_NAME,
                theme_preference="dark",
                color_palette=palette,
                default_low_stock_percent=DEFAULT_LOW_STOCK_PERCENT,
                preferred_landing_page=DEFAULT_LANDING_PAGE,
                display_preferences={"page_size": 25, "density": "comfortable", "show_sku": True},
                preferred_public_url=None,
                updated_at=utcnow(),
            )
        )
    session.flush()
