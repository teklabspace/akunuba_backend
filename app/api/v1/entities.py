from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, asc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timezone
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.entity import (
    Entity, EntityType, EntityStatus, EntityCompliance, ComplianceStatus,
    EntityPerson, EntityRole, EntityDocument, EntityDocumentType, DocumentStatus,
    EntityAuditTrail, AuditAction
)
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Permission, has_permission
from app.utils.logger import logger
from app.integrations.supabase_client import SupabaseClient
from app.config import settings
from uuid import UUID
from pydantic import BaseModel
import io
import zipfile
import secrets

router = APIRouter()


# ==================== SCHEMAS ====================

class EntityCreate(BaseModel):
    name: str
    entity_type: EntityType
    jurisdiction: Optional[str] = None
    location: Optional[str] = None
    registration_number: Optional[str] = None
    formation_date: Optional[str] = None  # YYYY-MM-DD
    parent_entity_id: Optional[UUID] = None
    description: Optional[str] = None


class EntityUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    status: Optional[EntityStatus] = None
    description: Optional[str] = None


class EntityResponse(BaseModel):
    id: UUID
    name: str
    location: Optional[str] = None
    registration_number: Optional[str] = None
    formation_date: Optional[str] = None
    status: str
    entity_type: str
    jurisdiction: Optional[str] = None
    parent_entity_id: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EntityDetailResponse(EntityResponse):
    child_entities: List[Dict[str, Any]] = []
    compliance_status: Optional[Dict[str, Any]] = None


class EntityTypeResponse(BaseModel):
    type: str
    full_name: str
    jurisdiction: str
    formation_rates: str
    description: str
    available_jurisdictions: List[str]


class ComplianceUpdate(BaseModel):
    kyc_aml_status: Optional[ComplianceStatus] = None
    registered_agent: Optional[str] = None
    tax_residency: Optional[str] = None
    fatca_crs_compliance: Optional[ComplianceStatus] = None


class PersonCreate(BaseModel):
    name: str
    role: EntityRole
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[UUID] = None


class PersonUpdate(BaseModel):
    role: Optional[EntityRole] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class DocumentStatusUpdate(BaseModel):
    status: DocumentStatus
    notes: Optional[str] = None


class AuditTrailCreate(BaseModel):
    action: AuditAction
    notes: Optional[str] = None
    document_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None


class AuditTrailUpdate(BaseModel):
    notes: Optional[str] = None


# ==================== HELPER FUNCTIONS ====================

def get_role_display(role: EntityRole) -> str:
    """Convert role enum to display name"""
    role_map = {
        EntityRole.TRUSTEE: "Trustee",
        EntityRole.SIGNATORY: "Signatory",
        EntityRole.POWER_OF_ATTORNEY: "Power of Attorney",
        EntityRole.DIRECTOR: "Director",
        EntityRole.OFFICER: "Officer",
        EntityRole.MEMBER: "Member",
        EntityRole.MANAGER: "Manager",
        EntityRole.BENEFICIARY: "Beneficiary",
        EntityRole.OTHER: "Other"
    }
    return role_map.get(role, role.value.title())


def get_document_type_display(doc_type: EntityDocumentType) -> str:
    """Convert document type enum to display name"""
    type_map = {
        EntityDocumentType.ARTICLES_OF_INCORPORATION: "Articles of Incorporation",
        EntityDocumentType.TRUST_DEED: "Trust Deed",
        EntityDocumentType.OPERATING_AGREEMENT: "Operating Agreement",
        EntityDocumentType.BYLAWS: "Bylaws",
        EntityDocumentType.CERTIFICATE_OF_FORMATION: "Certificate of Formation",
        EntityDocumentType.EIN_DOCUMENT: "EIN Document",
        EntityDocumentType.TAX_DOCUMENT: "Tax Document",
        EntityDocumentType.COMPLIANCE_DOCUMENT: "Compliance Document",
        EntityDocumentType.OTHER: "Other"
    }
    return type_map.get(doc_type, doc_type.value.replace("_", " ").title())


def get_action_display(action: AuditAction) -> str:
    """Convert action enum to display name"""
    action_map = {
        AuditAction.ENTITY_CREATED: "Entity Created",
        AuditAction.ENTITY_UPDATED: "Entity Updated",
        AuditAction.ENTITY_DELETED: "Entity Deleted",
        AuditAction.DOCUMENT_UPLOADED: "Document Uploaded",
        AuditAction.DOCUMENT_APPROVED: "Document Approved",
        AuditAction.DOCUMENT_REJECTED: "Document Rejected",
        AuditAction.STATUS_UPDATED: "Status Updated",
        AuditAction.PERSON_ADDED: "Person Added",
        AuditAction.PERSON_REMOVED: "Person Removed",
        AuditAction.PERSON_UPDATED: "Person Updated",
        AuditAction.COMPLIANCE_UPDATED: "Compliance Updated",
        AuditAction.NOTE_ADDED: "Note Added",
        AuditAction.RELATIONSHIP_UPDATED: "Relationship Updated"
    }
    return action_map.get(action, action.value.replace("_", " ").title())


