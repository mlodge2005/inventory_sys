"""Versioned inventory routes. Mutations go through InventoryService."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.api.deps import get_service
from app.core.constants import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.core.themes import PRESETS
from app.schemas.api import (
    AuditOut,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    DeleteResult,
    DisposeRequest,
    ImportBundle,
    Page,
    PartCreate,
    PartOut,
    PartUpdate,
    SettingsOut,
    SettingsUpdate,
    SlotCreate,
    SlotOut,
    SlotSummary,
    SlotUpdate,
    StatsOut,
    StockAdd,
    StockAdjust,
    StockRemove,
    StockTransfer,
    TransactionOut,
)
from app.services.csv_io import apply_plan, export_csv, plan_bundle
from app.services.inventory import InventoryService
from app.services.network import detect_addresses, exposure_warnings
from app.services.views import transaction_dict
from app.utils.color import PALETTE_KEYS

router = APIRouter(prefix="/api/v1", tags=["inventory"])


@router.get("/health", tags=["meta"])
def health(request: Request):
    from sqlalchemy import text

    from app.maintenance import schema_revision

    settings = request.app.state.settings
    database = "error"
    revision = None
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT COUNT(*) FROM app_settings"))
        database = "ok"
        revision = schema_revision(settings.resolved_database_path)
    except Exception:
        database = "error"
    frontend = settings.resolved_frontend_dist.joinpath("index.html").is_file()
    from app import __version__
    from fastapi.responses import JSONResponse

    payload = {
        "status": "ok" if database == "ok" else "degraded",
        "version": __version__,
        "database": database,
        "schema_revision": revision,
        "frontend": frontend,
    }
    if database != "ok":
        return JSONResponse(status_code=503, content=payload)
    return payload


@router.get("/items", response_model=Page[PartOut])
def list_items(
    service: InventoryService = Depends(get_service),
    search: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=120),
    status: str | None = None,
    slot: int | None = Query(default=None, alias="slot"),
    include_archived: bool = False,
    sort: str = "name",
    order: str = "asc",
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict:
    items, total = service.list_part_views(
        search=search,
        category=category,
        status=status,
        slot_number=slot,
        include_archived=include_archived,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/items", response_model=PartOut, status_code=201)
def create_item(body: PartCreate, service: InventoryService = Depends(get_service)) -> dict:
    return service.create_part(body.model_dump())


@router.get("/items/{part_id}", response_model=PartOut)
def get_item(part_id: str, service: InventoryService = Depends(get_service)) -> dict:
    return service.part_view(part_id)


@router.patch("/items/{part_id}", response_model=PartOut)
def update_item(part_id: str, body: PartUpdate, service: InventoryService = Depends(get_service)) -> dict:
    return service.update_part(part_id, body.model_dump(exclude_unset=True))


@router.post("/items/{part_id}/archive", response_model=PartOut)
def archive_item(
    part_id: str,
    body: DisposeRequest | None = None,
    service: InventoryService = Depends(get_service),
) -> dict:
    payload = body or DisposeRequest()
    return service.archive_part(
        part_id,
        confirm_remove_stock=payload.confirm_remove_stock,
        reason=payload.reason,
    )


@router.post("/items/{part_id}/unarchive", response_model=PartOut)
def unarchive_item(part_id: str, service: InventoryService = Depends(get_service)) -> dict:
    return service.unarchive_part(part_id)


@router.delete("/items/{part_id}", response_model=DeleteResult)
def delete_item(part_id: str, service: InventoryService = Depends(get_service)) -> dict:
    service.delete_part(part_id)
    return {"deleted": True}


@router.get("/items/{part_id}/transactions", response_model=Page[TransactionOut])
def item_transactions(
    part_id: str,
    service: InventoryService = Depends(get_service),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict:
    service.part_view(part_id)
    items, total = service.list_transactions(part_id=part_id, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/items/{part_id}/audit", response_model=list[AuditOut])
def item_audit(part_id: str, service: InventoryService = Depends(get_service)) -> list[dict]:
    service.part_view(part_id)
    return service.list_audit(entity_type="part", entity_id=part_id)


@router.get("/slots", response_model=Page[SlotSummary])
def list_slots(
    service: InventoryService = Depends(get_service),
    search: str | None = Query(default=None, max_length=200),
    include_archived: bool = False,
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict:
    items, total = service.list_slots(
        search=search,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/slots", response_model=SlotOut, status_code=201)
def create_slot(body: SlotCreate, service: InventoryService = Depends(get_service)) -> dict:
    return service.create_slot(**body.model_dump())


@router.get("/slots/{slot_number}", response_model=SlotOut)
def get_slot(slot_number: int, service: InventoryService = Depends(get_service)) -> dict:
    return service.slot_view(slot_number)


@router.patch("/slots/{slot_number}", response_model=SlotOut)
def update_slot(
    slot_number: int,
    body: SlotUpdate,
    service: InventoryService = Depends(get_service),
) -> dict:
    return service.update_slot(slot_number, body.model_dump(exclude_unset=True))


@router.post("/slots/{slot_number}/archive", response_model=SlotOut)
def archive_slot(
    slot_number: int,
    body: DisposeRequest | None = None,
    service: InventoryService = Depends(get_service),
) -> dict:
    payload = body or DisposeRequest()
    return service.archive_slot(
        slot_number,
        confirm_remove_stock=payload.confirm_remove_stock,
        reason=payload.reason,
    )


@router.post("/slots/{slot_number}/unarchive", response_model=SlotOut)
def unarchive_slot(slot_number: int, service: InventoryService = Depends(get_service)) -> dict:
    return service.unarchive_slot(slot_number)


@router.delete("/slots/{slot_number}", response_model=DeleteResult)
def delete_slot(
    slot_number: int,
    body: DisposeRequest | None = None,
    service: InventoryService = Depends(get_service),
) -> dict:
    payload = body or DisposeRequest()
    service.delete_slot(
        slot_number,
        confirm_remove_stock=payload.confirm_remove_stock,
        reason=payload.reason,
    )
    return {"deleted": True}


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(service: InventoryService = Depends(get_service)) -> list[dict]:
    return service.list_categories()


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryCreate, service: InventoryService = Depends(get_service)) -> dict:
    return service.create_category(**body.model_dump())


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: str,
    body: CategoryUpdate,
    service: InventoryService = Depends(get_service),
) -> dict:
    return service.update_category(category_id, body.model_dump(exclude_unset=True))


@router.delete("/categories/{category_id}", response_model=DeleteResult)
def delete_category(
    category_id: str,
    service: InventoryService = Depends(get_service),
    reassign_to: str | None = None,
    allow_clear: bool = False,
) -> dict:
    service.delete_category(category_id, reassign_to=reassign_to, allow_clear=allow_clear)
    return {"deleted": True}


@router.post("/stock/add", response_model=TransactionOut)
def stock_add(body: StockAdd, service: InventoryService = Depends(get_service)) -> dict:
    txn = service.add_stock(**body.model_dump())
    return transaction_dict(txn)


@router.post("/stock/remove", response_model=TransactionOut)
def stock_remove(body: StockRemove, service: InventoryService = Depends(get_service)) -> dict:
    txn = service.remove_stock(**body.model_dump())
    return transaction_dict(txn)


@router.post("/stock/transfer", response_model=TransactionOut)
def stock_transfer(body: StockTransfer, service: InventoryService = Depends(get_service)) -> dict:
    txn = service.transfer_stock(**body.model_dump())
    return transaction_dict(txn)


@router.post("/stock/adjust", response_model=TransactionOut)
def stock_adjust(body: StockAdjust, service: InventoryService = Depends(get_service)) -> dict:
    txn = service.adjust_stock(**body.model_dump())
    return transaction_dict(txn)


@router.get("/transactions", response_model=Page[TransactionOut])
def list_transactions(
    service: InventoryService = Depends(get_service),
    part_id: str | None = None,
    slot: int | None = None,
    transaction_type: str | None = None,
    source: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict:
    items, total = service.list_transactions(
        part_id=part_id,
        slot_number=slot,
        transaction_type=transaction_type,
        source=source,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/alerts/low-stock", response_model=Page[PartOut])
def low_stock(
    service: InventoryService = Depends(get_service),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    items, total = service.low_stock(limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/stats", response_model=StatsOut)
def stats(service: InventoryService = Depends(get_service)) -> dict:
    return service.stats()


@router.get("/settings", response_model=SettingsOut)
def get_settings_route(service: InventoryService = Depends(get_service)) -> dict:
    return service.get_settings_view()


@router.patch("/settings", response_model=SettingsOut)
def update_settings_route(body: SettingsUpdate, service: InventoryService = Depends(get_service)) -> dict:
    payload = body.model_dump(exclude_unset=True)
    if "display_preferences" in payload and payload["display_preferences"] is not None:
        payload["display_preferences"] = body.display_preferences.model_dump()
    return service.update_settings(payload)


@router.get("/themes", tags=["meta"])
def themes() -> dict:
    return {"presets": PRESETS, "keys": list(PALETTE_KEYS)}


@router.get("/network", tags=["meta"])
def network(request: Request, service: InventoryService = Depends(get_service)) -> dict:
    settings = request.app.state.settings
    addresses = detect_addresses()
    saved = service.get_settings_view()
    return {
        "bind_host": settings.host,
        "port": settings.port,
        "preferred_public_url": saved["preferred_public_url"] or settings.public_url or None,
        "addresses": [
            {
                "interface": address.interface,
                "ip": address.ip,
                "kind": address.kind,
                "url": address.url(settings.port),
            }
            for address in addresses
        ],
        "warnings": exposure_warnings(settings.host, addresses),
    }


@router.get("/export/{kind}", response_class=PlainTextResponse)
def export_kind(kind: str, service: InventoryService = Depends(get_service)) -> Response:
    if kind.endswith(".csv"):
        kind = kind[: -len(".csv")]
    body = export_csv(service, kind)
    return PlainTextResponse(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'},
    )


@router.post("/import/preview")
def import_preview(body: ImportBundle, service: InventoryService = Depends(get_service)) -> dict:
    plan = plan_bundle(service, **body.model_dump())
    return plan.as_dict()


@router.post("/import/commit")
def import_commit(body: ImportBundle, service: InventoryService = Depends(get_service)) -> dict:
    plan = plan_bundle(service, **body.model_dump())
    # Apply uses the same session. The request dependency commits only if this returns.
    service.source = "import"
    return apply_plan(service, plan)
