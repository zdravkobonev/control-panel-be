# routers/restaurants.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_current_user
from ..db import get_db
from ..models import Restaurant, RestaurantStatus, Organization, Admin
from ..schemas import (
    RestaurantOut,
    RestaurantCreate,
    RestaurantUpdate,
)

router = APIRouter(prefix="/restaurants", tags=["restaurants"])

@router.get("", response_model=list[RestaurantOut])
def list_restaurants(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    organization_id: int | None = Query(None),
    include_deleted: bool = Query(False),
    q: str | None = Query(None, description="Търсене по име (substring)"),
    status_in: list[RestaurantStatus] | None = Query(None),
):
    stmt = select(Restaurant)
    if not include_deleted:
        stmt = stmt.where(Restaurant.is_deleted.is_(False))
    if organization_id is not None:
        stmt = stmt.where(Restaurant.organization_id == organization_id)
    if q:
        stmt = stmt.where(Restaurant.name.ilike(f"%{q}%"))
    if status_in:
        stmt = stmt.where(Restaurant.status.in_(status_in))
    rows = db.scalars(stmt.offset(skip).limit(limit)).all()
    return rows


@router.get("/{restaurant_id}", response_model=RestaurantOut)
def get_restaurant(
    restaurant_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user),
):
    r = db.get(Restaurant, restaurant_id)
    if not r or r.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found.")
    return r


@router.post("", response_model=RestaurantOut, status_code=status.HTTP_201_CREATED)
def create_restaurant(
    payload: RestaurantCreate,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user),
):
    # валидираме, че организацията съществува и не е soft-deleted
    org = db.get(Organization, payload.organization_id)
    if not org or org.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    r = Restaurant(
        name=payload.name,
        organization_id=payload.organization_id,
        status=payload.status or RestaurantStatus.pending,
    )
    db.add(r)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # най-често: дублирано име в рамките на организация
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Restaurant with this name already exists in the organization.",
        )
    db.refresh(r)

    # --- HelmRelease за ресторанта ---
    from app.flux_provisioner import apply_restaurant_helmrelease
    org_namespace = org.name  # винаги namespace = organization.name
    backend_tag = frontend_tag = "0.0.1"  # фиксирано за сега
    try:
        apply_restaurant_helmrelease(org_namespace, r.name, backend_tag, frontend_tag)
    except Exception as e:
        r.status = RestaurantStatus.error
        db.add(r)
        db.commit()
        raise HTTPException(500, f"Failed provisioning restaurant in cluster: {e}")

    return r


@router.patch("/{restaurant_id}", response_model=RestaurantOut)
def update_restaurant(
    restaurant_id: int,
    payload: RestaurantUpdate,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user),
):
    r = db.get(Restaurant, restaurant_id)
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found.")
    if r.is_deleted:
        raise HTTPException(status_code=409, detail="Restaurant is deleted.")

    if payload.name is not None:
        r.name = payload.name
    if payload.status is not None:
        r.status = payload.status

    db.add(r)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Restaurant with this name already exists in the organization.",
        )
    db.refresh(r)
    return r


@router.delete("/{restaurant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_restaurant(
    restaurant_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user),
):
    r = db.get(Restaurant, restaurant_id)
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found.")
    if r.is_deleted:
        return None
    r.is_deleted = True
    r.status = RestaurantStatus.deleted
    db.add(r)
    db.commit()
    return None
