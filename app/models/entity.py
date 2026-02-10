from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean, Date, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class EntityType(str, Enum):
    LLC = "LLC"
    CORPORATION = "Corporation"
    TRUST = "Trust"
    PARTNERSHIP = "Partnership"
    FOUNDATION = "Foundation"
    OTHER = "Other"


class EntityStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    SUSPENDED = "suspended"
    DISSOLVED = "dissolved"


class EntityRole(str, Enum):
    TRUSTEE = "trustee"
    SIGNATORY = "signatory"
    POWER_OF_ATTORNEY = "power_of_attorney"
    DIRECTOR = "director"
    OFFICER = "officer"
    MEMBER = "member"
    MANAGER = "manager"
    BENEFICIARY = "beneficiary"
    OTHER = "other"


class EntityDocumentType(str, Enum):
    ARTICLES_OF_INCORPORATION = "articles_of_incorporation"
    TRUST_DEED = "trust_deed"
    OPERATING_AGREEMENT = "operating_agreement"
    BYLAWS = "bylaws"
    CERTIFICATE_OF_FORMATION = "certificate_of_formation"
    EIN_DOCUMENT = "ein_document"
    TAX_DOCUMENT = "tax_document"
    COMPLIANCE_DOCUMENT = "compliance_document"
    OTHER = "other"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ComplianceStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    NOT_COMPLIANT = "not_compliant"
    COMPLIANT = "compliant"


class AuditAction(str, Enum):
    ENTITY_CREATED = "entity_created"
    ENTITY_UPDATED = "entity_updated"
    ENTITY_DELETED = "entity_deleted"
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_APPROVED = "document_approved"
    DOCUMENT_REJECTED = "document_rejected"
    STATUS_UPDATED = "status_updated"
    PERSON_ADDED = "person_added"
    PERSON_REMOVED = "person_removed"
    PERSON_UPDATED = "person_updated"
    COMPLIANCE_UPDATED = "compliance_updated"
    NOTE_ADDED = "note_added"
    RELATIONSHIP_UPDATED = "relationship_updated"


class Entity(Base):
    __tablename__ = "entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    name = Column(String(255), nullable=False)
    entity_type = Column(SQLEnum(EntityType), nullable=False)
    jurisdiction = Column(String(100))
    location = Column(String(255))
    registration_number = Column(String(100))
    formation_date = Column(Date)
    status = Column(SQLEnum(EntityStatus), default=EntityStatus.PENDING, nullable=False)
    parent_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=True)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    parent_entity = relationship("Entity", remote_side=[id], backref="child_entities")
    compliance = relationship("EntityCompliance", back_populates="entity", uselist=False, cascade="all, delete-orphan")
    people = relationship("EntityPerson", back_populates="entity", cascade="all, delete-orphan")
    documents = relationship("EntityDocument", back_populates="entity", cascade="all, delete-orphan")
    audit_trail = relationship("EntityAuditTrail", back_populates="entity", cascade="all, delete-orphan", order_by="desc(EntityAuditTrail.timestamp)")


class EntityCompliance(Base):
    __tablename__ = "entity_compliance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False, unique=True)
    kyc_aml_status = Column(SQLEnum(ComplianceStatus), default=ComplianceStatus.PENDING)
    registered_agent = Column(String(255))
    tax_residency = Column(String(100))
    fatca_crs_compliance = Column(SQLEnum(ComplianceStatus), default=ComplianceStatus.PENDING)
    last_updated = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    entity = relationship("Entity", back_populates="compliance")


class EntityPerson(Base):
    __tablename__ = "entity_people"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    name = Column(String(255), nullable=False)
    role = Column(SQLEnum(EntityRole), nullable=False)
    email = Column(String(255))
    phone = Column(String(50))
    notes = Column(Text)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    entity = relationship("Entity", back_populates="people")
    user = relationship("User")


class EntityDocument(Base):
    __tablename__ = "entity_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False)
    name = Column(String(255), nullable=False)
    document_type = Column(SQLEnum(EntityDocumentType), nullable=False)
    status = Column(SQLEnum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False)
    file_path = Column(String(500))
    file_url = Column(String(500))
    supabase_storage_path = Column(String(500))
    file_size = Column(Integer)
    mime_type = Column(String(100))
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    description = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    entity = relationship("Entity", back_populates="documents")
    uploaded_by_user = relationship("User", foreign_keys=[uploaded_by])
    approved_by_user = relationship("User", foreign_keys=[approved_by])


class EntityAuditTrail(Base):
    __tablename__ = "entity_audit_trail"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(SQLEnum(AuditAction), nullable=False)
    action_display = Column(String(255))
    document_id = Column(UUID(as_uuid=True), ForeignKey("entity_documents.id"), nullable=True)
    status = Column(String(50), nullable=True)
    status_display = Column(String(255))
    notes = Column(Text)
    meta_data = Column("metadata", JSONB)  # Use "metadata" as column name, but "meta_data" as attribute
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    entity = relationship("Entity", back_populates="audit_trail")
    user = relationship("User")
    document = relationship("EntityDocument")