async def create_audit_entry(
    db: AsyncSession,
    entity_id: UUID,
    user_id: UUID,
    action: AuditAction,
    notes: Optional[str] = None,
    document_id: Optional[UUID] = None,
    status: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """Helper function to create audit trail entry"""
    audit_entry = EntityAuditTrail(
        entity_id=entity_id,
        user_id=user_id,
        action=action,
        action_display=get_action_display(action),
        document_id=document_id,
        status=status,
        status_display=status.replace("_", " ").title() if status else None,
        notes=notes,
        metadata=metadata or {}
    )
    db.add(audit_entry)
    return audit_entry


# ==================== ENTITY MANAGEMENT APIs ====================

@router.get("", response_model=Dict[str, Any])
async def list_entities(
    status_filter: Optional[EntityStatus] = Query(None),
    type_filter: Optional[EntityType] = Query(None),
    jurisdiction: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a list of all entities for the current user"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Entity).where(Entity.account_id == account.id)
    
    if status_filter:
        query = query.where(Entity.status == status_filter)
    if type_filter:
        query = query.where(Entity.entity_type == type_filter)
    if jurisdiction:
        query = query.where(Entity.jurisdiction == jurisdiction)
    if search:
        query = query.where(
            or_(
                Entity.name.ilike(f"%{search}%"),
                Entity.registration_number.ilike(f"%{search}%")
            )
        )
    
    # Get total count
    count_query = select(func.count(Entity.id)).where(Entity.account_id == account.id)
    if status_filter:
        count_query = count_query.where(Entity.status == status_filter)
    if type_filter:
        count_query = count_query.where(Entity.entity_type == type_filter)
    if jurisdiction:
        count_query = count_query.where(Entity.jurisdiction == jurisdiction)
    if search:
        count_query = count_query.where(
            or_(
                Entity.name.ilike(f"%{search}%"),
                Entity.registration_number.ilike(f"%{search}%")
            )
        )
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.order_by(desc(Entity.created_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    entities = result.scalars().all()
    
    return {
        "data": [
            {
                "id": str(entity.id),
                "name": entity.name,
                "location": entity.location,
                "registration_number": entity.registration_number,
                "formation_date": entity.formation_date.isoformat() if entity.formation_date else None,
                "status": entity.status.value if entity.status else None,
                "entity_type": entity.entity_type.value if entity.entity_type else None,
                "jurisdiction": entity.jurisdiction,
                "parent_entity_id": str(entity.parent_entity_id) if entity.parent_entity_id else None,
                "created_at": entity.created_at.isoformat() if entity.created_at else None,
                "updated_at": entity.updated_at.isoformat() if entity.updated_at else None
            }
            for entity in entities
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/{entity_id}", response_model=Dict[str, Any])
async def get_entity_details(
    entity_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Entity).options(
            selectinload(Entity.child_entities),
            selectinload(Entity.compliance)
        ).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Get child entities
    child_entities = []
    if entity.child_entities:
        for child in entity.child_entities:
            child_entities.append({
                "id": str(child.id),
                "name": child.name,
                "status": child.status.value if child.status else None
            })
    
    # Get compliance status
    compliance_status = None
    if entity.compliance:
        compliance_status = {
            "kyc_aml_status": entity.compliance.kyc_aml_status.value if entity.compliance.kyc_aml_status else None,
            "registered_agent": entity.compliance.registered_agent,
            "tax_residency": entity.compliance.tax_residency,
            "fatca_crs_compliance": entity.compliance.fatca_crs_compliance.value if entity.compliance.fatca_crs_compliance else None,
            "last_updated": entity.compliance.last_updated.isoformat() if entity.compliance.last_updated else None
        }
    
    return {
        "data": {
            "id": str(entity.id),
            "name": entity.name,
            "location": entity.location,
            "registration_number": entity.registration_number,
            "formation_date": entity.formation_date.isoformat() if entity.formation_date else None,
            "status": entity.status.value if entity.status else None,
            "entity_type": entity.entity_type.value if entity.entity_type else None,
            "jurisdiction": entity.jurisdiction,
            "parent_entity_id": str(entity.parent_entity_id) if entity.parent_entity_id else None,
            "child_entities": child_entities,
            "compliance_status": compliance_status,
            "created_at": entity.created_at.isoformat() if entity.created_at else None,
            "updated_at": entity.updated_at.isoformat() if entity.updated_at else None
        }
    }


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_entity(
    entity_data: EntityCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Validate parent entity if provided
    if entity_data.parent_entity_id:
        parent_result = await db.execute(
            select(Entity).where(
                Entity.id == entity_data.parent_entity_id,
                Entity.account_id == account.id
            )
        )
        parent = parent_result.scalar_one_or_none()
        if not parent:
            raise BadRequestException("Parent entity not found or access denied")
    
    # Parse formation date
    formation_date = None
    if entity_data.formation_date:
        try:
            formation_date = datetime.strptime(entity_data.formation_date, "%Y-%m-%d").date()
        except ValueError:
            raise BadRequestException("Invalid formation_date format. Use YYYY-MM-DD")
    
    entity = Entity(
        account_id=account.id,
        name=entity_data.name,
        entity_type=entity_data.entity_type,
        jurisdiction=entity_data.jurisdiction,
        location=entity_data.location,
        registration_number=entity_data.registration_number,
        formation_date=formation_date,
        parent_entity_id=entity_data.parent_entity_id,
        description=entity_data.description,
        status=EntityStatus.PENDING
    )
    
    db.add(entity)
    await db.flush()
    
    # Create compliance record
    compliance = EntityCompliance(entity_id=entity.id)
    db.add(compliance)
    
    # Create audit entry
    await create_audit_entry(
        db=db,
        entity_id=entity.id,
        user_id=current_user.id,
        action=AuditAction.ENTITY_CREATED,
        notes=f"Entity '{entity.name}' created"
    )
    
    await db.commit()
    await db.refresh(entity)
    
    logger.info(f"Entity created: {entity.id}")
    
    return {
        "data": {
            "id": str(entity.id),
            "name": entity.name,
            "status": entity.status.value,
            "created_at": entity.created_at.isoformat() if entity.created_at else None
        },
        "message": "Entity created successfully"
    }


@router.put("/{entity_id}", response_model=Dict[str, Any])
async def update_entity(
    entity_id: UUID,
    entity_data: EntityUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update entity information"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Track changes for audit
    changes = []
    if entity_data.name and entity_data.name != entity.name:
        changes.append(f"name: {entity.name} -> {entity_data.name}")
        entity.name = entity_data.name
    if entity_data.location and entity_data.location != entity.location:
        changes.append(f"location: {entity.location} -> {entity_data.location}")
        entity.location = entity_data.location
    if entity_data.status and entity_data.status != entity.status:
        changes.append(f"status: {entity.status.value} -> {entity_data.status.value}")
        entity.status = entity_data.status
    if entity_data.description is not None:
        entity.description = entity_data.description
    
    await db.flush()
    
    # Create audit entry
    if changes:
        await create_audit_entry(
            db=db,
            entity_id=entity.id,
            user_id=current_user.id,
            action=AuditAction.ENTITY_UPDATED,
            notes=f"Updated: {', '.join(changes)}"
        )
    
    await db.commit()
    await db.refresh(entity)
    
    logger.info(f"Entity updated: {entity_id}")
    
    return {
        "data": {
            "id": str(entity.id),
            "name": entity.name,
            "updated_at": entity.updated_at.isoformat() if entity.updated_at else None
        },
        "message": "Entity updated successfully"
    }


@router.delete("/{entity_id}", status_code=status.HTTP_200_OK)
async def delete_entity(
    entity_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an entity (soft delete by setting status to dissolved)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Check for child entities
    child_result = await db.execute(
        select(func.count(Entity.id)).where(Entity.parent_entity_id == entity_id)
    )
    child_count = child_result.scalar() or 0
    
    if child_count > 0:
        raise BadRequestException(f"Cannot delete entity with {child_count} child entity/entities. Please remove or reassign child entities first.")
    
    # Soft delete by setting status to dissolved
    entity.status = EntityStatus.DISSOLVED
    
    await db.flush()
    
    # Create audit entry
    await create_audit_entry(
        db=db,
        entity_id=entity.id,
        user_id=current_user.id,
        action=AuditAction.ENTITY_DELETED,
        notes=f"Entity '{entity.name}' deleted (dissolved)"
    )
    
    await db.commit()
    
    logger.info(f"Entity deleted: {entity_id}")
    
    return {
        "message": "Entity deleted successfully"
    }


# ==================== ENTITY TYPES APIs ====================

@router.get("/types", response_model=Dict[str, Any])
async def list_entity_types(
    jurisdiction: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of available entity types with their details"""
    # Static entity types data
    entity_types = [
        {
            "type": "LLC",
            "full_name": "Limited Liability Company",
            "jurisdiction": "State",
            "formation_rates": "LLC",
            "description": "A flexible business structure that combines the pass-through taxation of a partnership or sole proprietorship with the limited liability of a corporation.",
            "available_jurisdictions": ["Delaware", "Wyoming", "Nevada", "Florida", "Texas"]
        },
        {
            "type": "Corporation",
            "full_name": "Corporation (C-Corp)",
            "jurisdiction": "State",
            "formation_rates": "Corporation",
            "description": "A separate legal entity that is owned by shareholders. Provides limited liability protection and can issue stock.",
            "available_jurisdictions": ["Delaware", "Nevada", "Wyoming"]
        },
        {
            "type": "Trust",
            "full_name": "Trust",
            "jurisdiction": "State",
            "formation_rates": "Trust",
            "description": "A fiduciary relationship in which one party holds legal title to property for the benefit of another party.",
            "available_jurisdictions": ["Delaware", "Nevada", "South Dakota"]
        },
        {
            "type": "Partnership",
            "full_name": "Partnership",
            "jurisdiction": "State",
            "formation_rates": "Partnership",
            "description": "A business structure in which two or more individuals manage and operate a business in accordance with the terms and objectives set out in a Partnership Deed.",
            "available_jurisdictions": ["Delaware", "Nevada"]
        },
        {
            "type": "Foundation",
            "full_name": "Foundation",
            "jurisdiction": "State",
            "formation_rates": "Foundation",
            "description": "A legal entity that is established to support charitable, educational, or other public benefit purposes.",
            "available_jurisdictions": ["Delaware", "Nevada"]
        }
    ]
    
    # Filter by jurisdiction if provided
    if jurisdiction:
        entity_types = [
            et for et in entity_types
            if jurisdiction in et.get("available_jurisdictions", [])
        ]
    
    return {
        "data": entity_types
    }


@router.get("/types/{type_id}", response_model=Dict[str, Any])
async def get_entity_type_details(
    type_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific entity type"""
    # Static entity type details
    type_details = {
        "LLC": {
            "type": "LLC",
            "full_name": "Limited Liability Company",
            "jurisdiction": "State",
            "formation_rates": "LLC",
            "requirements": ["Articles of Organization", "Operating Agreement", "EIN"],
            "tax_implications": "Pass-through taxation (default) or can elect to be taxed as a corporation",
            "liability": "Limited liability protection for members"
        },
        "Corporation": {
            "type": "Corporation",
            "full_name": "Corporation (C-Corp)",
            "jurisdiction": "State",
            "formation_rates": "Corporation",
            "requirements": ["Articles of Incorporation", "Bylaws", "EIN", "Stock Certificates"],
            "tax_implications": "Double taxation (corporate tax and shareholder dividends)",
            "liability": "Limited liability protection for shareholders"
        },
        "Trust": {
            "type": "Trust",
            "full_name": "Trust",
            "jurisdiction": "State",
            "formation_rates": "Trust",
            "requirements": ["Trust Deed", "Trust Agreement", "EIN"],
            "tax_implications": "Pass-through taxation",
            "liability": "Limited liability for trustees"
        }
    }
    
    details = type_details.get(type_id)
    if not details:
        raise NotFoundException("Entity Type", type_id)
    
    return {
        "data": details
    }


# ==================== ENTITY HIERARCHY APIs ====================

@router.get("/{entity_id}/hierarchy", response_model=Dict[str, Any])
async def get_entity_hierarchy(
    entity_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the complete hierarchy structure of an entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Entity).options(
            selectinload(Entity.parent_entity),
            selectinload(Entity.child_entities)
        ).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Build parent
    parent = None
    if entity.parent_entity:
        parent = {
            "id": str(entity.parent_entity.id),
            "name": entity.parent_entity.name,
            "status": entity.parent_entity.status.value if entity.parent_entity.status else None
        }
    
    # Build current
    current = {
        "id": str(entity.id),
        "name": entity.name,
        "status": entity.status.value if entity.status else None
    }
    
    # Build children recursively
    def build_child_tree(child_entity: Entity) -> Dict[str, Any]:
        return {
            "id": str(child_entity.id),
            "name": child_entity.name,
            "status": child_entity.status.value if child_entity.status else None,
            "children": [build_child_tree(c) for c in child_entity.child_entities] if child_entity.child_entities else []
        }
    
    children = []
    if entity.child_entities:
        for child in entity.child_entities:
            # Load child's children
            child_result = await db.execute(
                select(Entity).options(
                    selectinload(Entity.child_entities)
                ).where(Entity.id == child.id)
            )
            full_child = child_result.scalar_one_or_none()
            if full_child:
                children.append(build_child_tree(full_child))
    
    return {
        "data": {
            "parent": parent,
            "current": current,
            "children": children
        }
    }


@router.post("/{entity_id}/children", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def add_child_entity(
    entity_id: UUID,
    entity_data: EntityCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a child entity to the current entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify parent entity exists and belongs to account
    parent_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    parent = parent_result.scalar_one_or_none()
    
    if not parent:
        raise NotFoundException("Entity", str(entity_id))
    
    # Parse formation date
    formation_date = None
    if entity_data.formation_date:
        try:
            formation_date = datetime.strptime(entity_data.formation_date, "%Y-%m-%d").date()
        except ValueError:
            raise BadRequestException("Invalid formation_date format. Use YYYY-MM-DD")
    
    # Create child entity
    child_entity = Entity(
        account_id=account.id,
        name=entity_data.name,
        entity_type=entity_data.entity_type,
        jurisdiction=entity_data.jurisdiction,
        location=entity_data.location,
        registration_number=entity_data.registration_number,
        formation_date=formation_date,
        parent_entity_id=entity_id,  # Set parent
        description=entity_data.description,
        status=EntityStatus.PENDING
    )
    
    db.add(child_entity)
    await db.flush()
    
    # Create compliance record
    compliance = EntityCompliance(entity_id=child_entity.id)
    db.add(compliance)
    
    # Create audit entries
    await create_audit_entry(
        db=db,
        entity_id=child_entity.id,
        user_id=current_user.id,
        action=AuditAction.ENTITY_CREATED,
        notes=f"Child entity '{child_entity.name}' created under '{parent.name}'"
    )
    
    await create_audit_entry(
        db=db,
        entity_id=entity_id,
        user_id=current_user.id,
        action=AuditAction.RELATIONSHIP_UPDATED,
        notes=f"Child entity '{child_entity.name}' added"
    )
    
    await db.commit()
    await db.refresh(child_entity)
    
    logger.info(f"Child entity created: {child_entity.id} under {entity_id}")
    
    return {
        "data": {
            "id": str(child_entity.id),
            "name": child_entity.name,
            "parent_entity_id": str(entity_id),
            "created_at": child_entity.created_at.isoformat() if child_entity.created_at else None
        },
        "message": "Child entity added successfully"
    }


@router.patch("/{entity_id}/parent", response_model=Dict[str, Any])
async def update_entity_relationship(
    entity_id: UUID,
    parent_entity_id: UUID = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update the parent entity relationship"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get entity
    result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Validate new parent
    if parent_entity_id:
        parent_result = await db.execute(
            select(Entity).where(
                Entity.id == parent_entity_id,
                Entity.account_id == account.id
            )
        )
        new_parent = parent_result.scalar_one_or_none()
        if not new_parent:
            raise BadRequestException("Parent entity not found or access denied")
        
        # Check for circular reference
        if parent_entity_id == entity_id:
            raise BadRequestException("Entity cannot be its own parent")
        
        # Simple check: if new parent is a child of this entity, it's circular
        child_result = await db.execute(
            select(Entity).where(Entity.parent_entity_id == entity_id)
        )
        children = child_result.scalars().all()
        child_ids = [c.id for c in children]
        if parent_entity_id in child_ids:
            raise BadRequestException("Cannot set parent: would create circular reference")
        
        # Check if new parent is a descendant (would create circular reference)
        # Get all descendants of current entity
        all_descendants = set(child_ids)
        checked = set()
        to_check = list(child_ids)
        
        while to_check:
            current_id = to_check.pop()
            if current_id in checked:
                continue
            checked.add(current_id)
            
            if current_id == parent_entity_id:
                raise BadRequestException("Cannot set parent: would create circular reference")
            
            # Get children of current entity
            desc_result = await db.execute(
                select(Entity).where(Entity.parent_entity_id == current_id)
            )
            descendants = desc_result.scalars().all()
            for desc in descendants:
                if desc.id not in checked:
                    all_descendants.add(desc.id)
                    to_check.append(desc.id)
        
        if parent_entity_id in all_descendants:
            raise BadRequestException("Cannot set parent: would create circular reference")
    
    old_parent_id = entity.parent_entity_id
    entity.parent_entity_id = parent_entity_id
    
    await db.flush()
    
    # Create audit entry
    old_parent_name = "None"
    if old_parent_id:
        old_parent_result = await db.execute(
            select(Entity).where(Entity.id == old_parent_id)
        )
        old_parent = old_parent_result.scalar_one_or_none()
        if old_parent:
            old_parent_name = old_parent.name
    
    new_parent_name = "None"
    if parent_entity_id:
        new_parent_result = await db.execute(
            select(Entity).where(Entity.id == parent_entity_id)
        )
        new_parent = new_parent_result.scalar_one_or_none()
        if new_parent:
            new_parent_name = new_parent.name
    
    await create_audit_entry(
        db=db,
        entity_id=entity.id,
        user_id=current_user.id,
        action=AuditAction.RELATIONSHIP_UPDATED,
        notes=f"Parent changed from '{old_parent_name}' to '{new_parent_name}'"
    )
    
    await db.commit()
    await db.refresh(entity)
    
    logger.info(f"Entity relationship updated: {entity_id}")
    
    return {
        "data": {
            "id": str(entity.id),
            "parent_entity_id": str(entity.parent_entity_id) if entity.parent_entity_id else None,
            "updated_at": entity.updated_at.isoformat() if entity.updated_at else None
        },
        "message": "Entity relationship updated successfully"
    }


# ==================== COMPLIANCE APIs ====================

@router.get("/{entity_id}/compliance", response_model=Dict[str, Any])
async def get_compliance_status(
    entity_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get compliance status for an entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Get or create compliance record
    compliance_result = await db.execute(
        select(EntityCompliance).where(EntityCompliance.entity_id == entity_id)
    )
    compliance = compliance_result.scalar_one_or_none()
    
    if not compliance:
        compliance = EntityCompliance(entity_id=entity_id)
        db.add(compliance)
        await db.commit()
        await db.refresh(compliance)
    
    return {
        "data": {
            "kyc_aml_status": compliance.kyc_aml_status.value if compliance.kyc_aml_status else None,
            "registered_agent": compliance.registered_agent,
            "tax_residency": compliance.tax_residency,
            "fatca_crs_compliance": compliance.fatca_crs_compliance.value if compliance.fatca_crs_compliance else None,
            "last_updated": compliance.last_updated.isoformat() if compliance.last_updated else None
        }
    }


@router.patch("/{entity_id}/compliance", response_model=Dict[str, Any])
async def update_compliance_status(
    entity_id: UUID,
    compliance_data: ComplianceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update compliance status for an entity"""
    # Check permissions - only admins and compliance officers
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied. Compliance updates require admin or compliance officer permissions.")
    
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Get or create compliance record
    compliance_result = await db.execute(
        select(EntityCompliance).where(EntityCompliance.entity_id == entity_id)
    )
    compliance = compliance_result.scalar_one_or_none()
    
    if not compliance:
        compliance = EntityCompliance(entity_id=entity_id)
        db.add(compliance)
    
    # Track changes
    changes = []
    if compliance_data.kyc_aml_status and compliance_data.kyc_aml_status != compliance.kyc_aml_status:
        changes.append(f"KYC/AML: {compliance.kyc_aml_status.value if compliance.kyc_aml_status else 'None'} -> {compliance_data.kyc_aml_status.value}")
        compliance.kyc_aml_status = compliance_data.kyc_aml_status
    if compliance_data.registered_agent is not None:
        compliance.registered_agent = compliance_data.registered_agent
    if compliance_data.tax_residency is not None:
        compliance.tax_residency = compliance_data.tax_residency
    if compliance_data.fatca_crs_compliance and compliance_data.fatca_crs_compliance != compliance.fatca_crs_compliance:
        changes.append(f"FATCA/CRS: {compliance.fatca_crs_compliance.value if compliance.fatca_crs_compliance else 'None'} -> {compliance_data.fatca_crs_compliance.value}")
        compliance.fatca_crs_compliance = compliance_data.fatca_crs_compliance
    
    compliance.last_updated = datetime.now(timezone.utc)
    
    await db.flush()
    
    # Create audit entry
    if changes:
        await create_audit_entry(
            db=db,
            entity_id=entity.id,
            user_id=current_user.id,
            action=AuditAction.COMPLIANCE_UPDATED,
            notes=f"Compliance updated: {', '.join(changes)}"
        )
    
    await db.commit()
    await db.refresh(compliance)
    
    logger.info(f"Compliance updated for entity: {entity_id}")
    
    return {
        "data": {
            "kyc_aml_status": compliance.kyc_aml_status.value if compliance.kyc_aml_status else None,
            "fatca_crs_compliance": compliance.fatca_crs_compliance.value if compliance.fatca_crs_compliance else None,
            "updated_at": compliance.updated_at.isoformat() if compliance.updated_at else None
        },
        "message": "Compliance status updated successfully"
    }


@router.get("/{entity_id}/compliance-package")
async def download_compliance_package(
    entity_id: UUID,
    format: str = Query("zip", regex="^(zip|pdf)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Download a zip file containing all compliance documents for an entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Get all approved documents
    documents_result = await db.execute(
        select(EntityDocument).where(
            EntityDocument.entity_id == entity_id,
            EntityDocument.status == DocumentStatus.APPROVED
        )
    )
    documents = documents_result.scalars().all()
    
    if not documents:
        raise BadRequestException("No approved documents found for this entity")
    
    if format == "zip":
        # Create ZIP file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for doc in documents:
                try:
                    # Download file from Supabase
                    if doc.supabase_storage_path:
                        file_data = SupabaseClient.get_client().storage.from_("documents").download(doc.supabase_storage_path)
                        zip_file.writestr(doc.name, file_data)
                except Exception as e:
                    logger.error(f"Failed to add document {doc.id} to zip: {e}")
                    continue
        
        zip_buffer.seek(0)
        
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            io.BytesIO(zip_buffer.read()),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="compliance_package_{entity_id}.zip"'}
        )
    else:
        # PDF generation not implemented yet
        raise BadRequestException("PDF format not yet implemented. Please use 'zip' format.")


# ==================== PEOPLE & ROLES APIs ====================

@router.get("/{entity_id}/people", response_model=Dict[str, Any])
async def list_people_roles(
    entity_id: UUID,
    role_filter: Optional[EntityRole] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of people associated with an entity and their roles"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    query = select(EntityPerson).where(EntityPerson.entity_id == entity_id)
    if role_filter:
        query = query.where(EntityPerson.role == role_filter)
    
    result = await db.execute(query.order_by(EntityPerson.added_at.desc()))
    people = result.scalars().all()
    
    return {
        "data": [
            {
                "id": str(person.id),
                "name": person.name,
                "role": person.role.value if person.role else None,
                "role_display": get_role_display(person.role) if person.role else None,
                "email": person.email,
                "phone": person.phone,
                "added_at": person.added_at.isoformat() if person.added_at else None
            }
            for person in people
        ]
    }


@router.post("/{entity_id}/people", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def add_person_to_entity(
    entity_id: UUID,
    person_data: PersonCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a person to an entity with a specific role"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Verify user exists if user_id provided
    if person_data.user_id:
        user_result = await db.execute(
            select(User).where(User.id == person_data.user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User", str(person_data.user_id))
    
    person = EntityPerson(
        entity_id=entity_id,
        user_id=person_data.user_id,
        name=person_data.name,
        role=person_data.role,
        email=person_data.email,
        phone=person_data.phone,
        notes=person_data.notes
    )
    
    db.add(person)
    await db.flush()
    
    # Create audit entry
    await create_audit_entry(
        db=db,
        entity_id=entity_id,
        user_id=current_user.id,
        action=AuditAction.PERSON_ADDED,
        notes=f"Person '{person_data.name}' added with role '{get_role_display(person_data.role)}'"
    )
    
    await db.commit()
    await db.refresh(person)
    
    logger.info(f"Person added to entity {entity_id}: {person.id}")
    
    return {
        "data": {
            "id": str(person.id),
            "name": person.name,
            "role": person.role.value if person.role else None,
            "role_display": get_role_display(person.role) if person.role else None,
            "added_at": person.added_at.isoformat() if person.added_at else None
        },
        "message": "Person added successfully"
    }


@router.patch("/{entity_id}/people/{person_id}", response_model=Dict[str, Any])
async def update_person_role(
    entity_id: UUID,
    person_id: UUID,
    person_data: PersonUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a person's role or information"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Get person
    result = await db.execute(
        select(EntityPerson).where(
            EntityPerson.id == person_id,
            EntityPerson.entity_id == entity_id
        )
    )
    person = result.scalar_one_or_none()
    
    if not person:
        raise NotFoundException("Person", str(person_id))
    
    # Track changes
    changes = []
    if person_data.role and person_data.role != person.role:
        changes.append(f"role: {get_role_display(person.role)} -> {get_role_display(person_data.role)}")
        person.role = person_data.role
    if person_data.name and person_data.name != person.name:
        changes.append(f"name: {person.name} -> {person_data.name}")
        person.name = person_data.name
    if person_data.email is not None:
        person.email = person_data.email
    if person_data.phone is not None:
        person.phone = person_data.phone
    if person_data.notes is not None:
        person.notes = person_data.notes
    
    await db.flush()
    
    # Create audit entry
    if changes:
        await create_audit_entry(
            db=db,
            entity_id=entity_id,
            user_id=current_user.id,
            action=AuditAction.PERSON_UPDATED,
            notes=f"Person '{person.name}' updated: {', '.join(changes)}"
        )
    
    await db.commit()
    await db.refresh(person)
    
    logger.info(f"Person updated: {person_id}")
    
    return {
        "data": {
            "id": str(person.id),
            "name": person.name,
            "role": person.role.value if person.role else None,
            "updated_at": person.updated_at.isoformat() if person.updated_at else None
        },
        "message": "Person updated successfully"
    }


@router.delete("/{entity_id}/people/{person_id}", status_code=status.HTTP_200_OK)
async def remove_person_from_entity(
    entity_id: UUID,
    person_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove a person from an entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Get person
    result = await db.execute(
        select(EntityPerson).where(
            EntityPerson.id == person_id,
            EntityPerson.entity_id == entity_id
        )
    )
    person = result.scalar_one_or_none()
    
    if not person:
        raise NotFoundException("Person", str(person_id))
    
    person_name = person.name
    person_role = get_role_display(person.role) if person.role else None
    
    await db.delete(person)
    await db.flush()
    
    # Create audit entry
    await create_audit_entry(
        db=db,
        entity_id=entity_id,
        user_id=current_user.id,
        action=AuditAction.PERSON_REMOVED,
        notes=f"Person '{person_name}' ({person_role}) removed from entity"
    )
    
    await db.commit()
    
    logger.info(f"Person removed from entity {entity_id}: {person_id}")
    
    return {
        "message": "Person removed successfully"
    }


# ==================== AUDIT TRAIL APIs ====================

@router.get("/{entity_id}/audit-trail", response_model=Dict[str, Any])
async def get_audit_trail(
    entity_id: UUID,
    action: Optional[str] = Query(None),
    user: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get audit trail entries for an entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    query = select(EntityAuditTrail).options(
        selectinload(EntityAuditTrail.user),
        selectinload(EntityAuditTrail.document)
    ).where(EntityAuditTrail.entity_id == entity_id)
    
    if action:
        try:
            action_enum = AuditAction(action)
            query = query.where(EntityAuditTrail.action == action_enum)
        except ValueError:
            pass
    
    if user:
        # Search by user name or email
        user_query = select(User).where(
            or_(
                User.email.ilike(f"%{user}%"),
                User.full_name.ilike(f"%{user}%") if hasattr(User, 'full_name') else False
            )
        )
        user_result = await db.execute(user_query)
        users = user_result.scalars().all()
        if users:
            user_ids = [u.id for u in users]
            query = query.where(EntityAuditTrail.user_id.in_(user_ids))
    
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            query = query.where(EntityAuditTrail.timestamp >= date_from_dt)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            query = query.where(EntityAuditTrail.timestamp <= date_to_dt)
        except ValueError:
            pass
    
    # Get total count
    count_query = select(func.count(EntityAuditTrail.id)).where(EntityAuditTrail.entity_id == entity_id)
    if action:
        try:
            action_enum = AuditAction(action)
            count_query = count_query.where(EntityAuditTrail.action == action_enum)
        except ValueError:
            pass
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.order_by(desc(EntityAuditTrail.timestamp)).offset(offset).limit(limit)
    result = await db.execute(query)
    audit_entries = result.scalars().all()
    
    audit_list = []
    for entry in audit_entries:
        user_name = None
        user_role = None
        if entry.user:
            user_name = entry.user.email
            if hasattr(entry.user, 'role'):
                user_role = entry.user.role.value if entry.user.role else None
        
        document_name = None
        if entry.document:
            document_name = entry.document.name
        
        audit_list.append({
            "id": str(entry.id),
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "user": user_name,
            "user_id": str(entry.user_id) if entry.user_id else None,
            "role": user_role or "User",
            "action": entry.action.value if entry.action else None,
            "action_display": entry.action_display,
            "document": document_name,
            "document_id": str(entry.document_id) if entry.document_id else None,
            "status": entry.status,
            "status_display": entry.status_display,
            "notes": entry.notes,
            "metadata": entry.meta_data or {}
        })
    
    return {
        "data": audit_list,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.post("/{entity_id}/audit-trail", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def add_audit_trail_entry(
    entity_id: UUID,
    audit_data: AuditTrailCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a new audit trail entry (note or comment)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Verify document exists if provided
    if audit_data.document_id:
        doc_result = await db.execute(
            select(EntityDocument).where(
                EntityDocument.id == audit_data.document_id,
                EntityDocument.entity_id == entity_id
            )
        )
        doc = doc_result.scalar_one_or_none()
        if not doc:
            raise NotFoundException("Document", str(audit_data.document_id))
    
    audit_entry = EntityAuditTrail(
        entity_id=entity_id,
        user_id=current_user.id,
        action=audit_data.action,
        action_display=get_action_display(audit_data.action),
        document_id=audit_data.document_id,
        notes=audit_data.notes,
        meta_data=audit_data.metadata or {}
    )
    
    db.add(audit_entry)
    await db.commit()
    await db.refresh(audit_entry)
    
    logger.info(f"Audit trail entry added for entity {entity_id}: {audit_entry.id}")
    
    return {
        "data": {
            "id": str(audit_entry.id),
            "timestamp": audit_entry.timestamp.isoformat() if audit_entry.timestamp else None,
            "user": current_user.email,
            "action": audit_entry.action.value if audit_entry.action else None,
            "notes": audit_entry.notes,
            "created_at": audit_entry.created_at.isoformat() if audit_entry.created_at else None
        },
        "message": "Audit trail entry added successfully"
    }


@router.patch("/{entity_id}/audit-trail/{entry_id}", response_model=Dict[str, Any])
async def update_audit_trail_entry(
    entity_id: UUID,
    entry_id: UUID,
    audit_data: AuditTrailUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update an audit trail entry (e.g., edit note)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Get audit entry
    result = await db.execute(
        select(EntityAuditTrail).where(
            EntityAuditTrail.id == entry_id,
            EntityAuditTrail.entity_id == entity_id
        )
    )
    audit_entry = result.scalar_one_or_none()
    
    if not audit_entry:
        raise NotFoundException("Audit Trail Entry", str(entry_id))
    
    # Only allow updating notes for note_added actions
    if audit_entry.action != AuditAction.NOTE_ADDED:
        raise BadRequestException("Only notes can be updated. Action history is immutable.")
    
    if audit_data.notes is not None:
        audit_entry.notes = audit_data.notes
    
    await db.commit()
    await db.refresh(audit_entry)
    
    logger.info(f"Audit trail entry updated: {entry_id}")
    
    return {
        "data": {
            "id": str(audit_entry.id),
            "notes": audit_entry.notes,
            "updated_at": audit_entry.timestamp.isoformat() if audit_entry.timestamp else None
        },
        "message": "Audit trail entry updated successfully"
    }


@router.delete("/{entity_id}/audit-trail/{entry_id}", status_code=status.HTTP_200_OK)
async def delete_audit_trail_entry(
    entity_id: UUID,
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an audit trail entry"""
    # Check permissions - only admins can delete audit entries
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied. Only admins can delete audit trail entries.")
    
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Get audit entry
    result = await db.execute(
        select(EntityAuditTrail).where(
            EntityAuditTrail.id == entry_id,
            EntityAuditTrail.entity_id == entity_id
        )
    )
    audit_entry = result.scalar_one_or_none()
    
    if not audit_entry:
        raise NotFoundException("Audit Trail Entry", str(entry_id))
    
    await db.delete(audit_entry)
    await db.commit()
    
    logger.info(f"Audit trail entry deleted: {entry_id}")
    
    return {
        "message": "Audit trail entry deleted successfully"
    }


# ==================== DOCUMENT MANAGEMENT APIs ====================

@router.get("/{entity_id}/documents", response_model=Dict[str, Any])
async def list_entity_documents(
    entity_id: UUID,
    document_type: Optional[EntityDocumentType] = Query(None),
    status_filter: Optional[DocumentStatus] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of documents associated with an entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    query = select(EntityDocument).options(
        selectinload(EntityDocument.uploaded_by_user),
        selectinload(EntityDocument.approved_by_user)
    ).where(EntityDocument.entity_id == entity_id)
    
    if document_type:
        query = query.where(EntityDocument.document_type == document_type)
    if status_filter:
        query = query.where(EntityDocument.status == status_filter)
    
    # Get total count
    count_query = select(func.count(EntityDocument.id)).where(EntityDocument.entity_id == entity_id)
    if document_type:
        count_query = count_query.where(EntityDocument.document_type == document_type)
    if status_filter:
        count_query = count_query.where(EntityDocument.status == status_filter)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.order_by(desc(EntityDocument.uploaded_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    documents = result.scalars().all()
    
    document_list = []
    for doc in documents:
        uploaded_by_name = None
        if doc.uploaded_by_user:
            uploaded_by_name = doc.uploaded_by_user.email
        
        document_list.append({
            "id": str(doc.id),
            "name": doc.name,
            "type": doc.document_type.value if doc.document_type else None,
            "type_display": get_document_type_display(doc.document_type) if doc.document_type else None,
            "status": doc.status.value if doc.status else None,
            "status_display": doc.status.value.replace("_", " ").title() if doc.status else None,
            "file_url": doc.file_url,
            "file_size": doc.file_size,
            "uploaded_by": uploaded_by_name,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            "approved_at": doc.approved_at.isoformat() if doc.approved_at else None
        })
    
    return {
        "data": document_list,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.post("/{entity_id}/documents", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def upload_entity_document(
    entity_id: UUID,
    file: UploadFile = File(...),
    document_type: EntityDocumentType = Form(...),
    description: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload a document for an entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    # Validate file type
    file_extension = file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if file_extension not in settings.ALLOWED_FILE_TYPES:
        raise BadRequestException(f"File type not allowed. Allowed types: {settings.ALLOWED_FILE_TYPES}")
    
    # Read file
    file_data = await file.read()
    file_size = len(file_data)
    
    # Check file size
    if file_size > settings.MAX_UPLOAD_SIZE:
        raise BadRequestException(f"File size exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE} bytes")
    
    # Upload to Supabase Storage
    try:
        file_path = f"entities/{entity_id}/{file.filename}"
        SupabaseClient.upload_file(
            bucket="documents",
            file_path=file_path,
            file_data=file_data,
            content_type=file.content_type or "application/octet-stream"
        )
        
        # Get public URL
        file_url = SupabaseClient.get_file_url("documents", file_path)
    except Exception as e:
        logger.error(f"Failed to upload document to Supabase: {e}")
        raise BadRequestException("Failed to upload document")
    
    # Create document record
    document = EntityDocument(
        entity_id=entity_id,
        name=file.filename,
        document_type=document_type,
        status=DocumentStatus.PENDING,
        file_path=file_path,
        file_url=file_url,
        supabase_storage_path=file_path,
        file_size=file_size,
        mime_type=file.content_type,
        uploaded_by=current_user.id,
        description=description,
        notes=notes
    )
    
    db.add(document)
    await db.flush()
    
    # Create audit entry
    await create_audit_entry(
        db=db,
        entity_id=entity_id,
        user_id=current_user.id,
        action=AuditAction.DOCUMENT_UPLOADED,
        document_id=document.id,
        notes=f"Document '{file.filename}' uploaded",
        metadata={"document_type": document_type.value}
    )
    
    await db.commit()
    await db.refresh(document)
    
    logger.info(f"Entity document uploaded: {document.id}")
    
    return {
        "data": {
            "id": str(document.id),
            "name": document.name,
            "type": document.document_type.value if document.document_type else None,
            "status": document.status.value if document.status else None,
            "uploaded_at": document.uploaded_at.isoformat() if document.uploaded_at else None
        },
        "message": "Document uploaded successfully"
    }


@router.get("/{entity_id}/documents/{document_id}", response_model=Dict[str, Any])
async def get_document_details(
    entity_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific document"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    result = await db.execute(
        select(EntityDocument).options(
            selectinload(EntityDocument.uploaded_by_user),
            selectinload(EntityDocument.approved_by_user)
        ).where(
            EntityDocument.id == document_id,
            EntityDocument.entity_id == entity_id
        )
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    uploaded_by_name = None
    if document.uploaded_by_user:
        uploaded_by_name = document.uploaded_by_user.email
    
    approved_by_name = None
    if document.approved_by_user:
        approved_by_name = document.approved_by_user.email
    
    return {
        "data": {
            "id": str(document.id),
            "name": document.name,
            "type": document.document_type.value if document.document_type else None,
            "status": document.status.value if document.status else None,
            "file_url": document.file_url,
            "file_size": document.file_size,
            "mime_type": document.mime_type,
            "uploaded_by": uploaded_by_name,
            "uploaded_at": document.uploaded_at.isoformat() if document.uploaded_at else None,
            "approved_by": approved_by_name,
            "approved_at": document.approved_at.isoformat() if document.approved_at else None,
            "description": document.description,
            "notes": document.notes
        }
    }


@router.get("/{entity_id}/documents/{document_id}/download")
async def download_document(
    entity_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Download a document file"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    result = await db.execute(
        select(EntityDocument).where(
            EntityDocument.id == document_id,
            EntityDocument.entity_id == entity_id
        )
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    try:
        # Get file from Supabase Storage
        file_data = SupabaseClient.get_client().storage.from_("documents").download(document.supabase_storage_path)
        
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            io.BytesIO(file_data),
            media_type=document.mime_type or "application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{document.name}"'}
        )
    except Exception as e:
        logger.error(f"Failed to download document: {e}")
        raise BadRequestException("Failed to download document")


@router.patch("/{entity_id}/documents/{document_id}/status", response_model=Dict[str, Any])
async def update_document_status(
    entity_id: UUID,
    document_id: UUID,
    status_data: DocumentStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update document status (approve, reject, etc.)"""
    # Check permissions - only admins and compliance officers
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied. Document approval requires admin or compliance officer permissions.")
    
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    result = await db.execute(
        select(EntityDocument).where(
            EntityDocument.id == document_id,
            EntityDocument.entity_id == entity_id
        )
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    old_status = document.status.value if document.status else None
    document.status = status_data.status
    
    if status_data.status == DocumentStatus.APPROVED:
        document.approved_by = current_user.id
        document.approved_at = datetime.now(timezone.utc)
    
    if status_data.notes:
        existing_notes = document.notes or ""
        document.notes = f"{existing_notes}\n[{datetime.now(timezone.utc).isoformat()}] {status_data.notes}".strip()
    
    await db.flush()
    
    # Create audit entry
    action = AuditAction.DOCUMENT_APPROVED if status_data.status == DocumentStatus.APPROVED else AuditAction.DOCUMENT_REJECTED
    await create_audit_entry(
        db=db,
        entity_id=entity_id,
        user_id=current_user.id,
        action=action,
        document_id=document.id,
        status=status_data.status.value,
        notes=status_data.notes or f"Document status changed from {old_status} to {status_data.status.value}"
    )
    
    await db.commit()
    await db.refresh(document)
    
    logger.info(f"Document status updated: {document_id} -> {status_data.status.value}")
    
    return {
        "data": {
            "id": str(document.id),
            "status": document.status.value if document.status else None,
            "approved_at": document.approved_at.isoformat() if document.approved_at else None,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None
        },
        "message": "Document status updated successfully"
    }


@router.delete("/{entity_id}/documents/{document_id}", status_code=status.HTTP_200_OK)
async def delete_document(
    entity_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a document from an entity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify entity belongs to account
    entity_result = await db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.account_id == account.id
        )
    )
    entity = entity_result.scalar_one_or_none()
    
    if not entity:
        raise NotFoundException("Entity", str(entity_id))
    
    result = await db.execute(
        select(EntityDocument).where(
            EntityDocument.id == document_id,
            EntityDocument.entity_id == entity_id
        )
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    # Delete from Supabase Storage
    try:
        if document.supabase_storage_path:
            SupabaseClient.delete_file("documents", document.supabase_storage_path)
    except Exception as e:
        logger.error(f"Failed to delete document from storage: {e}")
    
    await db.delete(document)
    await db.commit()
    
    logger.info(f"Entity document deleted: {document_id}")
    
    return {
        "message": "Document deleted successfully"
    }
