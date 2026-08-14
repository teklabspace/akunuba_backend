"""Delegated asset creation — investor requests an advisor, admin issues a grant.

See docs/superpowers/specs/2026-08-12-delegated-asset-creation-design.md in the
frontend repo.

Status columns are String(20) rather than native PG enums, matching the
convention set by 037_transfers. Compare against the enum members' `.value`.
"""
import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class AdvisorRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class GrantStatus(str, enum.Enum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AdvisorRequest(Base):
    """An investor asking an admin to allot them a specific advisor.

    At most one PENDING row per investor, enforced by a partial unique index.
    """
    __tablename__ = "advisor_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    # Nullable: the investor may only be able to describe who they spoke to.
    requested_advisor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    note = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, server_default=AdvisorRequestStatus.PENDING.value)
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decision_reason = Column(Text, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AssetDelegationGrant(Base):
    """Single-use authorisation for an advisor to create ONE asset for an investor.

    `expires_at` bounds only an UNCONSUMED grant — it is the deadline to create
    the asset at all. Once consumed, the advisor's edit rights are governed by
    the asset_access row (Milestone 3), not by this expiry.
    """
    __tablename__ = "asset_delegation_grants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("advisor_requests.id"), nullable=True)
    investor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    advisor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, server_default=GrantStatus.ACTIVE.value)
    # Stamped when the grant is consumed (Milestone 2).
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    issued_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
