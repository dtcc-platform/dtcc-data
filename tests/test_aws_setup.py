"""Tests for the database credential handling in deploy/aws-setup.sh.

aws-setup.sh runs with a fake ssh that captures each remote step. The captured
database step then runs against fake sudo, psql and pg_isready for each
role/credential-file case. Fake sudo maps /etc to a temporary root.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PASSWORD = "Setup123abc"
OTHER = "Other999xyz"

FAKES = {
    "ssh": r"""#!/bin/sh
case "$*" in *"echo ok") exit 0 ;; esac
n=$(ls "$CAPTURE" | wc -l | tr -d ' ')
cat > "$CAPTURE/step-$n.sh"
""",
    "sudo": r"""#!/bin/sh
echo "sudo $*" >> "$ARGV_LOG"
case "$1" in
  -u) shift 2; exec "$@" ;;
  test) shift; exec test $(printf '%s\n' "$*" | sed "s#/etc/#$ROOT/etc/#g") ;;
  /usr/bin/python3)
    code=$(printf '%s' "$4" | sed "s/^UID = GID = 0 .*/UID, GID = $(id -u), $(id -g)/")
    exec "$PYTHON" -I -c "$code" "$5" "$ROOT$6" "$7" "$8" ;;
esac
exit 99
""",
    "psql": r"""#!/bin/sh
echo "psql $*" >> "$ARGV_LOG"
case "$*" in
  *require_auth=scram-sha-256*) [ "$PGPASSWORD" = "$ROLE_PASS" ]; exit $? ;;
  *-tc*) echo 1; exit 0 ;;
esac
sql=$(cat)
case "$sql" in
  *"FROM pg_roles"*) [ -n "$ROLE_PASS" ] && echo 1; exit 0 ;;
  *"CREATE ROLE"*) printf '%s\n' "$sql" > "$ROOT/create-role.sql" ;;
