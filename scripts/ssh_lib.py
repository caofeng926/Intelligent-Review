"""Shared SSH helpers used by sync/upload deploy scripts.

Security defaults (audit 2026-09-03 C3):
  - RejectPolicy() instead of AutoAddPolicy()
  - load_host_keys from ~/.ssh/known_hosts
  - MA_SSH_USER defaults to "ubuntu" (was inconsistent: root/ubuntu)
  - MA_SSH_HOST default = 132.232.152.250 (audit L2: extract to env)
  - MA_SSH_PORT default = 2222

Environment variables:
  MA_SSH_HOST   - server hostname/IP     (default: 132.232.152.250)
  MA_SSH_PORT   - SSH port                (default: 2222)
  MA_SSH_USER   - SSH user                (default: ubuntu)
  MA_SSH_PASS   - SSH password            (REQUIRED, no default; or use ssh-agent keys)
  MA_SSH_KEY    - path to SSH private key  (preferred; overrides MA_SSH_PASS)
  MA_SSH_TRUST_HOST=1 - if set, auto-trust unknown host (FIRST-TIME SETUP ONLY;
                                                  emits a loud warning; never use in prod)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko


DEFAULT_HOST = "132.232.152.250"
DEFAULT_PORT = "2222"
DEFAULT_USER = "ubuntu"


def _host():
    return os.environ.get("MA_SSH_HOST", DEFAULT_HOST)


def _port():
    return int(os.environ.get("MA_SSH_PORT", DEFAULT_PORT))


def _user():
    return os.environ.get("MA_SSH_USER", DEFAULT_USER)


def _connect():
    """Open a Paramiko SSHClient with hardened defaults.

    Returns:
        paramiko.SSHClient

    Raises:
        SystemExit on missing credentials or host-key mismatch.
    """
    host = _host()
    port = _port()
    user = _user()
    password = os.environ.get("MA_SSH_PASS")
    key_path = os.environ.get("MA_SSH_KEY")

    if not password and not key_path:
        sys.exit(
            "需要设置 MA_SSH_PASS 或 MA_SSH_KEY 环境变量\n"
            "  推荐: export MA_SSH_KEY=~/.ssh/id_ed25519_medical_audit"
        )

    client = paramiko.SSHClient()

    # 1. 加载已信任的 known_hosts
    known_hosts_path = Path.home() / ".ssh" / "known_hosts"
    if known_hosts_path.exists():
        try:
            client.load_host_keys(str(known_hosts_path))
        except Exception as e:
            print(f"[warn] failed to load {known_hosts_path}: {e}", file=sys.stderr)

    # 2. 主机密钥策略: 优先 RejectPolicy,首次连接可显式 opt-in
    if os.environ.get("MA_SSH_TRUST_HOST") == "1":
        print(
            f"[WARN] MA_SSH_TRUST_HOST=1 -- auto-trusting {host}:{port} host key.",
            file=sys.stderr,
        )
        print(
            "[WARN] 仅在首次部署时使用!  之后请把指纹 pin 到 ~/.ssh/known_hosts 并取消此变量.",
            file=sys.stderr,
        )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

    # 3. 认证
    connect_kwargs = {
        "hostname": host,
        "port": port,
        "username": user,
        "timeout": 30,
        "banner_timeout": 30,
        "auth_timeout": 30,
    }
    if key_path:
        pkey = paramiko.Ed25519Key.from_private_key_file(key_path)
        connect_kwargs["pkey"] = pkey
    else:
        connect_kwargs["password"] = password

    client.connect(**connect_kwargs)
    return client
