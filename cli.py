#!/usr/bin/env python3
"""clark CLI — scaffold modules and manage the project.

Usage:
    python cli.py make module --name weather
    python cli.py start | stop | status
    python cli.py deploy service
    python cli.py install-skill agent --openclaw
    python cli.py uninstall-skill agent --openclaw

Commands:
    make module          Create a new module with boilerplate files
    start                Start clark server as a background process
    stop                 Stop clark server gracefully
    status               Check clark server health
    deploy service       Generate systemd service file from template + clark.json
    install-skill agent  Install clark OpenClaw skill for agent discovery
    uninstall-skill agent  Remove clark OpenClaw skill
"""

import argparse
import json
import os
import pwd
import signal
import subprocess
import sys
import time
from pathlib import Path

from core.scaffolder import scaffold_module
from core.templates import render

HOST = "127.0.0.1"
PORT = "8124"
APP_DIR = Path(__file__).resolve().parent
PID_FILE = APP_DIR / "data" / "clark.pid"
LOG_FILE = APP_DIR / "data" / "clark.log"
VENV_PYTHON = APP_DIR / ".venv" / "bin" / "python"

# Paths for deploy generation
DEPLOY_TEMPLATE = APP_DIR / "deploy" / "clark.service.template"
DEPLOY_OUTPUT = APP_DIR / "deploy" / "clark.service"

# Skill paths
# Source: repo/openclaw/skills/clark/  (version-controlled)
# Target: ~/.openclaw/workspace/skills/clark/  (auto-discovered by OpenClaw)
SKILL_SOURCE = APP_DIR / "openclaw" / "skills" / "clark"
SKILL_TARGET = Path.home() / ".openclaw" / "workspace" / "skills" / "clark"


def _pid() -> int | None:
    """Read PID file, return PID if process is alive, else None."""
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return None


def cmd_make_module(args: argparse.Namespace) -> None:
    try:
        result = scaffold_module(
            name=args.name,
            description=args.desc,
            with_handler=args.with_handler,
            with_migration=args.with_migration,
        )
    except (ValueError, FileExistsError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ Module '{result['name']}' created\n")
    print("   Files created:")
    for f in result["files"]:
        print(f"     {f}")
    print()
    print("   Next steps:")
    print("     1. Edit the files above to add your logic")
    if result["config_updated"]:
        print('     2. Enable in clark.json → set "enabled": true')
    print("     3. Reload: curl -X POST http://localhost:8124/api/reload\n")


def cmd_start(_args: argparse.Namespace) -> None:
    pid = _pid()
    if pid is not None:
        print(f"clark is already running (PID: {pid})")
        return

    if not VENV_PYTHON.exists():
        print("❌ .venv not found. Run: uv sync", file=sys.stderr)
        sys.exit(1)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(LOG_FILE, "w") as log:
        proc = subprocess.Popen(
            [
                str(VENV_PYTHON),
                "-m", "uvicorn",
                "app.main:app",
                "--host", HOST,
                "--port", PORT,
                "--workers", "1",
                "--no-access-log",
            ],
            stdout=log,
            stderr=log,
            cwd=APP_DIR,
        )

    PID_FILE.write_text(str(proc.pid))

    time.sleep(2)
    if proc.poll() is None:
        print(f"✅ clark started (PID: {proc.pid}) — http://{HOST}:{PORT}")
    else:
        print(f"❌ clark failed to start — check {LOG_FILE}", file=sys.stderr)
        with open(LOG_FILE) as f:
            sys.stderr.write(f.read())
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)


def cmd_stop(_args: argparse.Namespace) -> None:
    pid = _pid()
    if pid is not None:
        print(f"Stopping clark (PID: {pid})…")
        os.kill(pid, signal.SIGTERM)

        for _ in range(5):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break

        try:
            os.kill(pid, 0)
            print("Force killing…")
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        PID_FILE.unlink(missing_ok=True)
        print("✅ clark stopped")
    else:
        try:
            subprocess.run(
                ["pkill", "-f", "uvicorn app.main:app"],
                capture_output=True,
            )
            print("✅ clark stopped (by process name)")
        except Exception:
            print("clark is not running")
        PID_FILE.unlink(missing_ok=True)


