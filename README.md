# Admin Login API (FastAPI + Postgres)

## Инсталация

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Миграции

```
alembic revision --autogenerate -m "add organizations"
alembic upgrade head
```

## Пускане

```bash
uvicorn app.main:app --reload
```

Health check: GET http://127.0.0.1:8000/health


## Seed на 1 админ

```bash python3 seeds/seed_admin.py```

## Бележки по сигурността

- Паролите се хешират с bcrypt (passlib).
- Съобщенията при неуспех са еднакви (не издаваме дали user съществува).
- Заключването се пази в БД (`locked_until`) и е устойчиво.
- При нужда добави JWT (PyJWT) за `access_token`.
