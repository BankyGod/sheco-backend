from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AuditLog, Batch, Product, Sale, SaleItem, SettingsRow, User
from app.security import hash_password
from app.services.settings_svc import get_or_create_settings


def _days_from_now(n: int) -> date:
    return date.today() + timedelta(days=n)


def _days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


def seed_if_empty(db: Session) -> None:
    if db.query(User).first():
        get_or_create_settings(db)
        db.commit()
        return

    users = [
        User(
            id="u1",
            name="Ama Mensah",
            username="admin",
            password_hash=hash_password("admin123"),
            pin_hash=hash_password("1234"),
            role="super_admin",
            active=True,
        ),
        User(
            id="u2",
            name="Kwame Boateng",
            username="kwame",
            password_hash=hash_password("sale123"),
            pin_hash=hash_password("2222"),
            role="salesperson",
            active=True,
        ),
        User(
            id="u3",
            name="Efua Asante",
            username="efua",
            password_hash=hash_password("sale123"),
            pin_hash=hash_password("3333"),
            role="salesperson",
            active=True,
        ),
    ]
    for u in users:
        db.add(u)

    products = [
        Product(
            id="p1",
            name="Paracetamol 500mg",
            generic_name="Paracetamol",
            category="Analgesic",
            unit="blister",
            cost_price=120,
            selling_price=250,
            reorder_level=40,
            prescription_only=False,
            active=True,
        ),
        Product(
            id="p2",
            name="Amoxicillin 500mg",
            generic_name="Amoxicillin",
            category="Antibiotic",
            unit="capsule",
            cost_price=450,
            selling_price=800,
            reorder_level=30,
            prescription_only=True,
            active=True,
        ),
        Product(
            id="p3",
            name="ORS Sachet",
            generic_name="Oral Rehydration Salts",
            category="Rehydration",
            unit="sachet",
            cost_price=55,
            selling_price=150,
            reorder_level=50,
            prescription_only=False,
            active=True,
        ),
        Product(
            id="p4",
            name="Ibuprofen 400mg",
            generic_name="Ibuprofen",
            category="Analgesic",
            unit="blister",
            cost_price=200,
            selling_price=400,
            reorder_level=25,
            prescription_only=False,
            active=True,
        ),
        Product(
            id="p5",
            name="Metformin 500mg",
            generic_name="Metformin",
            category="Antidiabetic",
            unit="tablet",
            cost_price=280,
            selling_price=600,
            reorder_level=20,
            prescription_only=True,
            active=True,
        ),
        Product(
            id="p6",
            name="Vitamin C 1000mg",
            generic_name="Ascorbic Acid",
            category="Supplement",
            unit="bottle",
            cost_price=1800,
            selling_price=3500,
            reorder_level=10,
            prescription_only=False,
            active=True,
        ),
    ]
    for p in products:
        db.add(p)

    batches = [
        Batch(
            id="b1",
            product_id="p1",
            batch_number="PCM-2401",
            expiry_date=_days_from_now(200),
            quantity_received=200,
            quantity_remaining=148,
            cost_price=120,
            supplier="Ernest Chemists",
            date_received=_days_from_now(-40),
        ),
        Batch(
            id="b2",
            product_id="p2",
            batch_number="AMX-2311",
            expiry_date=_days_from_now(45),
            quantity_received=100,
            quantity_remaining=62,
            cost_price=450,
            supplier="Kinapharma",
            date_received=_days_from_now(-60),
        ),
        Batch(
            id="b3",
            product_id="p2",
            batch_number="AMX-2405",
            expiry_date=_days_from_now(300),
            quantity_received=80,
            quantity_remaining=80,
            cost_price=430,
            supplier="Kinapharma",
            date_received=_days_from_now(-10),
        ),
        Batch(
            id="b4",
            product_id="p3",
            batch_number="ORS-2390",
            expiry_date=_days_from_now(-5),
            quantity_received=120,
            quantity_remaining=18,
            cost_price=60,
            supplier="Tobinco",
            date_received=_days_from_now(-120),
        ),
        Batch(
            id="b5",
            product_id="p3",
            batch_number="ORS-2410",
            expiry_date=_days_from_now(180),
            quantity_received=150,
            quantity_remaining=120,
            cost_price=55,
            supplier="Tobinco",
            date_received=_days_from_now(-20),
        ),
        Batch(
            id="b6",
            product_id="p4",
            batch_number="IBU-2402",
            expiry_date=_days_from_now(70),
            quantity_received=90,
            quantity_remaining=22,
            cost_price=200,
            supplier="Ernest Chemists",
            date_received=_days_from_now(-35),
        ),
        Batch(
            id="b7",
            product_id="p5",
            batch_number="MET-2403",
            expiry_date=_days_from_now(250),
            quantity_received=60,
            quantity_remaining=41,
            cost_price=280,
            supplier="Dannex",
            date_received=_days_from_now(-25),
        ),
        Batch(
            id="b8",
            product_id="p6",
            batch_number="VTC-2401",
            expiry_date=_days_from_now(400),
            quantity_received=40,
            quantity_remaining=8,
            cost_price=1800,
            supplier="Dannex",
            date_received=_days_from_now(-15),
        ),
    ]
    for b in batches:
        db.add(b)

    sales = [
        Sale(
            id="sale_seed_1",
            receipt_number="DEV-SEED-20261110-0001",
            device_id="DEV-SEED",
            salesperson_id="u2",
            created_at=_days_ago(0),
            total=1050,
            status="completed",
            void_reason=None,
            sync_flag="synced",
            needs_review=False,
            payment_method="cash",
            amount_tendered=2000,
            change_amount=950,
        ),
        Sale(
            id="sale_seed_2",
            receipt_number="DEV-SEED-20261110-0002",
            device_id="DEV-SEED",
            salesperson_id="u3",
            created_at=_days_ago(0),
            total=1600,
            status="completed",
            sync_flag="synced",
            payment_method="momo",
            amount_tendered=1600,
            change_amount=0,
            momo_network="MTN MoMo",
            momo_reference="MTN-884221",
        ),
        Sale(
            id="sale_seed_3",
            receipt_number="DEV-SEED-20261109-0003",
            device_id="DEV-SEED",
            salesperson_id="u2",
            created_at=_days_ago(1),
            total=3500,
            status="completed",
            sync_flag="synced",
            payment_method="cash",
            amount_tendered=4000,
            change_amount=500,
        ),
        Sale(
            id="sale_seed_4",
            receipt_number="DEV-SEED-20261108-0004",
            device_id="DEV-SEED",
            salesperson_id="u3",
            created_at=_days_ago(2),
            total=800,
            status="voided",
            void_reason="Wrong product selected",
            sync_flag="synced",
            payment_method="cash",
            amount_tendered=1000,
            change_amount=200,
        ),
    ]
    for s in sales:
        db.add(s)

    items = [
        SaleItem(
            sale_id="sale_seed_1",
            product_id="p1",
            batch_id="b1",
            quantity=2,
            unit_selling_price=250,
            unit_cost_price=120,
        ),
        SaleItem(
            sale_id="sale_seed_1",
            product_id="p3",
            batch_id="b5",
            quantity=1,
            unit_selling_price=150,
            unit_cost_price=55,
        ),
        SaleItem(
            sale_id="sale_seed_1",
            product_id="p4",
            batch_id="b6",
            quantity=1,
            unit_selling_price=400,
            unit_cost_price=200,
        ),
        SaleItem(
            sale_id="sale_seed_2",
            product_id="p2",
            batch_id="b2",
            quantity=2,
            unit_selling_price=800,
            unit_cost_price=450,
            prescription_ref="RX-4412",
        ),
        SaleItem(
            sale_id="sale_seed_3",
            product_id="p6",
            batch_id="b8",
            quantity=1,
            unit_selling_price=3500,
            unit_cost_price=1800,
        ),
        SaleItem(
            sale_id="sale_seed_4",
            product_id="p2",
            batch_id="b2",
            quantity=1,
            unit_selling_price=800,
            unit_cost_price=450,
            prescription_ref="RX-1100",
        ),
    ]
    for item in items:
        db.add(item)

    audits = [
        AuditLog(
            id="a1",
            user_id="u1",
            device_id="DEV-SEED",
            action="sign_in",
            record="User Ama Mensah",
            time=_days_ago(0),
        ),
        AuditLog(
            id="a2",
            user_id="u2",
            device_id="DEV-SEED",
            action="sale",
            record="Receipt DEV-SEED-20261110-0001",
            time=_days_ago(0),
        ),
        AuditLog(
            id="a3",
            user_id="u1",
            device_id="DEV-SEED",
            action="void",
            record="Receipt DEV-SEED-20261108-0004 — Wrong product selected",
            time=_days_ago(2),
        ),
        AuditLog(
            id="a4",
            user_id="u1",
            device_id="DEV-SEED",
            action="price_change",
            record="Paracetamol 500mg selling price updated",
            time=_days_ago(5),
        ),
    ]
    for a in audits:
        db.add(a)

    settings = SettingsRow(
        singleton_key="default",
        discount_limit_percent=10,
        session_timeout_minutes=60,
        offline_unlock_days=7,
        expiry_alert_days=90,
        receipt_seq=10,
    )
    db.add(settings)
    db.commit()
