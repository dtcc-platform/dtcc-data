#!/usr/bin/env python3
"""Read or create the root-only database credential file used by the service.

Run as root by aws-setup.sh on the remote host:

    db-env.py read PATH USER DB    print the validated DATABASE_URL
    db-env.py write PATH USER DB   create PATH from the password on stdin
    db-env.py verifier             print a SCRAM-SHA-256 verifier for the password on stdin

The file holds exactly one line, DATABASE_URL=postgresql://USER:PASS@localhost:5432/DB.
Errors never print the file content or the password.
"""

import base64
import hashlib
import hmac
import os
import re
import stat
import sys

UID = GID = 0  # root; tests override these
IDENT = re.compile(r"[a-z_][a-z0-9_]{0,62}")
PASSWORD = re.compile(r"[A-Za-z0-9]{1,128}")


def fail(message):
    sys.stderr.write("ERROR: " + message + "\n")
    sys.exit(1)


def check_password(password):
    if not PASSWORD.fullmatch(password):
        fail("the database password must be 1-128 letters and digits")


def verifier(password, salt=None, iterations=4096):
    """Return a PostgreSQL SCRAM-SHA-256 verifier, so the server never receives the password."""
    salt = os.urandom(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    stored_key = hashlib.sha256(hmac.new(salted, b"Client Key", "sha256").digest()).digest()
    server_key = hmac.new(salted, b"Server Key", "sha256").digest()
    b64 = [base64.b64encode(value).decode() for value in (salt, stored_key, server_key)]
    return "SCRAM-SHA-256$%d:%s$%s:%s" % (iterations, b64[0], b64[1], b64[2])


def line(user, db, password):
    return "DATABASE_URL=postgresql://%s:%s@localhost:5432/%s\n" % (user, password, db)


def check_dir(path):
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != UID or st.st_mode & 0o077:
        fail("%s must be a directory owned by root with mode 0700" % path)


def read(path, user, db):
    check_dir(os.path.dirname(path))
    try:
        # O_NONBLOCK keeps a FIFO from blocking before its type is checked
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        fail("cannot open %s as a regular file" % path)
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != UID or st.st_gid != GID
                or stat.S_IMODE(st.st_mode) != 0o600):
            fail("%s must be a regular file owned by root:root with mode 0600" % path)
        content = f.read(4097)
    expected = re.compile(
        rb"DATABASE_URL=postgresql://%s:([A-Za-z0-9]{1,128})@localhost:5432/%s\n"
        % (re.escape(user.encode()), re.escape(db.encode())))
    if not expected.fullmatch(content):
        fail("%s must hold exactly one DATABASE_URL line for %s on database %s" % (path, user, db))
    return content.decode()[len("DATABASE_URL="):-1]


def write(path, user, db, password):
    check_password(password)
    directory = os.path.dirname(path)
    os.umask(0o077)
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError:
        pass
    check_dir(directory)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        fail("%s already exists; it is never overwritten" % path)
    with os.fdopen(fd, "w") as f:
        f.write(line(user, db, password))
        f.flush()
        os.fsync(f.fileno())
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def main(argv):
    if argv == ["verifier"]:
        password = sys.stdin.read()
        check_password(password)
        sys.stdout.write(verifier(password))
        return
    if len(argv) != 4 or argv[0] not in ("read", "write"):
        fail("usage: db-env.py read|write PATH USER DB, or db-env.py verifier")
    command, path, user, db = argv
    if not os.path.isabs(path) or not IDENT.fullmatch(user) or not IDENT.fullmatch(db):
        fail("PATH must be absolute; USER and DB must be lowercase identifiers")
    if command == "read":
        sys.stdout.write(read(path, user, db))
    else:
        write(path, user, db, sys.stdin.read())


if __name__ == "__main__":
    main(sys.argv[1:])
