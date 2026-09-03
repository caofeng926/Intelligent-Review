#!/usr/bin/env bash
# 部署脚本: 医保智审规则库 → 腾讯云 CVM
# 用法:
#   export MA_SSH_PASS='<your password>'
#   bash scripts/deploy_now.sh

set -euo pipefail

REMOTE_HOST="132.232.152.250"
REMOTE_PORT="2222"
REMOTE_USER="ubuntu"
REMOTE_DIR="/opt/medical-audit"

if [[ -z "${MA_SSH_PASS:-}" ]]; then
  echo "❌ 请先设置 MA_SSH_PASS 环境变量"
  echo "   export MA_SSH_PASS='<your ssh password>'"
  exit 1
fi

# SSH 选项 (无 sudoers, 用密码登后 sudo -S)
# Audit 2026-09-03 C3: 已移除 -o StrictHostKeyChecking=no (依赖 ~/.ssh/known_hosts 预 pin)
SSH_BASE=(ssh -p "$REMOTE_PORT" "$REMOTE_USER@$REMOTE_HOST")
SUDO_CMD=(sudo -S)
SUDO_FEED="echo '$MA_SSH_PASS' | sudo -S -p ''"

run_sudo() {
  echo "$MA_SSH_PASS" | "${SSH_BASE[@]}" "sudo -S -p '' $*" 2>/dev/null
}

echo "=== 1. 测试连通性 ==="
"${SSH_BASE[@]}" 'echo OK; whoami; date' || { echo "❌ SSH 失败"; exit 1; }

echo ""
echo "=== 2. rsync 代码 (排除 kp.db) ==="
rsync -av --delete \
  --exclude='data/kp.db' \
  --exclude='data/kp.db-shm' \
  --exclude='data/kp.db-wal' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  # Audit C3: 不再 disable host key verification
  -e "ssh -p $REMOTE_PORT" \
  deploy_artifacts/webapp/ \
  "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/webapp/"

echo ""
echo "=== 3. 健康检查 (重启前) ==="
HTTP_BEFORE=$(curl -s -o /dev/null -w "%{http_code}" "http://$REMOTE_HOST:5000/" || echo "000")
echo "重启前 HTTP 状态: $HTTP_BEFORE"

echo ""
echo "=== 4. 重启 medical-audit.service ==="
run_sudo "systemctl restart medical-audit.service" || true
sleep 2
run_sudo "systemctl status medical-audit.service --no-pager -l" | head -20 || true

echo ""
echo "=== 5. 健康检查 (重启后) ==="
sleep 3
HTTP_AFTER=$(curl -s -o /dev/null -w "%{http_code}" "http://$REMOTE_HOST:5000/" || echo "000")
echo "重启后 HTTP 状态: $HTTP_AFTER"

echo ""
echo "=== 6. 冒烟测试 ==="
for path in "/" "/api/stats" "/search" "/search/yp" "/api/nhsa/yp/search?q=%E9%98%BF" "/api/nhsa/hc/search?q=%E5%BF%83"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://$REMOTE_HOST:5000$path" || echo "000")
  printf "  %-50s → %s\n" "$path" "$code"
done

echo ""
echo "=== 7. 日志最后 20 行 ==="
run_sudo "journalctl -u medical-audit -n 20 --no-pager" || true

echo ""
echo "✅ 部署完成"
echo "   访问: http://$REMOTE_HOST:5000/"
