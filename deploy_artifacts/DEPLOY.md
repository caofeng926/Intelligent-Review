# Deploy to Chengdu server

Server: `ubuntu@132.232.152.250:2222`  (Ubuntu, OpenSSH 9.6p1)
**2026-07-18 修正**：原 `root@43.136.175.219` 不可达（IP 已变或服务器迁移），
正确地址是 `132.232.152.250`，SSH 端口 **2222**（22 关），用户 `ubuntu`。

## After server reboot

```bash
ssh -p 2222 ubuntu@132.232.152.250
sudo apt-get install -y python3-venv python3-pip  # skip apt-get update to avoid hangs
sudo mkdir -p /opt/medical-audit
```

## Upload from local

```bash
rsync -avz --delete -e "ssh -p 2222" \
  deploy_artifacts/webapp/ \
  ubuntu@132.232.152.250:/opt/medical-audit/webapp/

scp -P 2222 deploy_artifacts/medical-audit.service \
  ubuntu@132.232.152.250:/etc/systemd/system/medical-audit.service
scp -P 2222 deploy_artifacts/start.sh \
  ubuntu@132.232.152.250:/opt/medical-audit/start.sh
```

## First-time venv + start

```bash
ssh -p 2222 ubuntu@132.232.152.250
cd /opt/medical-audit
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r webapp/requirements.txt
chmod +x start.sh

sudo systemctl daemon-reload
sudo systemctl enable --now medical-audit
sudo systemctl status medical-audit
```

## Verify

```bash
curl -s http://127.0.0.1:5000/ | head -5
curl -s 'http://127.0.0.1:5000/api/search?q=丹参&mode=auto' | head -c 300
curl -s http://127.0.0.1:5000/api/stats | head -c 300   # V1.0 mini-app
curl -s http://127.0.0.1:5000/api/hot-queries?limit=5   # V1.1 mini-app
```

## Logs / restart

```bash
journalctl -u medical-audit -f
sudo systemctl restart medical-audit
```