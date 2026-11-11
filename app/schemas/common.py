from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Role = Literal["super_admin", "salesperson"]
PaymentMethod = Literal["cash", "momo"]
SaleStatus = Literal["completed", "voided"]


class CamelModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PublicUser(CamelModel):
    id: str
    name: str
    username: str
    role: Role
    active: bool


class SessionOut(CamelModel):
    user: PublicUser
    device_id: str = Field(alias="deviceId")
    signed_in_at: datetime = Field(alias="signedInAt")
    access_token: str = Field(alias="accessToken")
    token_type: str = Field(default="bearer", alias="tokenType")
    offline_unlock_days: int = Field(alias="offlineUnlockDays")


class LoginIn(CamelModel):
    username: str
    password: str
    device_id: str | None = Field(default=None, alias="deviceId")


class UserCreateIn(CamelModel):
    name: str
    username: str
    password: str
    pin: str | None = "0000"
    role: Role


class UserActiveIn(CamelModel):
    active: bool


class PasswordResetIn(CamelModel):
    password: str


class BatchOut(CamelModel):
    id: str
    product_id: str = Field(alias="productId")
    batch_number: str = Field(alias="batchNumber")
    expiry_date: date = Field(alias="expiryDate")
    quantity_received: int = Field(alias="quantityReceived")
    quantity_remaining: int = Field(alias="quantityRemaining")
    cost_price: int = Field(alias="costPrice")
    supplier: str
    date_received: date = Field(alias="dateReceived")
    expired: bool | None = None
    days_to_expiry: int | None = Field(default=None, alias="daysToExpiry")


class ProductOut(CamelModel):
    id: str
    name: str
    generic_name: str = Field(alias="genericName")
    category: str
    unit: str
    cost_price: int | None = Field(default=None, alias="costPrice")
    selling_price: int = Field(alias="sellingPrice")
    reorder_level: int = Field(alias="reorderLevel")
    prescription_only: bool = Field(alias="prescriptionOnly")
    active: bool
    available_qty: int = Field(alias="availableQty")
    total_qty: int = Field(alias="totalQty")
    low_stock: bool = Field(alias="lowStock")
    expiring_soon: bool = Field(alias="expiringSoon")
    expired_qty: int = Field(alias="expiredQty")
    unit_profit: int | None = Field(default=None, alias="unitProfit")
    batches: list[BatchOut] | None = None


class ProductSaveIn(CamelModel):
    id: str | None = None
    name: str
    generic_name: str = Field(alias="genericName")
    category: str
    unit: str
    cost_price: int = Field(alias="costPrice")
    selling_price: int = Field(alias="sellingPrice")
    reorder_level: int = Field(alias="reorderLevel")
    prescription_only: bool = Field(default=False, alias="prescriptionOnly")
    active: bool = True


class RestockIn(CamelModel):
    product_id: str = Field(alias="productId")
    batch_number: str = Field(alias="batchNumber")
    expiry_date: date = Field(alias="expiryDate")
    quantity: int
    cost_price: int = Field(alias="costPrice")
    supplier: str = ""


class AdjustStockIn(CamelModel):
    batch_id: str = Field(alias="batchId")
    new_quantity: int = Field(alias="newQuantity")
    reason: str


class PaymentIn(CamelModel):
    method: PaymentMethod
    amount_tendered: int = Field(alias="amountTendered")
    change: int = 0
    network: str | None = None
    reference: str | None = None


class SaleLineIn(CamelModel):
    product_id: str = Field(alias="productId")
    quantity: int
    prescription_ref: str | None = Field(default=None, alias="prescriptionRef")


class CompleteSaleIn(CamelModel):
    items: list[SaleLineIn]
    payment: PaymentIn
    offline: bool = False
    id: str | None = None
    receipt_number: str | None = Field(default=None, alias="receiptNumber")
    device_id: str | None = Field(default=None, alias="deviceId")
    created_at: datetime | None = Field(default=None, alias="createdAt")


class SyncSalesIn(CamelModel):
    sales: list[CompleteSaleIn]


class VoidSaleIn(CamelModel):
    reason: str


class SaleItemOut(CamelModel):
    product_id: str = Field(alias="productId")
    batch_id: str = Field(alias="batchId")
    quantity: int
    unit_selling_price: int = Field(alias="unitSellingPrice")
    unit_cost_price: int | None = Field(default=None, alias="unitCostPrice")
    prescription_ref: str | None = Field(default=None, alias="prescriptionRef")


class PaymentOut(CamelModel):
    method: PaymentMethod
    amount_tendered: int = Field(alias="amountTendered")
    change: int
    network: str | None = None
    reference: str | None = None


class SaleOut(CamelModel):
    id: str
    receipt_number: str = Field(alias="receiptNumber")
    device_id: str = Field(alias="deviceId")
    salesperson_id: str = Field(alias="salespersonId")
    created_at: datetime = Field(alias="createdAt")
    total: int
    status: SaleStatus
    void_reason: str | None = Field(default=None, alias="voidReason")
    payment: PaymentOut
    items: list[SaleItemOut]
    sync_flag: str | None = Field(default=None, alias="syncFlag")
    needs_review: bool | None = Field(default=None, alias="needsReview")


class SettingsOut(CamelModel):
    discount_limit_percent: int = Field(alias="discountLimitPercent")
    session_timeout_minutes: int = Field(alias="sessionTimeoutMinutes")
    offline_unlock_days: int = Field(alias="offlineUnlockDays")
    expiry_alert_days: int = Field(alias="expiryAlertDays")


class SettingsUpdateIn(CamelModel):
    discount_limit_percent: int | None = Field(default=None, alias="discountLimitPercent")
    session_timeout_minutes: int | None = Field(default=None, alias="sessionTimeoutMinutes")
    offline_unlock_days: int | None = Field(default=None, alias="offlineUnlockDays")
    expiry_alert_days: int | None = Field(default=None, alias="expiryAlertDays")


class AuditOut(CamelModel):
    id: str
    user_id: str = Field(alias="userId")
    device_id: str = Field(alias="deviceId")
    action: str
    record: str
    time: datetime
    user_name: str | None = Field(default=None, alias="userName")
