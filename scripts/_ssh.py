# -*- coding: utf-8 -*-
"""Paramiko helper used by sync_to_cvm.ps1.

Performs SCP-style uploads (single file or whole directory tree) and
remote shell commands against the medical-audit CVM.

Usage (called from PowerShell, not directly):

    python -X utf8 scripts/_ssh.py upload <local_path> <remote_path>
    python -X utf8 scripts/_ssh.py backup <remote_db_path>
    python -X utf8 scripts/_ssh.py exec  "<remote shell command>"
    python -X utf8 scripts/_ssh.py healthcheck <local_url>
    python -X utf8 scripts/_ssh.py healthcheck-remote <url>   # curl from inside the CVM

Credentials are read from environment variables so the .ps1 wrapper
controls where they live:
    MA_SSH_HOST   (default: 132.232.152.250)
    MA_SSH_PORT   (default: 2222)
    MA_SSH_USER   (default: root)
    MA_SSH_PASS   (required, no default)
"""

from __future__ import annotations

import os
import posixpath
import sys
import time
from pathlib import Path

import shlex
import paramiko


HOST = os.environ.get("MA_SSH_HOST", "132.232.152.250")
PORT = int(os.environ.get("MA_SSH_PORT", "2222"))
USER = os.environ.get("MA_SSH_USER", "root")
PASS = os.environ.get("MA_SSH_PASS", "")
if not PASS:
    raise SystemExit("MA_SSH_PASS env var required (set it in your shell before running)")


def _connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASS,
                   timeout=30, banner_timeout=30, auth_timeout=30)
    return client


def _human_size(num_bytes):
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _ensure_dir(sftp, remote_dir):
    if remote_dir in ("", "/"):
        return
    parts = []
    cursor = remote_dir
    while cursor not in ("", "/"):
        parts.append(cursor)
        cursor = posixpath.dirname(cursor)
    for d in reversed(parts):
        try:
            sftp.stat(d)
        except IOError:
            parent = posixpath.dirname(d)
            try:
                sftp.stat(parent)
            except IOError:
                continue
            try:
                sftp.mkdir(d)
            except IOError:
                pass


def _put_file(sftp, local, remote):
    _ensure_dir(sftp, posixpath.dirname(remote))
    size = local.stat().st_size
    sftp.put(str(local), remote)
    print(f"  [file] {local} -> {remote} ({_human_size(size)})")


def _put_dir(sftp, local, remote):
    _ensure_dir(sftp, remote)
    for root, dirs, files in os.walk(local):
        rel = Path(root).relative_to(local)
        target_dir = remote if str(rel) == "." else posixpath.join(remote, *rel.parts)
        _ensure_dir(sftp, target_dir)
        for name in files:
            src = Path(root) / name
            dst = posixpath.join(target_dir, name)
            _put_file(sftp, src, dst)


def cmd_upload(local_arg, remote_arg):
    local = Path(local_arg).resolve()
    if not local.exists():
        print(f"[ERR] local path not found: {local}", file=sys.stderr)
        return 2

    client = _connect()
    try:
        sftp = client.open_sftp()
        try:
            if local.is_file():
                _put_file(sftp, local, remote_arg)
            else:
                _put_dir(sftp, local, remote_arg)
        finally:
            sftp.close()
    finally:
        client.close()
    print(f"[OK] upload complete: {local} -> {remote_arg}")
    return 0


def cmd_backup(remote_db_arg):
    remote_dir = posixpath.dirname(remote_db_arg)
    remote_name = posixpath.basename(remote_db_arg)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_name = f"{remote_name}.bak.{stamp}"
    backup_path = posixpath.join(remote_dir, backup_name)

    client = _connect()
    try:
        sftp = client.open_sftp()
        try:
            try:
                sftp.stat(remote_db_arg)
            except IOError:
                print(f"[skip] remote DB not found, nothing to back up: {remote_db_arg}")
                return 0
            try:
                sftp.rename(remote_db_arg, backup_path)
                print(f"[OK] backup created: {backup_path}")
            except IOError as exc:
                print(f"[ERR] backup rename failed: {exc}", file=sys.stderr)
                return 3
        finally:
            sftp.close()
    finally:
        client.close()
    return 0


def cmd_exec(remote_cmd):
    client = _connect()
    try:
        stdin, stdout, stderr = client.exec_command(remote_cmd, timeout=300)
        for line in iter(lambda: stdout.readline(4096), ""):
            sys.stdout.write(line)
            sys.stdout.flush()
        for line in iter(lambda: stderr.readline(4096), ""):
            sys.stderr.write(line)
            sys.stderr.flush()
        rc = stdout.channel.recv_exit_status()
        print(f"[exit] {rc}")
        return rc
    finally:
        client.close()


def cmd_healthcheck(url):
    import urllib.request
    import urllib.error

    deadline = time.time() + 60
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    print(f"[OK] {url} -> 200 (attempt {attempt})")
                    return 0
                print(f"[wait] {url} -> {resp.status} (attempt {attempt})")
        except urllib.error.URLError as exc:
            print(f"[wait] {url} -> {exc} (attempt {attempt})")
        time.sleep(2)
    print(f"[FAIL] {url} never returned 200 within 60s", file=sys.stderr)
    return 4


def cmd_healthcheck_remote(url):
    """从 CVM 内部 curl 该 URL(取代/补充 cmd_healthcheck 的本地视角)。

    用途:捕获 gunicorn 没起来、端口未绑定,但本地反代仍能 200 这种本地视角假绿的情况。
    """
    quoted = shlex.quote(url)
    deadline = time.time() + 60
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        client = _connect()
        try:
            stdin, stdout, stderr = client.exec_command(
                f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 {quoted}",
                timeout=10,
            )
            code = stdout.read().decode().strip() or "ERR"
            err = stderr.read().decode().strip()
            label = f"{code}{(' err=' + err) if err else ''}"
            if code == "200":
                print(f"[OK] {url} -> 200 from CVM (attempt {attempt})")
                return 0
            print(f"[wait] {url} -> {label} (attempt {attempt})")
        finally:
            client.close()
        time.sleep(2)
    print(f"[FAIL] {url} never returned 200 from CVM within 60s", file=sys.stderr)
    return 4


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 64

    action, args = argv[1], argv[2:]
    if action == "upload":
        if len(args) != 2:
            print("usage: _ssh.py upload <local> <remote>", file=sys.stderr)
            return 64
        return cmd_upload(args[0], args[1])
    if action == "backup":
        if len(args) != 1:
            print("usage: _ssh.py backup <remote_db_path>", file=sys.stderr)
            return 64
        return cmd_backup(args[0])
    if action == "exec":
        if len(args) != 1:
            print("usage: _ssh.py exec \"<remote shell command>\"", file=sys.stderr)
            return 64
        return cmd_exec(args[0])
    if action == "healthcheck":
        if len(args) != 1:
            print("usage: _ssh.py healthcheck <url>", file=sys.stderr)
            return 64
        return cmd_healthcheck(args[0])
    if action == "healthcheck-remote":
        if len(args) != 1:
            print("usage: _ssh.py healthcheck-remote <url>", file=sys.stderr)
            return 64
        return cmd_healthcheck_remote(args[0])

    print(f"[ERR] unknown action: {action}", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))