esac
exit 0
""",
    "pg_isready": "#!/bin/sh\nexit 0\n",
}


def fake_bin(tmp):
    path = tmp / "bin"
    path.mkdir()
    for name, body in FAKES.items():
        (path / name).write_text(body)
        (path / name).chmod(0o755)
    return path


def render(tmp, db_pass):
    """Run aws-setup.sh locally and return the captured remote steps by role."""
    deploy = tmp / "repo" / "deploy"
    deploy.mkdir(parents=True)
    for name in ("aws-setup.sh", "db-env.py", "post-setup-dtcc-data.sh"):
        shutil.copy(REPO / "deploy" / name, deploy / name)
    (deploy / "deploy.env").write_text(
        "REPO_URL=https://example.invalid/repo.git\nDB_NAME=dtcc_data\nDB_PASS=%s\n"
        "POST_SETUP_SCRIPT=deploy/post-setup-dtcc-data.sh\n" % db_pass)
    (deploy / ".env.aws").write_text("KEY_FILE=/dev/null\nPUBLIC_IP=192.0.2.1\n")
    capture = tmp / "capture"
    capture.mkdir()
    env = {**os.environ, "PATH": "%s:%s" % (fake_bin(tmp), os.environ["PATH"]),
           "CAPTURE": str(capture)}
    subprocess.run(["bash", str(deploy / "aws-setup.sh")], env=env, check=True,
                   capture_output=True, stdin=subprocess.DEVNULL)
    scripts = [p.read_text() for p in capture.iterdir()]
    markers = {"db": "Decide from the role", "post": "Pass DATABASE_URL", "unit": "[Service]"}
    return {key: next(s for s in scripts if marker in s) for key, marker in markers.items()}


@pytest.fixture(scope="module")
def with_pass(tmp_path_factory):
    return render(tmp_path_factory.mktemp("with-pass"), PASSWORD)


@pytest.fixture(scope="module")
def without_pass(tmp_path_factory):
    return render(tmp_path_factory.mktemp("without-pass"), "")


def run_db_step(tmp, script, role_pass, file_pass=None):
    """Run the captured database step; role_pass empty means the role is absent."""
    root = tmp / "root"
    (root / "etc").mkdir(parents=True)
    env_file = root / "etc" / "dtcc-data" / "database.env"
    if file_pass is not None:
        env_file.parent.mkdir(mode=0o700)
        env_file.write_text(
            "DATABASE_URL=postgresql://dtcc:%s@localhost:5432/dtcc_data\n" % file_pass)
        env_file.chmod(0o600)
    (tmp / "step.sh").write_text(script)
    argv_log = tmp / "argv.log"
    env = {**os.environ, "PATH": "%s:%s" % (fake_bin(tmp), os.environ["PATH"]),
           "ROOT": str(root), "ARGV_LOG": str(argv_log), "ROLE_PASS": role_pass,
           "PYTHON": sys.executable, "HOME": str(tmp)}
    result = subprocess.run(["bash", str(tmp / "step.sh")], env=env, capture_output=True,
                            text=True, stdin=subprocess.DEVNULL)
    argv = argv_log.read_text()
    assert PASSWORD not in argv and OTHER not in argv
    assert PASSWORD not in result.stdout and OTHER not in result.stdout
    content = env_file.read_text() if env_file.exists() else None
    created = root / "create-role.sql"
    return result, content, created.read_text() if created.exists() else None


def url_line(password):
    return "DATABASE_URL=postgresql://dtcc:%s@localhost:5432/dtcc_data\n" % password


def test_new_role_and_file(tmp_path, with_pass):
    result, content, created = run_db_step(tmp_path, with_pass["db"], role_pass="")
    assert result.returncode == 0, result.stderr
    assert created == ("SET log_statement = 'none';\nSET log_min_error_statement = 'panic';\n"
                       "CREATE ROLE :\"role\" LOGIN PASSWORD '%s';\n" % PASSWORD)
    assert content == url_line(PASSWORD)


def test_existing_role_writes_file_after_login(tmp_path, with_pass):
    result, content, created = run_db_step(tmp_path, with_pass["db"], role_pass=PASSWORD)
    assert result.returncode == 0, result.stderr
    assert created is None and content == url_line(PASSWORD)


def test_existing_role_refuses_wrong_password(tmp_path, with_pass):
    result, content, created = run_db_step(tmp_path, with_pass["db"], role_pass=OTHER)
    assert result.returncode == 1 and "does not authenticate" in result.stderr
    assert content is None and created is None


def test_existing_file_is_used_without_db_pass(tmp_path, without_pass):
    result, content, created = run_db_step(tmp_path, without_pass["db"], OTHER, OTHER)
    assert result.returncode == 0, result.stderr
    assert content == url_line(OTHER) and created is None


def test_existing_file_refuses_different_db_pass(tmp_path, with_pass):
    result, content, _ = run_db_step(tmp_path, with_pass["db"], OTHER, OTHER)
    assert result.returncode == 1 and "DB_PASS differs" in result.stderr
    assert content == url_line(OTHER)


def test_existing_file_must_authenticate(tmp_path, without_pass):
    result, content, _ = run_db_step(tmp_path, without_pass["db"], PASSWORD, OTHER)
    assert result.returncode == 1 and "does not authenticate" in result.stderr
    assert content == url_line(OTHER)


def test_file_without_role_fails(tmp_path, with_pass):
    result, content, created = run_db_step(tmp_path, with_pass["db"], "", PASSWORD)
    assert result.returncode == 1 and "role dtcc does not" in result.stderr
    assert created is None


def test_no_file_needs_db_pass(tmp_path, without_pass):
    result, content, created = run_db_step(tmp_path, without_pass["db"], role_pass="")
    assert result.returncode == 1 and "DB_PASS must be set" in result.stderr
    assert content is None and created is None


def test_unit_and_post_setup_keep_the_password_out(with_pass):
    unit, post = with_pass["unit"], with_pass["post"]
    assert "EnvironmentFile=/etc/dtcc-data/database.env" in unit
    assert "DATABASE_URL" not in unit and PASSWORD not in unit
    assert "read /etc/dtcc-data/database.env dtcc dtcc_data" in post
    assert "DB_PASS" not in post and PASSWORD not in post and "--database-url" not in post
