"""恢复同步:SSH 通了之后,跑这个把本地新代码/数据库推到 CVM。

前置: 确保 132.232.152.250:22 沙箱已能连通(本沙箱目前被封,需等待)。

执行:
    python -X utf8 scripts/sync_yp2023_to_cvm.py
"""
import paramiko, os, hashlib, time, posixpath, sys

HOST = "132.232.152.250"
USER = "root"
PASS = os.environ.get("MA_SSH_PASS", "")
if not PASS:
    raise SystemExit("MA_SSH_PASS env var required")
REMOTE_DIR = "/opt/medical-audit/webapp"

def md5_local(p):
    if not os.path.exists(p): return None
    h = hashlib.md5()
    with open(p, "rb") as f:
        while True:
            c = f.read(1024 * 1024)
            if not c: break
            h.update(c)
    return h.hexdigest()

def md5_remote(ssh, p):
    sin, sout, serr = ssh.exec_command(f"md5sum {p}", timeout=60)
    o = sout.read().decode().strip()
    return o.split()[0] if o else None

def main():
    print(f"连接 {HOST}:22 ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, port=22, username=USER, password=PASS, timeout=15)
    except Exception as e:
        print(f"FAIL: {e}")
        print("如果是被 fail2ban / 沙箱封禁 — 等待数小时或换 SSH 密钥")
        sys.exit(1)
    print("已连接")
    sftp = ssh.open_sftp()
    sftp.chdir(REMOTE_DIR)

    # 备份远端 kp.db
    stamp = time.strftime("%Y%m%d_%H%M%S")
    print(f"备份远端 kp.db -> kp.db.bak.{stamp}")
    ssh.exec_command(f"mv {REMOTE_DIR}/data/kp.db {REMOTE_DIR}/data/kp.db.bak.{stamp}")
    time.sleep(1)

    # 上传代码
    files = [
        ("webapp/app.py", f"{REMOTE_DIR}/app.py"),
        ("webapp/yp2023.py", f"{REMOTE_DIR}/yp2023.py"),
        ("webapp/ingest_yp_2023.py", f"{REMOTE_DIR}/ingest_yp_2023.py"),
        ("webapp/templates/home.html", f"{REMOTE_DIR}/templates/home.html"),
        ("webapp/templates/yp2023.html", f"{REMOTE_DIR}/templates/yp2023.html"),
        ("webapp/templates/yp2023_detail.html", f"{REMOTE_DIR}/templates/yp2023_detail.html"),
    ]
    print("上传 6 个代码文件...")
    for lcl, rmt in files:
        sftp.put(lcl, rmt)
        print(f"  OK {lcl} -> {rmt}")

    # 上传新 kp.db
    print("上传新 kp.db (434 MB)...")
    t0 = time.time()
    sftp.put("webapp/data/kp.db", f"{REMOTE_DIR}/data/kp.db.tmp")
    print(f"  OK 用时 {time.time()-t0:.1f}s")

    # Swap + 重启
    print("Swap kp.db + 重启服务")
    ssh.exec_command(f"cd {REMOTE_DIR}/data && mv kp.db.tmp kp.db && chown root:root kp.db")
    ssh.exec_command("systemctl restart medical-audit.service", timeout=30)
    time.sleep(6)

    # 验证
    print("验证")
    for cmd in [
        "systemctl is-active medical-audit.service",
        "curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/yp2023",
        "curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/api/yp2023/stats",
    ]:
        sin, sout, _ = ssh.exec_command(cmd, timeout=15)
        print(f"  $ {cmd[:60]} -> {sout.read().decode().strip()}")
    sftp.close()
    ssh.close()
    print("\u2705 部署完成")

if __name__ == "__main__":
    main()
