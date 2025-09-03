from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, DateTime, func, Enum, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base
import enum


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

class OrgStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"
    deleted = "deleted"

class RestaurantStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"
    deleted = "deleted"

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[OrgStatus] = mapped_column(
        Enum(OrgStatus, name="org_status_enum"),
        nullable=False,
        default=OrgStatus.pending,
        server_default=OrgStatus.pending.value,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    # FK към organizations.id
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # име на ресторанта (уникално в рамките на организация)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # статус + soft delete флаг
    status: Mapped[RestaurantStatus] = mapped_column(
        Enum(RestaurantStatus, name="restaurant_status_enum"),
        nullable=False,
        default=RestaurantStatus.pending,
        server_default=RestaurantStatus.pending.value,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )


    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # релация към Organization
    organization: Mapped["Organization"] = relationship(
        "Organization",
        backref="restaurants",
        lazy="joined",
    )

    # уникалност на името в рамките на една организация
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_restaurant_org_name"),
        Index("ix_restaurants_org_active", "organization_id", "is_deleted"),
    )