from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_current_user
from ..db import get_db
from ..models import Organization, OrgStatus, Admin
from ..schemas import OrganizationOut, OrganizationCreate, OrganizationUpdate

from app.flux_provisioner import ensure_namespace, apply_helmrelease
from app.config import settings

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationOut])
def list_organizations(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    rows = db.scalars(
        select(Organization)
        .where(Organization.is_deleted.is_(False))
        .offset(skip)
        .limit(limit)
    ).all()
    return rows


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    current_user: Admin = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    org = Organization(
        name=payload.name,
        # ВЕЧЕ е string SemVer; по подразбиране "1.0.0"
        version=payload.version if payload.version is not None else "1.0.0",
        status=payload.status if payload.status is not None else OrgStatus.pending,
    )
    db.add(org)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # най-често: уникално име се дублира
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization with this name already exists.",
        )
    db.refresh(org)

    try:
        ensure_namespace(org.name)
        apply_helmrelease(org.name, payload.version, payload.version)
    except Exception as e:
        raise HTTPException(500, f"Failed provisioning in cluster: {e}")

    return org


@router.patch("/{org_id}", response_model=OrganizationOut)
def update_organization(
    org_id: int,
    payload: OrganizationUpdate,
    current_user: Admin = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    if org.is_deleted:
        raise HTTPException(status_code=409, detail="Organization is deleted.")

    # частичен update
    if payload.name is not None:
        org.name = payload.name
    if payload.version is not None:
        # payload.version е вече валидиран SemVer string от Pydantic
        org.version = payload.version
    if payload.status is not None:
        org.status = payload.status

    db.add(org)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization with this name already exists.",
        )
    db.refresh(org)
    return org


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    org_id: int,
    current_user: Admin = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    
    if org.is_deleted:
        return None
    
    org.is_deleted = True
    org.status = OrgStatus.deleted
    db.add(org)
    db.commit()
    return None
