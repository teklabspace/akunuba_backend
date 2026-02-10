from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    
    # Notification Preferences
    email_alerts = Column(Boolean, default=True, nullable=False)
    push_notifications = Column(Boolean, default=False, nullable=False)
    weekly_reports = Column(Boolean, default=True, nullable=False)
    market_updates = Column(Boolean, default=True, nullable=False)
    
    # Privacy Preferences
    profile_visible = Column(Boolean, default=True, nullable=False)
    show_portfolio = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    user = relationship("User", back_populates="preferences", uselist=False)
