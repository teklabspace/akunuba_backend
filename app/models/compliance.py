from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean, Date, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum
from decimal import Decimal


# ==================== ENUMS ====================

class TaskStatus(str, Enum):
    PENDING = "pending"
    OVERDUE = "overdue"
    NOT_STARTED = "not_started"
    COMPLETED = "completed"


class TaskPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AuditType(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    REGULATORY = "regulatory"


class AuditStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"


class ReportStatus(str, Enum):
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportFormat(str, Enum):
    PDF = "pdf"
    EXCEL = "excel"
    CSV = "csv"


class PolicyStatus(str, Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


# ==================== MODELS ====================

class ComplianceTask(Base):
    __tablename__ = "compliance_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=True)
    task_name = Column(String(255), nullable=False)
    description = Column(Text)
    assignee_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    due_date = Column(Date, nullable=False)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.NOT_STARTED, nullable=False)
    priority = Column(SQLEnum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False)
    category = Column(String(50))  # AML, KYC, GDPR, etc.
    completion_notes = Column(Text)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    entity = relationship("Entity")
    assignee = relationship("User", foreign_keys=[assignee_id])


class ComplianceTaskDocument(Base):
    __tablename__ = "compliance_task_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("compliance_tasks.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    task = relationship("ComplianceTask")
    document = relationship("Document")


class ComplianceTaskComment(Base):
    __tablename__ = "compliance_task_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("compliance_tasks.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    task = relationship("ComplianceTask")
    user = relationship("User")


class ComplianceTaskHistory(Base):
    __tablename__ = "compliance_task_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("compliance_tasks.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)  # created, updated, reassigned, completed, etc.
    old_value = Column(Text)
    new_value = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    task = relationship("ComplianceTask")
    user = relationship("User")


class ComplianceAudit(Base):
    __tablename__ = "compliance_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=True)
    audit_name = Column(String(255), nullable=False)
    audit_type = Column(SQLEnum(AuditType), nullable=False)
    status = Column(SQLEnum(AuditStatus), default=AuditStatus.PENDING, nullable=False)
    scheduled_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    auditor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    scope = Column(JSONB)  # Array of strings: ["AML", "KYC", "GDPR"]
    description = Column(Text)
    findings = Column(JSONB)  # Array of findings
    recommendations = Column(JSONB)  # Array of recommendations
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    entity = relationship("Entity")
    auditor = relationship("User", foreign_keys=[auditor_id])


class ComplianceAlert(Base):
    __tablename__ = "compliance_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=True)
    alert_type = Column(String(100), nullable=False)  # policy_violation, deadline_missed, etc.
    severity = Column(SQLEnum(AlertSeverity), nullable=False)
    status = Column(SQLEnum(AlertStatus), default=AlertStatus.OPEN, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    notes = Column(Text)
    resolution_notes = Column(Text)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    entity = relationship("Entity")
    acknowledged_by_user = relationship("User", foreign_keys=[acknowledged_by])
    resolved_by_user = relationship("User", foreign_keys=[resolved_by])


class ComplianceScore(Base):
    __tablename__ = "compliance_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=True)
    score = Column(Numeric(5, 2), nullable=False)  # 0.00 to 100.00
    change = Column(Numeric(5, 2))  # Change from previous score
    date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account")
    entity = relationship("Entity")


class ComplianceMetrics(Base):
    __tablename__ = "compliance_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=True)
    category = Column(String(50), nullable=False)  # AML, KYC, GDPR, etc.
    score = Column(Numeric(5, 2), nullable=False)
    status = Column(String(50))  # compliant, needs_attention, non_compliant
    issues_count = Column(Integer, default=0)
    date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account")
    entity = relationship("Entity")


class ComplianceReport(Base):
    __tablename__ = "compliance_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=True)
    report_type = Column(String(50), nullable=False)  # summary, detailed, etc.
    status = Column(SQLEnum(ReportStatus), default=ReportStatus.GENERATING, nullable=False)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    format = Column(SQLEnum(ReportFormat), nullable=False)
    include_sections = Column(JSONB)  # Array of strings: ["score", "tasks", "audits", "alerts"]
    file_path = Column(String(500), nullable=True)
    download_url = Column(String(500), nullable=True)
    supabase_storage_path = Column(String(500), nullable=True)
    file_size = Column(Integer, nullable=True)
    estimated_completion = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    entity = relationship("Entity")


class CompliancePolicy(Base):
    __tablename__ = "compliance_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=True)
    policy_name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)  # AML, KYC, GDPR, etc.
    status = Column(SQLEnum(PolicyStatus), default=PolicyStatus.DRAFT, nullable=False)
    version = Column(String(50), nullable=False)
    effective_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=True)
    last_reviewed = Column(Date, nullable=True)
    next_review = Column(Date, nullable=True)
    document_url = Column(String(500), nullable=True)
    document_path = Column(String(500), nullable=True)
    supabase_storage_path = Column(String(500), nullable=True)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    entity = relationship("Entity")
