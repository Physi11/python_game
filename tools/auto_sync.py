"""代码变动时自动提交并推送。

工作原理
--------
轮询 ``git status --porcelain``：一旦工作区变脏，并且**连续若干秒没有新改动**
（防抖，避免一个函数改十次就提交十次），就自动 ``git add -A`` → 生成变更日志 →
``git commit`` → ``git push``。

为什么用 ``git status`` 而不是自己遍历文件：
它天然遵守 ``.gitignore``，还能正确处理删除、重命名、二进制文件，
不必在脚本里重复维护一份排除规则。

用法::

    python tools/auto_sync.py                # 常驻监听，Ctrl+C 退出
    python tools/auto_sync.py --quiet 30     # 静默 30 秒再提交
    python tools/auto_sync.py --once         # 只同步一次（适合定时任务）
    python tools/auto_sync.py --dry-run      # 只打印将要提交的内容
    python tools/auto_sync.py --note "修了什么"

想给某次自动提交写上"为什么改"，除了 ``--note``，也可以在项目根目录放一个
``SYNC_NOTE.txt``，脚本会读走内容并删除该文件。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / ".git" / "auto_sync.log"
NOTE_FILE = ROOT / "SYNC_NOTE.txt"

# porcelain 状态码 → 中文说明
STATUS_TEXT = {
    "A": "新增",
    "M": "修改",
    "D": "删除",
    "R": "重命名",
    "C": "复制",
    "T": "类型变更",
    "U": "冲突",
    "?": "未跟踪",
}


class SyncError(RuntimeError):
    """同步流程中的可预期错误（没有仓库、没有远程、推送失败等）。"""


# ------------------------------------------------------------------ 基础工具
def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """在项目根目录执行一条 git 命令。"""
    result = subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise SyncError(
            f"git {' '.join(args)} 失败：{(result.stderr or result.stdout).strip()[:300]}"
        )
    return result


def log(message: str) -> None:
    """同时输出到控制台和 ``.git/auto_sync.log``。"""
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:      # 日志写不了不影响主流程
        pass


def require_repo() -> None:
    """确认当前目录是 git 仓库且配好了远程。"""
    if git("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        raise SyncError("当前目录不是 git 仓库，请先执行 git init")
    if not git("remote", check=False).stdout.strip():
        raise SyncError("还没有配置远程仓库，请先执行 git remote add origin <地址>")


# ------------------------------------------------------------------ 变更采集
def status_text() -> str:
    """工作区的脏状态。空字符串表示干净。"""
    return git("status", "--porcelain").stdout.strip()


def staged_changes() -> list[dict]:
    """读取已暂存的文件及其增删行数。"""
    status_map: dict[str, str] = {}
    for line in git("diff", "--cached", "--name-status").stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            status_map[parts[-1]] = parts[0][0]

    changes: list[dict] = []
    for line in git("diff", "--cached", "--numstat").stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], parts[2]
        changes.append(
            {
                "path": path,
                "status": status_map.get(path, "M"),
                # 二进制文件 git 会给 "-" 而不是数字
                "add": None if added == "-" else int(added),
                "delete": None if deleted == "-" else int(deleted),
            }
        )
    return changes


def modules_of(changes: list[dict]) -> list[str]:
    """从文件路径里提取一级目录，作为"这次改了哪几个模块"。"""
    seen: list[str] = []
    for item in changes:
        parts = Path(item["path"]).parts
        name = parts[0] if len(parts) > 1 else "根目录"
        if name not in seen:
            seen.append(name)
    return seen


def build_message(changes: list[dict], note: str) -> str:
    """按 Conventional Commits 生成提交信息。"""
    modules = modules_of(changes)
    module_text = "、".join(modules[:3]) + ("等" if len(modules) > 3 else "")
    subject = f"chore(sync): 同步 {len(changes)} 个文件（{module_text}）"

    width = min(44, max(len(item["path"]) for item in changes))
    details: list[str] = []
    total_add = total_del = 0
    for item in changes:
        label = STATUS_TEXT.get(item["status"], "修改")
        if item["add"] is None:
            stat = "二进制"
        else:
            stat = f"+{item['add']} -{item['delete']}"
            total_add += item["add"]
            total_del += item["delete"]
        details.append(f"- {label}  {item['path']:<{width}}  {stat}")

    lines = [subject, "", "改动明细：", *details, ""]
    lines.append(f"涉及模块：{module_text}")
    lines.append(f"合计：{len(changes)} 个文件，+{total_add} -{total_del}")
    lines.append(f"目的：{note or '例行保存自动提交'}")
    return "\n".join(lines)


# ------------------------------------------------------------------ 提交与推送
def push() -> None:
    """推送到远程；首次推送自动建立上游关联。"""
    has_upstream = (
        git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False).returncode
        == 0
    )
    args = ["push"] if has_upstream else ["push", "-u", "origin", "HEAD"]
    result = git(*args, check=False)
    if result.returncode != 0:
        raise SyncError(f"推送失败：{(result.stderr or result.stdout).strip()[:300]}")


def sync_once(note: str, dry_run: bool = False) -> bool:
    """执行一次"暂存 → 提交 → 推送"。返回是否真的产生了提交。"""
    require_repo()
    git("add", "-A")

    changes = staged_changes()
    if not changes:
        log("没有需要提交的改动")
        return False

    message = build_message(changes, note)
    if dry_run:
        print("\n--- 将要提交的内容 ---")
        print(message)
        print("--- 结束（dry-run，未提交）---\n")
        git("reset", check=False)     # 撤销暂存，避免留下副作用
        return False

    git("commit", "-m", message)
    log(f"已提交 {len(changes)} 个文件")
    push()
    log("已推送到远程")
    return True


def watch(interval: float, quiet: float, note_box: "NoteBox") -> None:
    """常驻监听：工作区变脏且稳定 ``quiet`` 秒后自动提交。"""
    log(f"开始监听（轮询 {interval:g}s，静默 {quiet:g}s 后提交）。Ctrl+C 退出。")
    last_status = status_text()
    changed_at = time.time()
    if last_status:
        log("启动时已有未提交改动，等待稳定…")

    while True:
        time.sleep(interval)
        current = status_text()
        if current != last_status:
            last_status = current
            changed_at = time.time()
            if current:
                log("检测到改动，等待稳定…")
            continue
        if not current:
            continue
        if time.time() - changed_at < quiet:
            continue
        try:
            sync_once(note_box.take())
        except SyncError as exc:
            log(f"同步失败：{exc}")
        last_status = status_text()
        changed_at = time.time()


class NoteBox:
    """管理"这次提交的目的"：优先读 SYNC_NOTE.txt，其次用 --note。"""

    def __init__(self, pending: str = "") -> None:
        self._pending = pending.strip()

    def take(self) -> str:
        if NOTE_FILE.exists():
            try:
                text = NOTE_FILE.read_text(encoding="utf-8").strip()
                NOTE_FILE.unlink()      # 读走即删，避免同一条说明被重复使用
            except OSError:
                text = ""
            if text:
                self._pending = ""      # 文件优先，本次忽略 --note
                return text
        text, self._pending = self._pending, ""
        return text


# ------------------------------------------------------------------ 入口
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="代码变动时自动提交并推送")
    parser.add_argument("--once", action="store_true", help="只同步一次后退出")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要提交的内容")
    parser.add_argument("--interval", type=float, default=3.0, help="轮询间隔秒数（默认 3）")
    parser.add_argument("--quiet", type=float, default=20.0, help="静默多少秒后提交（默认 20）")
    parser.add_argument("--note", default="", help="本次提交的目的说明")
    args = parser.parse_args(argv)

    try:
        git("config", "core.quotepath", "false")   # 中文文件名不要变成 \344\270\255
        require_repo()
    except SyncError as exc:
        log(f"启动失败：{exc}")
        return 1

    if args.once or args.dry_run:
        try:
            sync_once(args.note, dry_run=args.dry_run)
        except SyncError as exc:
            log(f"同步失败：{exc}")
            return 1
        return 0

    try:
        watch(args.interval, args.quiet, NoteBox(args.note))
    except KeyboardInterrupt:
        log("已停止监听")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
