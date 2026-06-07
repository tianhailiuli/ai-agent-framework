"""
Unified launcher for AI Agent Framework.

Usage:
    python -m ai_agent_framework.launch        # Start server on default port
    python -m ai_agent_framework.launch --port 8080
    python -m ai_agent_framework.launch --foreground
    python -m ai_agent_framework.launch --killall
"""

import argparse
import subprocess
import sys
import os

from ai_agent_framework.utils.port_guard import cleanup_port, find_free_port, register_exit_handler


def kill_all_python():
    """Nuclear option: kill all python.exe / pythonw.exe processes."""
    print("[Launch] Killing all Python processes...")
    my_pid = os.getpid()
    try:
        import psutil
        count = 0
        for p in psutil.process_iter(["pid", "name"]):
            name = p.info["name"].lower()
            pid = p.info["pid"]
            if pid == my_pid:
                continue
            if name in ("python.exe", "pythonw.exe"):
                try:
                    p.terminate()
                    p.wait(timeout=2)
                    count += 1
                except psutil.TimeoutExpired:
                    p.kill()
                    count += 1
                except psutil.NoSuchProcess:
                    pass
        print(f"[Launch] Terminated {count} Python process(es).")
    except ImportError:
        print("[Launch] psutil not available, falling back to taskkill...")
        subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe"], capture_output=True)
        print("[Launch] taskkill sent.")


def main():
    parser = argparse.ArgumentParser(description="AI Agent Framework Launcher")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    parser.add_argument("--killall", action="store_true", help="Kill all Python processes and exit")
    args = parser.parse_args()

    if args.killall:
        kill_all_python()
        return

    # Import config after potential --killall (avoids unnecessary imports)
    from ai_agent_framework import config

    port = args.port or config.FLASK_PORT
    host = config.FLASK_HOST

    # Cleanup port
    port_free = cleanup_port(port, verbose=True)
    if not port_free:
        new_port = find_free_port(start=port + 1)
        print(f"[Launch] Port {port} still occupied, auto-switching to {new_port}")
        port = new_port

    register_exit_handler()

    if args.foreground:
        print(f"[Launch] Starting server on http://{host}:{port} (foreground)")
        from ai_agent_framework.web.app import app
        app.run(host=host, port=port, debug=config.FLASK_DEBUG, threaded=True)
    else:
        print(f"[Launch] Starting server on http://{host}:{port} (background)")
        log_file = "server.log"
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.dirname(pkg_dir)
        root_dir = os.path.dirname(src_dir)
        proc = subprocess.Popen(
            [sys.executable, "-c",
             f"""
import sys
sys.path.insert(0, r'{src_dir}')
from ai_agent_framework.web.app import app
from ai_agent_framework import config
from ai_agent_framework.utils.port_guard import register_exit_handler
register_exit_handler()
app.run(host='{host}', port={port}, debug=config.FLASK_DEBUG, threaded=True)
"""],
            stdout=open(log_file, "w"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        print(f"[Launch] Server PID: {proc.pid}")
        print(f"[Launch] Logs: {log_file}")
        print(f"[Launch] Stop with: python -m ai_agent_framework.launch --killall")


if __name__ == "__main__":
    main()
