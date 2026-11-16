from sqlalchemy.engine import make_url

from app.config import _database_url


def test_database_defaults_to_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SQLITE_DB_PATH", raising=False)

    url = make_url(_database_url())

    assert url.drivername == "sqlite"
    assert url.database == "ehcc.db"


def test_database_uses_configured_sqlite_path(monkeypatch, tmp_path):
    db_path = tmp_path / "EHCC" / "DB" / "ehcc-admin.db"
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_path))

    url = make_url(_database_url())

    assert url.drivername == "sqlite"
    assert url.database == str(db_path)


def test_explicit_external_database_url_takes_precedence(monkeypatch):
    monkeypatch.setenv("SQLITE_DB_PATH", "/var/lib/ehcc/ehcc.db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example/neondb")

    url = make_url(_database_url())

    assert url.drivername == "postgresql+psycopg"
    assert url.host == "db.example"
    assert url.database == "neondb"
