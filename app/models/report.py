from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class ReportType(str, Enum):
    PORTFOLIO = "portfolio"
    PERFORMANCE = "performance"
    TRANSACTION = "transaction"
    TAX = "tax"
    CUSTOM = "custom"


class ReportStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportFormat(str, Enum):
    PDF = "pdf"
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    report_type = Column(SQLEnum(ReportType), nullable=False)
    status = Column(SQLEnum(ReportStatus), default=ReportStatus.PENDING, nullable=False)
    format = Column(SQLEnum(ReportFormat), default=ReportFormat.PDF, nullable=False)
    
    # Date range for the report
    start_date = Column(DateTime(timezone=True))
    end_date = Column(DateTime(timezone=True))
    
    # Filters and parameters stored as JSON
    filters = Column(JSONB)
    parameters = Column(JSONB)
    
    # Generated report file
    file_path = Column(String(500))
    file_size = Column(Integer)
    file_url = Column(String(500))
    supabase_storage_path = Column(String(500))
    
    # Metadata
    generated_at = Column(DateTime(timezone=True))
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
