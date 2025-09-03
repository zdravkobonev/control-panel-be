from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from .models import OrgStatus 
from .models import RestaurantStatus


class LoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=6, max_length=128)

class LoginOut(BaseModel):
    success: bool
    message: str

class OrganizationBase(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    version: Optional[int] = Field(default=None, ge=1)
    status: Optional[OrgStatus] = None

class OrganizationCreate(OrganizationBase):
    name: str  # задължително при create

class OrganizationUpdate(OrganizationBase):
    pass  # всичко е опционално (PATCH)

class OrganizationOut(BaseModel):
    id: int
    name: str
    version: int
    status: OrgStatus
    created_at: datetime

    class Config:
        from_attributes = True


class RestaurantBase(BaseModel):
    name: str = Field(..., max_length=255)
    organization_id: int
    status: Optional[RestaurantStatus] = None

class RestaurantCreate(RestaurantBase):
    # фронтендът ти подава поне name и organization_id;
    # останалото е опционално
    pass

class RestaurantUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    status: Optional[RestaurantStatus] = None

class RestaurantOut(BaseModel):
    id: int
    name: str
    organization_id: int
    status: RestaurantStatus
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True