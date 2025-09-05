# app/flux_provisioner.py
from kubernetes import client
from .k8s_client import get_clients
from .config import settings


def ensure_namespace(name: str):
    core, _ = get_clients()
    ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=name))
    try:
        core.create_namespace(ns)
    except client.ApiException as e:
        if e.status != 409:  # 409 = вече съществува
            raise


def apply_helmrelease(name: str, backend_tag: str, frontend_tag: str):
    _, crd = get_clients()
    body = {
        "apiVersion": "helm.toolkit.fluxcd.io/v2",
        "kind": "HelmRelease",
        "metadata": {"name": name, "namespace": name},
        "spec": {
            "interval": "5m",
            "chart": {
                "spec": {
                    "chart": settings.CHART_PATH,
                    "sourceRef": {
                        "kind": settings.FLUX_SOURCE_KIND,
                        "name": settings.FLUX_SOURCE_NAME,
                        "namespace": settings.FLUX_SOURCE_NAMESPACE,
                    },
                }
            },
            "install": {"remediation": {"retries": 3}},
            "upgrade": {"remediation": {"retries": 3}},
            "values": {
                "orgName": name,
                "ingress": {"baseDomain": settings.BASE_DOMAIN},
                "images": {
                    "backend":  {"repository": "ghcr.io/zdravkobonev/organization-be", "tag": backend_tag},
                    "frontend": {"repository": "ghcr.io/zdravkobonev/organization-fe", "tag": frontend_tag},
                },
            },
        },
    }
    try:
        crd.create_namespaced_custom_object(
            group="helm.toolkit.fluxcd.io", version="v2",
            namespace=name, plural="helmreleases", body=body
        )
    except client.ApiException as e:
        if e.status == 409:  # вече съществува → update
            crd.patch_namespaced_custom_object(
                group="helm.toolkit.fluxcd.io", version="v2",
                namespace=name, plural="helmreleases", name=name, body=body
            )
        else:
            raise


def get_org_status(namespace: str) -> str:
    """
    Връща общ статус за организацията в дадения namespace:
      - "running"     → всичко е Ready (по HelmRelease Ready=True или всички pod-ове Ready)
      - "progressing" → още се вдига/реконсайлинг (Ready=False/Unknown, без грешки)
      - "error"       → има провали (Failed/Degraded, CrashLoopBackOff, ImagePullBackOff, и т.н.)
    """
    core, crd = get_clients()

    # 1) Опитай да прочетеш HelmRelease (Flux v2)
    try:
        hr = crd.get_namespaced_custom_object(
            group="helm.toolkit.fluxcd.io",
            version="v2",
            namespace=namespace,
            plural="helmreleases",
            name=namespace,
        )

        status = (hr or {}).get("status", {}) or {}
        conditions = status.get("conditions", []) or []

        # Намери Ready condition, ако има
        ready = _find_condition(conditions, "Ready")
        if ready:
            cond_status = (ready.get("status") or "").lower()        # "True" / "False" / "Unknown"
            reason = (ready.get("reason") or "").lower()             # "ReconciliationSucceeded", "Progressing", "InstallFailed", ...
            # Хепи път
            if cond_status == "true":
                return "running"
            # В процес (Flux често маркира Progressing/Reconciling като False/Unknown докато се вдига)
            if cond_status in {"false", "unknown"} and any(
                k in reason for k in ("progress", "reconcil", "pending")
            ):
                return "progressing"
            # Всичко друго с False/Unknown → вероятно проблем
            if cond_status in {"false", "unknown"}:
                # ако reason подсказва временно състояние, не е error
                if any(k in reason for k in ("wait", "poll", "retry")):
                    return "progressing"
                return "error"

        # Ако няма Ready condition, погледни други сигнали
        if _any_failed_condition(conditions):
            return "error"

        # Ако има status.conditions, но нищо категорично → progressing
        if conditions:
            return "progressing"

    except client.ApiException as e:
        if e.status == 404:
            # Няма HelmRelease все още → progressing (предполагаме, че ще се създаде скоро)
            pass
        else:
            # Ако API-то гръмне → ще проверим Pod-ове; ако и това гръмне, връщаме "error"
            pass

    # 2) Fallback: проверка на Pod-ове в namespace-а
    try:
        pods = (core.list_namespaced_pod(namespace=namespace).items) or []
        if not pods:
            return "progressing"

        any_error = False
        all_ready = True

        for p in pods:
            cstatuses = p.status.container_statuses or []
            if not cstatuses:
                all_ready = False
                continue
            for cs in cstatuses:
                st = cs.state
                # Грешки при стартиране/имиджи
                if st and st.waiting and st.waiting.reason in {
                    "CrashLoopBackOff",
                    "ErrImagePull",
                    "ImagePullBackOff",
                    "CreateContainerConfigError",
                    "CreateContainerError",
                }:
                    any_error = True
                # Не е готов
                if not cs.ready:
                    all_ready = False

        if any_error:
            return "error"
        if all_ready:
            return "running"
        return "progressing"

    except Exception:
        # Неуспешна проверка → счита се за проблем
        return "error"


