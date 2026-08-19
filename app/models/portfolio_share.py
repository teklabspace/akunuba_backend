from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid


class PortfolioShare(Base):
    """A time-limited, anonymous link to a portfolio view.

    Mirrors ``AssetShare`` but is scoped to an account and a view (currently
    ``crypto``) rather than to a single asset, because what is being shared is
    a whole page of aggregated holdings.
    """
    __tablename__ = "portfolio_shares"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True)
    # Which portfolio view the link resolves to, e.g. "crypto".
    view = Column(String(32), nullable=False, default="crypto")
    share_link = Column(String(500), nullable=False, unique=True)
    # The access code IS the credential — the resolve endpoint is anonymous.
    access_code = Column(String(64), nullable=False, index=True)
    email = Column(String(255))
    expires_at = Column(DateTime(timezone=True))
    # Snapshot of the range the link was generated for, so the recipient sees
    # the same window the owner was looking at.
    window = Column(JSONB)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account")
