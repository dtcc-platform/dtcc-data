"""Tests for deploy/db-env.py, the root-only database credential file helper."""

import importlib.util
import io
import os

import pytest

PASSWORD = "Abc123xyz"
URL = "postgresql://dtcc:Abc123xyz@localhost:5432/dtcc_data"


@pytest.fixture
def dbenv(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "db_env", os.path.join(os.path.dirname(__file__), "..", "deploy", "db-env.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "UID", os.getuid())
    monkeypatch.setattr(mod, "GID", os.getgid())
    return mod


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "dtcc-data" / "database.env")


def run(dbenv, monkeypatch, capsys, *argv, stdin=""):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    try:
        dbenv.main(list(argv))
        code = 0
    except SystemExit as exc:
        code = exc.code
    out, err = capsys.readouterr()
    return code, out, err


def test_write_then_read_round_trips(dbenv, path, monkeypatch, capsys):
    assert run(dbenv, monkeypatch, capsys, "write", path, "dtcc", "dtcc_data", stdin=PASSWORD)[0] == 0
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert oct(os.stat(os.path.dirname(path)).st_mode & 0o777) == "0o700"
    assert run(dbenv, monkeypatch, capsys, "read", path, "dtcc", "dtcc_data") == (0, URL, "")


def test_write_never_overwrites(dbenv, path, monkeypatch, capsys):
    run(dbenv, monkeypatch, capsys, "write", path, "dtcc", "dtcc_data", stdin=PASSWORD)
    code, out, err = run(dbenv, monkeypatch, capsys, "write", path, "dtcc", "dtcc_data", stdin="Other1")
    assert code == 1 and "never overwritten" in err
    assert open(path).read() == "DATABASE_URL=" + URL + "\n"


@pytest.mark.parametrize("password", ["", "pa:ss", "pa@ss", "pa'ss", "pass\n", "x" * 129])
def test_write_refuses_unsafe_passwords(dbenv, path, monkeypatch, capsys, password):
    code, out, err = run(dbenv, monkeypatch, capsys, "write", path, "dtcc", "dtcc_data", stdin=password)
    assert code == 1 and not os.path.exists(path)


@pytest.mark.parametrize("content", [
    "DATABASE_URL=" + URL,                                        # no newline
    "DATABASE_URL=" + URL + "\nDATABASE_URL=" + URL + "\n",       # repeated key
    "DATABASE_URL=" + URL.replace("dtcc:", "other:") + "\n",      # another user
    "DATABASE_URL=" + URL.replace("/dtcc_data", "/other") + "\n",  # another database
    "DATABASE_URL=" + URL.replace("localhost", "db.example") + "\n",
    "DATABASE_URL=" + URL.replace("Abc123xyz", "Abc 123") + "\n",
    "export DATABASE_URL=" + URL + "\n",
])
def test_read_refuses_unexpected_content(dbenv, path, monkeypatch, capsys, content):
    os.mkdir(os.path.dirname(path), 0o700)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o600)
    code, out, err = run(dbenv, monkeypatch, capsys, "read", path, "dtcc", "dtcc_data")
    assert code == 1 and out == ""
    assert "Abc" not in err


def test_read_refuses_loose_mode_and_symlink(dbenv, path, monkeypatch, capsys):
    run(dbenv, monkeypatch, capsys, "write", path, "dtcc", "dtcc_data", stdin=PASSWORD)
    os.chmod(path, 0o644)
    assert run(dbenv, monkeypatch, capsys, "read", path, "dtcc", "dtcc_data")[0] == 1
    os.chmod(path, 0o600)
    link = os.path.join(os.path.dirname(path), "link.env")
    os.symlink(path, link)
    assert run(dbenv, monkeypatch, capsys, "read", link, "dtcc", "dtcc_data")[0] == 1
    os.chmod(os.path.dirname(path), 0o755)
    assert run(dbenv, monkeypatch, capsys, "read", path, "dtcc", "dtcc_data")[0] == 1


def test_read_refuses_wrong_owner(dbenv, path, monkeypatch, capsys):
    run(dbenv, monkeypatch, capsys, "write", path, "dtcc", "dtcc_data", stdin=PASSWORD)
    monkeypatch.setattr(dbenv, "GID", os.getgid() + 1)
    assert run(dbenv, monkeypatch, capsys, "read", path, "dtcc", "dtcc_data")[0] == 1


@pytest.mark.parametrize("argv", [
    ("read", "relative.env", "dtcc", "dtcc_data"),
    ("read", "/etc/x/database.env", "Dtcc", "dtcc_data"),
    ("read", "/etc/x/database.env", "dtcc", "dtcc-data"),
    ("delete", "/etc/x/database.env", "dtcc", "dtcc_data"),
])
def test_refuses_bad_arguments(dbenv, monkeypatch, capsys, argv):
    assert run(dbenv, monkeypatch, capsys, *argv)[0] == 1
