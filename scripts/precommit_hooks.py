"""Custom pre-commit hooks (avoid bash dep for cross-platform reliability)."""
import re
import subprocess
import sys


def no_bak_files():
    """Block staging of any *.bak file."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    bad = [n for n in out.splitlines() if n.endswith(".bak") or ".bak." in n]
    if bad:
        sys.stderr.buffer.write("\u9519\u8bef\uff1a\u7981\u6b62\u63d0\u4ea4 .bak \u5907\u4efd\u6587\u4ef6\u3002\u8bf7\u5148\u6e05\u7406\n".encode("utf-8"))
        for b in bad:
            sys.stderr.buffer.write(f"  {b}\n".encode("utf-8"))
        sys.exit(1)


# 路径里出现这些的整段 diff 跳过 — 用于排除 hook 自身 / 测试 fixture 等
_PASSWORD_SKIP_PATHS = (
    "scripts/precommit_hooks.py",
)


def no_hardcoded_password():
    """Block obvious hard-coded password assignments in staged diff."""
    out = subprocess.run(
        ["git", "diff", "--cached", "-U0"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    # 过滤掉白名单路径的 hunk
    filtered_lines = []
    skip = False
    for line in out.splitlines(keepends=True):
        if line.startswith("diff --git"):
            skip = any(p in line for p in _PASSWORD_SKIP_PATHS)
        if not skip:
            filtered_lines.append(line)
    out = "".join(filtered_lines)
    pat = re.compile(
        # match added lines that contain password/passwd/pass = "...."
        # use triple-quoted raw string so we can include both ' and " literally
        r"""^\+(?=.*\b(?:password|passwd|pass)\b)[^\n]*?"""
        r"""(?:password|passwd|pass)\s*=\s*['\"][^'\"]{4,}""",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pat.search(out)
    if m:
        snip = m.group(0)[:200].replace("\n", " ")
        # 用 sys.stderr.buffer.write 以保证 Windows GBK 控制台也能正确输出非 ASCII
        msg = ("错误：检测到硬编码密码: " + snip + "\n⚠️  请使用环境变量 (env var) 或 secrets 管理。\n").encode("utf-8")
        sys.stderr.buffer.write(msg)
        sys.exit(1)





if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "no_bak_files":
        no_bak_files()
    elif cmd == "no_hardcoded_password":
        no_hardcoded_password()
    else:
        print(f"unknown cmd: {cmd}", file=sys.stderr)
        sys.exit(2)
