from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from backend.database import Base


class AccountInvitation(Base):
    __tablename__ = "account_invitations"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
