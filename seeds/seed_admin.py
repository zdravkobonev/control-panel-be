import getpass
import os
from sqlalchemy import select
from sqlalchemy.orm import Session

# позволяваме стартиране от корен на проекта
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import engine
from app.models import Admin
from app.security import hash_password

def main():
    username = os.getenv("ADMIN_USERNAME") or input("Admin username [admin]: ") or "admin"
    password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")

    with Session(engine) as db:
        exists = db.scalar(select(Admin).where(Admin.username == username))
        if exists:
            print(f"Admin '{username}' already exists. Nothing to do.")
            return

        admin = Admin(username=username, password_hash=hash_password(password))
        db.add(admin)
        db.commit()
        print(f"Admin '{username}' created.")

if __name__ == "__main__":
    main()
