"""
一键部署 /nhsa/ms 国家版分类修复到 Tencent CVM (ubuntu@132.232.152.250:2222)。包含三步:
  1. SCP 同步 3 个改动文件
  2. SSH 重启 medical-audit 服务 (前端立刻生效)
  3. SSH 重跑 ingest_nhsa_dbs (数据库 level 列更新, 持久化修复)

用法 (PowerShell):
  $env:MA_SSH_PASS = "<password>"
  python webapp\deploy_ms_fix.py

要求环境变量:
  MA_SSH_PASS   : SSH ubuntu 密码
  MA_SSH_USER   : SSH 用户名 (默认 ubuntu)
可选 (默认已设):
  MA_SSH_HOST   : 默认 132.232.152.250
  MA_SSH_PORT   : 默认 2222
  MA_DEPLOY_DIR : 默认 /opt/medical-audit/webapp
"""
from __future__ import annotations
import os, sys, time, pathlib

import paramiko

LOCAL_REPO = pathlib.Path(__file__).resolve().parent.parent
CHANGED = [
    "webapp/ingest_nhsa_dbs.py",
    "webapp/nhsa_browse.py",
    "webapp/templates/ms.html",
]

HOST = os.environ.get("MA_SSH_HOST", "132.232.152.250")
PORT = int(os.environ.get("MA_SSH_PORT", "2222"))
USER = os.environ.get("MA_SSH_USER", "ubuntu")
PASS = os.environ.get("MA_SSH_PASS")
DEPLOY_DIR = os.environ.get("MA_DEPLOY_DIR", "/opt/medical-audit/webapp")


def main():
    if not PASS:
        sys.exit("需要设置环境变量 MA_SSH_PASS 才能部署")
    print(f"[deploy] target = {USER}@{HOST}:{DEPLOY_DIR}")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
    sftp = ssh.open_sftp()

    # 1) 同步文件
    for rel in CHANGED:
        local = LOCAL_REPO / rel
        remote = f"{DEPLOY_DIR}/{rel}"
        print(f"[deploy] put {local} -> {remote}")
        try:
            sftp.stat(remote).st_mode
        except IOError:
            remote_dir = os.path.dirname(remote)
            try:
                sftp.stat(remote_dir)
            except IOError:
                stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {os.path.dirname(remote_dir)} && mkdir -p {remote_dir}")
                stdout.read()
        sftp.put(str(local), remote)
    sftp.close()

    def run(cmd: str):
        print(f"[deploy] ssh> {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
        out, err = stdout.read().decode("utf-8", "replace"), stderr.read().decode("utf-8", "replace")
        if out:
            print(out)
        if err:
            print("(err)", err)
        return out

    # 2) 重启服务 (前端立刻生效)
    run("systemctl restart medical-audit.service")
    time.sleep(2)
    run("systemctl status medical-audit.service --no-pager | head -20 || true")

    # 3) 重跑 ingest 让数据库 level 列更新
    run(f"cd {DEPLOY_DIR} && python -m webapp.ingest_nhsa_dbs 2>&1 | tail -40")

    # 4) 验证
    run("curl -s -o /dev/null -w 'http_code=%{http_code} time=%{time_total}s\n' http://localhost:5000/nhsa/ms")

    ssh.close()
    print("[deploy] done.")


if __name__ == "__main__":
    main()