def cmd_status(_args: argparse.Namespace) -> None:
    import urllib.request

    pid = _pid()
    if pid is None:
        print("❌ clark is not running")
        print("   Start:  python cli.py start")
        sys.exit(1)

    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().split()
        print(f"  Process:   running  (PID: {pid})")
    except (FileNotFoundError, IndexError):
        print(f"  Process:   running  (PID: {pid})")

    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex((HOST, int(PORT)))
    sock.close()
    if result == 0:
        print(f"  Port:      {HOST}:{PORT}  (listening)")
    else:
        print(f"  Port:      {HOST}:{PORT}  (not listening — restart?)")
        sys.exit(1)

    try:
        resp = urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=3)
        data = json.loads(resp.read())
        print(f"  API:       healthy  (v{data.get('version', '?')})")
    except Exception:
        print("  API:       unreachable")
        sys.exit(1)

    try:
        resp = urllib.request.urlopen(f"http://{HOST}:{PORT}/api/modules", timeout=3)
        modules = json.loads(resp.read())
        enabled = [m["name"] for m in modules if m.get("config", {}).get("enabled")]
        if enabled:
            print(f"  Modules:   {', '.join(enabled)}")
    except Exception:
        pass


def _openclaw_skill_path() -> str | None:
    """Resolve the openclaw skills install command, or None if not found."""
    import shutil
    return shutil.which("openclaw")


def cmd_install_skill(args: argparse.Namespace) -> None:
    """Install clark skill for an agent platform.

    Currently supports:
      --openclaw   Uses native `openclaw skills install` (recommended)
    """
    if args.openclaw:
        cmd = _openclaw_skill_path()
        if cmd is None:
            print("❌ 'openclaw' command not found on PATH", file=sys.stderr)
            print("   Install OpenClaw first, or copy manually:")
            print(f"   cp -r {SKILL_SOURCE} {SKILL_TARGET}", file=sys.stderr)
            sys.exit(1)

        if not SKILL_SOURCE.exists():
            print(f"❌ Skill source not found: {SKILL_SOURCE}", file=sys.stderr)
            print("   Expected: openclaw/skills/clark/SKILL.md", file=sys.stderr)
            sys.exit(1)

        import subprocess
        result = subprocess.run(
            [cmd, "skills", "install", str(SKILL_SOURCE), "--as", "clark"],
            capture_output=True, text=True, cwd=APP_DIR,
        )
        if result.returncode == 0:
            print(f"✅ clark skill installed for OpenClaw")
            print(f"   ▶ New session → skill auto-discovered")
        else:
            print(f"❌ Install failed:", file=sys.stderr)
            print(result.stderr or result.stdout, file=sys.stderr)
            sys.exit(1)
    else:
        print("❌ Specify an agent platform: --openclaw", file=sys.stderr)
        sys.exit(1)


def cmd_uninstall_skill(args: argparse.Namespace) -> None:
    """Remove clark skill from the agent platform."""
    if args.openclaw:
        if not SKILL_TARGET.exists():
            print("clark skill is not installed for OpenClaw")
            return

        import shutil
        if SKILL_TARGET.is_dir():
            shutil.rmtree(SKILL_TARGET)
        else:
            SKILL_TARGET.unlink()

        print("✅ clark skill uninstalled from OpenClaw")
        print("   ▶ Effect on next session")
    else:
        print("❌ Specify an agent platform: --openclaw", file=sys.stderr)
        sys.exit(1)


def _load_deploy_config() -> dict:
    """Read deploy overrides from clark.json (optional).

    Returns a dict with keys:
        host, port, workers, memory_max, cpu_quota
    Falls back to cli.py constants if clark.json or deploy section missing.
    """
    config_path = APP_DIR / "clark.json"
    deploy_defaults = {
        "host": HOST,
        "port": PORT,
        "workers": "1",
        "memory_max": "256M",
        "cpu_quota": "50%",
    }

    if not config_path.exists():
        return deploy_defaults

    try:
        with open(config_path) as f:
            raw = json.load(f)
        deploy_cfg = raw.get("deploy", {})
        for key in deploy_defaults:
            val = deploy_cfg.get(key)
            if val is not None:
                deploy_defaults[key] = str(val)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  Warning: could not read clark.json deploy config: {e}", file=sys.stderr)

    return deploy_defaults


