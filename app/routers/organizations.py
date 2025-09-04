from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_current_user
from ..db import get_db
from ..models import Organization, OrgStatus, Admin
from ..schemas import OrganizationOut, OrganizationCreate, OrganizationUpdate

from app.flux_provisioner import ensure_namespace, apply_helmrelease
# NEW: ще опитаме да използваме helper, ако съществува
try:
    from app.flux_provisioner import get_org_status  # очаква str: "running" | "progressing" | "error"
except Exception:
    get_org_status = None  # ще fallback-нем по-долу

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _map_cluster_state_to_org_status(cluster_state: str) -> OrgStatus:
    """
    Преобразува състояние от кластера към OrgStatus.
    running      -> active
    progressing  -> pending
    error        -> error
    other        -> suspended
    """
    s = (cluster_state or "").lower()
    if s == "running":
        return OrgStatus.active
    if s == "progressing":
        return OrgStatus.pending
    if s == "error":
        return OrgStatus.error
    return OrgStatus.suspended


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

    # Ако имаме функция за проверка на статуса в кластера — синхронизираме.
    updated = False
    for org in rows:
        # защитно: прескачаме ако няма име
        if not org.name:
            continue

        try:
            if get_org_status is None:
                # Нямаме имплементация: НЕ променяме статуса, само връщаме каквото е в БД.
                continue

            cluster_state = get_org_status(org.name)  # "running" | "progressing" | "error"
            new_status = _map_cluster_state_to_org_status(cluster_state)

        except Exception:
            # Ако проверката фейлне, маркираме като suspended (по-неутрално от error тук)
            new_status = OrgStatus.suspended

        if new_status != org.status:
            org.status = new_status
            db.add(org)
            updated = True

    if updated:
        db.commit()
        # не е нужно refresh на всеки ред — вече са в паметта с новия статус

    return rows


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    current_user: Admin = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    org = Organization(
        name=payload.name,
        # SemVer низ; по подразбиране "1.0.0"
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

    # Използваме реалната версия от БД за таговете
    be_tag = org.version
    fe_tag = org.version

    try:
        ensure_namespace(org.name)
        apply_helmrelease(org.name, be_tag, fe_tag)
    except Exception as e:
        # ако provisioning-ът се провали → статус error
        org.status = OrgStatus.error
        db.add(org)
        db.commit()
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

    # 🚫 Забраняваме промяна на името
    if payload.name is not None and payload.name != org.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization name cannot be changed."
        )

    # (по избор) блокирай външна промяна на статус през този ендпойнт
    if payload.status is not None and payload.status != org.status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization status cannot be changed via this endpoint."
        )

    # Разрешена промяна: само версията
    version_changed = False
    if payload.version is not None and payload.version != org.version:
        org.version = payload.version
        org.status = OrgStatus.pending  # започва нов rollout
        version_changed = True

    db.add(org)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # единствен възможен конфликт тук е по name, но ние не го пипаме; все пак пазим обработката
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict while updating organization."
        )
    db.refresh(org)

    # Ако версията се смени — re-apply HelmRelease с новите тагове
    if version_changed:
        be_tag = org.version
        fe_tag = org.version
        try:
            apply_helmrelease(org.name, be_tag, fe_tag)
        except Exception as e:
            # при провал на rollout → отбелязваме като error
            org.status = OrgStatus.error
            db.add(org)
            db.commit()
            raise HTTPException(500, f"Failed to roll out new version: {e}")

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
