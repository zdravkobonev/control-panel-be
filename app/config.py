# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str

    # JWT / Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Lockout policy
    MAX_LOGIN_ATTEMPTS: int = 3
    LOCKOUT_MINUTES: int = 1

    # >>> NEW: Kubernetes/Flux <<<
    # Prod
    # KUBECONFIG=/etc/org-provisioner/prod-kubeconfig   # път до kubeconfig файла за прод клъстъра
    # BASE_DOMAIN=example.com                           # реалният ти домейн
    # Prod
    KUBECONFIG: str | None = None                 # локално остави празно (ще ползва ~/.kube/config → minikube)
    BASE_DOMAIN: str = "127.0.0.1.nip.io"         # локално nip.io; в прод: твоя домейн (пример: example.com)
    FLUX_SOURCE_KIND: str = "GitRepository"
    FLUX_SOURCE_NAME: str = "org-stack"           # името от gitrepository.yaml
    FLUX_SOURCE_NAMESPACE: str = "flux-system"
    CHART_PATH: str = "charts/org-stack"          # пътят до чарта в твоето repo

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

settings = Settings()
