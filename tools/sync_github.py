# -*- coding: utf-8 -*-
"""
把最新的项目推到 GitHub：整体替换仓库内容（旧文件自动删除），只保留一条提交。

用法：
    python sync_github.py <仓库URL>            # 首次 / 换仓库
    python sync_github.py                       # 之后同步（沿用上次记录的 remote）
    python sync_github.py --keep                # 不重新清空导出目录，直接用现有内容推

鉴权（二选一）：
    · 环境变量 GITHUB_TOKEN 里放 Personal Access Token（推荐，不落盘）
    · 或者 URL 里直接带 token：https://<token>@github.com/<user>/<repo>.git
      （注意别把这个 URL 提交到仓库里）

行为：
    1. 调 build_github_export.py 重新生成导出目录（先清空，旧内容即被删除）
    2. 在该目录里 orphan 出一个只有一次提交的新分支，force push 到 main
       —— 于是仓库里永远只有「最新版」这一份内容，旧版本自动消失。
"""
import io, os, subprocess, sys

BASE = "C:/Users/Administrator/WorkBuddy/2026-09-13-03-27-43/kindle_dashboard"
DST = "C:/Users/Administrator/WorkBuddy/2026-09-13-03-27-43/kindle_dashboard_github"
EXPORT = os.path.join(BASE, "build_github_export.py")
PY = "C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
# 沙箱里 git 不在 PATH 上，用 PortableGit 的绝对路径
GIT = "C:/Users/Administrator/.workbuddy/binaries/PortableGit/versions/1.2.0/cmd/git.exe"
# remote 记录放在导出目录**外面**，否则会被 git add -A 一起提交进仓库
REMOTE_FILE = os.path.join(BASE, ".sync_remote")
BRANCH = "main"

args = [a for a in sys.argv[1:] if not a.startswith("--")]
KEEP = "--keep" in sys.argv


def run(cmd, cwd=None, quiet=False):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0 and not quiet:
        print("命令失败:", " ".join(cmd))
        print((r.stdout or "")[-800:])
        print((r.stderr or "")[-800:])
        sys.exit(r.returncode)
    return r


# ---- 1. 重新生成导出（清空 = 旧文件删除） ----
print("== 1/4 重新生成导出目录 ==")
cmd = [PY, EXPORT] + (["--keep"] if KEEP else [])
r = subprocess.run(cmd, capture_output=True, text=True)
print((r.stdout or "")[-800:])
if r.returncode != 0:
    print((r.stderr or "")[-800:])
    sys.exit(r.returncode)

# ---- 2. 确定 remote ----
remote = args[0] if args else None
if not remote and os.path.exists(REMOTE_FILE):
    remote = io.open(REMOTE_FILE, encoding="utf-8").read().strip()
if not remote:
    print("没有仓库地址。用法：python sync_github.py https://github.com/<user>/<repo>.git")
    sys.exit(1)
token = os.environ.get("GITHUB_TOKEN", "")
push_url = remote
if token and remote.startswith("https://") and "@" not in remote:
    push_url = remote.replace("https://", "https://%s@" % token)
io.open(REMOTE_FILE, "w", encoding="utf-8").write(remote)   # 只存不带 token 的地址
print("== 2/4 remote ==", remote)

# ---- 3. orphan 提交（仓库里只留最新这一版） ----
print("== 3/4 生成单次提交 ==")
if not os.path.isdir(os.path.join(DST, ".git")):
    run([GIT, "init", "-b", BRANCH], cwd=DST)
run([GIT, "add", "-A"], cwd=DST)
run([GIT, "-c", "user.name=WATERS", "-c", "user.email=waters@local",
     "commit", "-m", "水哥拯救墨水屏：同步最新版本（整体替换，旧内容已删除）",
     "--allow-empty"], cwd=DST, quiet=True)
run([GIT, "checkout", "--orphan", "latest"], cwd=DST, quiet=True)
run([GIT, "add", "-A"], cwd=DST)
run([GIT, "-c", "user.name=WATERS", "-c", "user.email=waters@local",
     "commit", "-m", "水哥拯救墨水屏：同步最新版本（整体替换，旧内容已删除）"], cwd=DST)
run([GIT, "branch", "-M", BRANCH], cwd=DST, quiet=True)

# ---- 4. force push ----
print("== 4/4 推送（force） ==")
r = run([GIT, "push", "-f", push_url, BRANCH], cwd=DST, quiet=True)
if r.returncode != 0:
    print((r.stdout or "")[-600:])
    print((r.stderr or "")[-800:])
    print("\n推送失败。常见原因：")
    print("  · 没有鉴权：设置环境变量 GITHUB_TOKEN，或把 token 写进仓库 URL")
    print("  · 仓库不存在：先在 GitHub 上建一个空仓库（不要勾选初始化 README）")
    sys.exit(1)
print((r.stdout or "")[-400:])
print((r.stderr or "")[-400:])
print("\n同步完成 ->", remote)
