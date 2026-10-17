from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from .config import DATABASE_URL
from .models import Base

_kwargs = {"pool_pre_ping": True, "pool_recycle": 300}
if DATABASE_URL.startswith("sqlite"):
    _kwargs = {"connect_args": {"check_same_thread": False}}

engine = create_engine(DATABASE_URL, **_kwargs)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def ensure_schema_compatibility():
    """Create missing tables and add missing columns without dropping existing data.

    Alembic remains the source of truth for constraints and indexes. This additive
    compatibility pass handles a fresh database and older installs missing columns.
    """
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {col["name"] for col in inspect(conn).get_columns(table.name)}
            for column in table.columns:
                if column.name in existing or column.primary_key:
                    continue
                compiled = column.type.compile(dialect=engine.dialect)
                nullable = " NULL" if column.nullable else ""
                default_sql = ""
                default = column.server_default
                if default is not None:
                    default_sql = f" DEFAULT {default.arg}"
                elif not column.nullable:
                    # Backfill safely from a scalar Python-side default where possible.
                    py_default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
                    if py_default is None:
                        raise RuntimeError(
                            f"Cannot add required column {table.name}.{column.name} without a server default; "
                            "run the matching Alembic migration."
                        )
                    if isinstance(py_default, str):
                        literal = "'" + py_default.replace("'", "''") + "'"
                    elif isinstance(py_default, bool):
                        literal = "TRUE" if py_default else "FALSE"
                    else:
                        literal = str(py_default)
                    default_sql = f" DEFAULT {literal}"
                conn.execute(text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {compiled}{default_sql}{nullable}'
                ))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
