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
from app.k8s_client import get_clients
from kubernetes import client
from app.flux_provisioner import apply_restaurant_helmrelease, ensure_namespace

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


def _normalize_name(name: str) -> str:
    import re
    if not name:
        return name
    return re.sub(r"\s+", "-", name.strip()).lower()

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

    # Ако имаме възможност за проверка в кластера — синхронизиране на статуса
    updated = False
    for r in rows:
        # защитно: прескачаме ако няма име или няма организация (трябва да има FK)
        if not r.name or not r.organization:
            continue

        release_name = f"restaurant-{r.name}"
        org_ns = r.organization.name

        try:
            core, crd = get_clients()

            # 1) Опитай HelmRelease (Flux v2)
            try:
                hr = crd.get_namespaced_custom_object(
                    group="helm.toolkit.fluxcd.io",
                    version="v2",
                    namespace=org_ns,
                    plural="helmreleases",
                    name=release_name,
                )
                status = (hr or {}).get("status", {}) or {}
                conditions = status.get("conditions", []) or []

                # намери Ready condition
                ready = None
                for c in conditions:
                    if (c.get("type") or "").lower() == "ready":
                        ready = c
                        break

                if ready:
                    cond_status = (ready.get("status") or "").lower()
                    reason = (ready.get("reason") or "").lower()
                    if cond_status == "true":
                        new_state = RestaurantStatus.active
                    elif cond_status in {"false", "unknown"} and any(k in reason for k in ("progress", "reconcil", "pending")):
                        new_state = RestaurantStatus.pending
                    elif cond_status in {"false", "unknown"}:
                        if any(k in reason for k in ("wait", "poll", "retry")):
                            new_state = RestaurantStatus.pending
                        else:
                            new_state = RestaurantStatus.error
                else:
                    # без Ready condition — ако има очевидни failed indicators
                    any_failed = False
                    for c in conditions or []:
                        st = (c.get("status") or "").lower()
                        reason = (c.get("reason") or "").lower()
                        ctype = (c.get("type") or "").lower()
                        if any(k in reason for k in ("fail", "degrad", "error")) or ctype in {"failed", "degraded"}:
                            any_failed = True
                            break
                    new_state = RestaurantStatus.error if any_failed else RestaurantStatus.pending

            except client.ApiException:
                # HelmRelease не е наличен/чете се — fallback към pod проверка
                hr = None

            # 2) Fallback: проверка на Pod-ове само ако няма категоричен резултат от HelmRelease
            if hr is None:
                try:
                    pods = (core.list_namespaced_pod(namespace=org_ns).items) or []
                    if not pods:
                        new_state = RestaurantStatus.pending
                    else:
                        any_error = False
                        all_ready = True
                        for p in pods:
                            cstatuses = p.status.container_statuses or []
                            if not cstatuses:
                                all_ready = False
                                continue
                            for cs in cstatuses:
                                st = cs.state
                                if st and st.waiting and st.waiting.reason in {
                                    "CrashLoopBackOff",
                                    "ErrImagePull",
                                    "ImagePullBackOff",
                                    "CreateContainerConfigError",
                                    "CreateContainerError",
                                }:
                                    any_error = True
                                if not cs.ready:
                                    all_ready = False

                        if any_error:
                            new_state = RestaurantStatus.error
                        elif all_ready:
                            new_state = RestaurantStatus.active
                        else:
                            new_state = RestaurantStatus.pending
                except Exception:
                    new_state = RestaurantStatus.error

        except Exception:
            # Ако въобще не можем да проверим — пропускаме
            continue

        if new_state != r.status:
            r.status = new_state
            db.add(r)
            updated = True

    if updated:
        db.commit()

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
    name=_normalize_name(payload.name),
        organization_id=payload.organization_id,
    version=payload.version if getattr(payload, 'version', None) is not None else "0.0.1",
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

    org_namespace = org.name  # винаги namespace = organization.name
    # използваме реалната, записана версия на ресторанта за таговете
    backend_tag = frontend_tag = r.version
    try:
        # гарантираме, че namespace-а съществува (създаден при организацията, но безопасно е да повикаме)
        ensure_namespace(org_namespace)
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

    # Забраняваме промяна на името чрез това ендпойнт (по-рано позволихме). Ако е нужно — махни проверката.
    if payload.name is not None:
        r.name = _normalize_name(payload.name)
    # Разрешаваме промяна само на status и version
    version_changed = False
    if hasattr(payload, 'version') and payload.version is not None and payload.version != r.version:
        # при смяна на версия — отбелязваме, че започва нов rollout
        r.version = payload.version
        r.status = RestaurantStatus.pending
        version_changed = True
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

    # Ако версията се смени — re-apply HelmRelease с новите тагове
    if version_changed:
        try:
            apply_restaurant_helmrelease(r.organization.name, r.name, r.version, r.version)
        except Exception as e:
            r.status = RestaurantStatus.error
            db.add(r)
            db.commit()
            raise HTTPException(500, f"Failed to roll out new restaurant version: {e}")
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
