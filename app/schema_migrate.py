from sqlalchemy import inspect, text

from app.database import engine


SETTINGS_COLUMNS = {
    "pharmacy_name": "VARCHAR(200) NOT NULL DEFAULT 'Sheco Pharmacy'",
    "pharmacy_phone": "VARCHAR(80) NOT NULL DEFAULT ''",
    "pharmacy_address": "VARCHAR(300) NOT NULL DEFAULT ''",
    "pharmacy_email": "VARCHAR(160) NOT NULL DEFAULT ''",
    "receipt_footer": "VARCHAR(300) NOT NULL DEFAULT 'Thank you for shopping with Sheco'",
    "momo_account_name": "VARCHAR(160) NOT NULL DEFAULT ''",
    "momo_account_number": "VARCHAR(80) NOT NULL DEFAULT ''",
}

USERS_COLUMNS = {
    "deleted": "BOOLEAN NOT NULL DEFAULT FALSE",
}

SALES_COLUMNS = {
    "review_reason": "VARCHAR(500)",
}


def _add_missing_columns(table: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table)}
    with engine.begin() as conn:
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def ensure_schema() -> None:
    _add_missing_columns("settings", SETTINGS_COLUMNS)
    _add_missing_columns("users", USERS_COLUMNS)
    _add_missing_columns("sales", SALES_COLUMNS)
