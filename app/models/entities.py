from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sales: Mapped[list[Sale]] = relationship(back_populates="salesperson")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    generic_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(60), nullable=False, default="unit")
    # Money stored as integer pesewas (exact; never float)
    cost_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selling_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prescription_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    batches: Mapped[list[Batch]] = relationship(back_populates="product")


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    batch_number: Mapped[str] = mapped_column(String(80), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_price: Mapped[int] = mapped_column(Integer, nullable=False)
    supplier: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    date_received: Mapped[date] = mapped_column(Date, nullable=False)

    product: Mapped[Product] = relationship(back_populates="batches")


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    receipt_number: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(80), nullable=False)
    salesperson_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    discount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sync_flag: Mapped[str] = mapped_column(String(20), nullable=False, default="synced")
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_tendered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    change_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    momo_network: Mapped[str | None] = mapped_column(String(80), nullable=True)
    momo_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)

    salesperson: Mapped[User] = relationship(back_populates="sales")
    items: Mapped[list[SaleItem]] = relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sale_id: Mapped[str] = mapped_column(ForeignKey("sales.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_selling_price: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_price: Mapped[int] = mapped_column(Integer, nullable=False)
    prescription_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    sale: Mapped[Sale] = relationship(back_populates="items")


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    record: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SettingsRow(Base):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("singleton_key", name="uq_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    singleton_key: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    discount_limit_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    session_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    offline_unlock_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    expiry_alert_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    receipt_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
