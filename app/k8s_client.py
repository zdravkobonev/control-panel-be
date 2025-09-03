# app/k8s_client.py
from kubernetes import client, config
from .config import settings

def get_clients():
    # ако имаш settings.KUBECONFIG (примерно в прод) → ползва него;
    # иначе локално чете ~/.kube/config (minikube)
    if settings.KUBECONFIG:
        config.load_kube_config(config_file=settings.KUBECONFIG)
    else:
        config.load_kube_config()

    core = client.CoreV1Api()       # namespaces, pods, services...
    crd = client.CustomObjectsApi() # Flux HelmRelease (CRD)
    return core, crd