def cmd_deploy_service(_args: argparse.Namespace) -> None:
    """Generate deploy/clark.service from template + clark.json config."""
    if not DEPLOY_TEMPLATE.exists():
        print(f"❌ Template not found: {DEPLOY_TEMPLATE}", file=sys.stderr)
        sys.exit(1)

    # Read template
    template = DEPLOY_TEMPLATE.read_text()

    # Auto-detect user, paths
    current_user = pwd.getpwuid(os.getuid()).pw_name
    working_dir = str(APP_DIR)
    python_path = str(VENV_PYTHON)

    # Load deploy config overrides from clark.json
    deploy_cfg = _load_deploy_config()

    # Build render context
    ctx = {
        "user": current_user,
        "working_dir": working_dir,
        "python_path": python_path,
        "host": deploy_cfg["host"],
        "port": deploy_cfg["port"],
        "workers": deploy_cfg["workers"],
        "memory_max": deploy_cfg["memory_max"],
        "cpu_quota": deploy_cfg["cpu_quota"],
    }

    # Render and write
    output = render(template, ctx)
    DEPLOY_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEPLOY_OUTPUT.write_text(output)

    print(f"✅  {DEPLOY_OUTPUT} generated")
    print()
    print("   Variables:")
    for key, val in ctx.items():
        print(f"     {key}: {val}")
    print()
    print("   Next steps:")
    print("     sudo cp deploy/clark.service /etc/systemd/system/")
    print("     sudo systemctl daemon-reload")
    print("     sudo systemctl enable --now clark")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="clark",
        description="clark CLI — scaffold modules and manage your AI task backend.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    # `make` group
    make_parser = subparsers.add_parser("make", help="Create something new")
    make_sub = make_parser.add_subparsers(dest="type", required=True)

    module_parser = make_sub.add_parser("module", help="Create a new module")
    module_parser.add_argument("--name", required=True, help="Module name (lowercase, e.g. 'weather')")
    module_parser.add_argument("--desc", default="", help="Module description (optional)")
    module_parser.add_argument("--with-handler", action="store_true", help="Include job handler template")
    module_parser.add_argument("--with-migration", action="store_true", help="Include migration template")
    module_parser.set_defaults(func=cmd_make_module)

    # `start`
    start_parser = subparsers.add_parser("start", help="Start clark server as a background process")
    start_parser.set_defaults(func=cmd_start)

    # `stop`
    stop_parser = subparsers.add_parser("stop", help="Stop clark server gracefully")
    stop_parser.set_defaults(func=cmd_stop)

    # `status`
    status_parser = subparsers.add_parser("status", help="Check clark server health")
    status_parser.set_defaults(func=cmd_status)

    # `deploy` group
    deploy_parser = subparsers.add_parser("deploy", help="Generate deploy artifacts from template + clark.json")
    deploy_sub = deploy_parser.add_subparsers(dest="type", required=True)

    deploy_service_parser = deploy_sub.add_parser("service", help="Generate systemd service file")
    deploy_service_parser.set_defaults(func=cmd_deploy_service)

    # `install-skill agent` — platform-agnostic skill installation
    install_skill_parser = subparsers.add_parser("install-skill", help="Install clark skill for an agent platform")
    install_skill_sub = install_skill_parser.add_subparsers(dest="target", required=True)

    agent_install_parser = install_skill_sub.add_parser("agent", help="Install for an AI agent platform")
    agent_install_parser.add_argument("--openclaw", action="store_true", help="Install for OpenClaw (uses native openclaw skills install)")
    agent_install_parser.set_defaults(func=cmd_install_skill)

    # `uninstall-skill agent`
    uninstall_skill_parser = subparsers.add_parser("uninstall-skill", help="Remove clark skill from an agent platform")
    uninstall_skill_sub = uninstall_skill_parser.add_subparsers(dest="target", required=True)

    agent_uninstall_parser = uninstall_skill_sub.add_parser("agent", help="Remove from an AI agent platform")
    agent_uninstall_parser.add_argument("--openclaw", action="store_true", help="Remove from OpenClaw")
    agent_uninstall_parser.set_defaults(func=cmd_uninstall_skill)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
