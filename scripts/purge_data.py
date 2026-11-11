"""One-shot purge: keep settings + one admin; remove inventory/sales/other users.

Usage (from backend root):
  .\\.venv\\Scripts\\python scripts/purge_data.py
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal, Base, engine
from app.schema_migrate import ensure_schema
from app.services.purge import purge_operational_data


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        result = purge_operational_data(db)
        db.commit()
        print("Purge complete:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
