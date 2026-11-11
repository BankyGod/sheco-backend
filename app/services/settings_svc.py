from sqlalchemy.orm import Session

from app.models import SettingsRow


def get_or_create_settings(db: Session) -> SettingsRow:
    row = db.query(SettingsRow).filter(SettingsRow.singleton_key == "default").first()
    if row:
        return row
    row = SettingsRow(singleton_key="default")
    db.add(row)
    db.flush()
    return row
