"""System endpoints. (Under pytest the database is the isolated in-memory SQLite one; the real app reports "postgresql".)"""


def test_health_db_reports_ok_and_backend(client):
    res = client.get("/health/db")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "sqlite"}
