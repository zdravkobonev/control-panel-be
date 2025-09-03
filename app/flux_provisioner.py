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
                    "backend":  {"repository":"ghcr.io/zdravkobonev/organization-be","tag": backend_tag},
                    "frontend": {"repository":"ghcr.io/zdravkobonev/organization-fe","tag": frontend_tag},
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
