import json

from sqlalchemy.orm import Session

from .. import models as m


def log(db: Session, actor: str, action: str, entity_type: str, entity_id: int | None,
        team_id: int | None = None, details: dict | None = None) -> None:
    safe = json.loads(json.dumps(details or {}, default=str))
    db.add(m.AuditLog(actor=actor or "system", action=action, entity_type=entity_type,
                      entity_id=entity_id, team_id=team_id, details=safe))