def _find_condition(conditions: list[dict], cond_type: str) -> dict | None:
    for c in conditions:
        if (c.get("type") or "").lower() == cond_type.lower():
            return c
    return None


def _any_failed_condition(conditions: list[dict]) -> bool:
    """
    Търси очевидни failure индикатори по reasons/types от Flux/Helm.
    """
    for c in conditions or []:
        status = (c.get("status") or "").lower()
        reason = (c.get("reason") or "").lower()
        ctype = (c.get("type") or "").lower()
        if any(k in reason for k in ("fail", "degrad", "error")):
            return True
        if ctype in {"failed", "degraded"}:
            return True
        if status == "false" and any(k in reason for k in ("installfailed", "upgradefailed", "reconciliationfailed")):
            return True
    return False


# --- NEW: HelmRelease за ресторант ---
def apply_restaurant_helmrelease(org_namespace: str, restaurant_name: str, backend_tag: str, frontend_tag: str):
    """
    Създава или ъпдейтва HelmRelease за ресторант в даден namespace (на организацията).
    HelmRelease name: restaurant-<restaurant_name>
    Namespace: org_namespace
    """
    _, crd = get_clients()
    release_name = f"restaurant-{restaurant_name}"
    body = {
        "apiVersion": "helm.toolkit.fluxcd.io/v2",
        "kind": "HelmRelease",
        "metadata": {"name": release_name, "namespace": org_namespace},
        "spec": {
            "interval": "5m",
            "releaseName": release_name,
            "chart": {
                "spec": {
                    "chart": "charts/restaurant-stack",
                    "sourceRef": {
                        "kind": "GitRepository",
                        "name": "restaurant-stack",
                        "namespace": "flux-system",
                    },
                }
            },
            "install": {"remediation": {"retries": 3}},
            "upgrade": {"remediation": {"retries": 3}},
            "values": {
                "restaurantName": restaurant_name,
                "ingress": {"baseDomain": settings.BASE_DOMAIN},
                "images": {
                    "backend":  {"repository": "ghcr.io/zdravkobonev/restaurant-be", "tag": backend_tag},
                    "frontend": {"repository": "ghcr.io/zdravkobonev/restaurant-fe", "tag": frontend_tag},
                },
            },
        },
    }
    try:
        crd.create_namespaced_custom_object(
            group="helm.toolkit.fluxcd.io", version="v2",
            namespace=org_namespace, plural="helmreleases", body=body
        )
    except client.ApiException as e:
        if e.status == 409:  # вече съществува → update
            crd.patch_namespaced_custom_object(
                group="helm.toolkit.fluxcd.io", version="v2",
                namespace=org_namespace, plural="helmreleases", name=release_name, body=body
            )
        else:
            raise
