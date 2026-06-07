"""Port guard — automatically kill zombie processes occupying the target port."""

import sys
import time
import signal
import subprocess

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def _get_pid_by_netstat(port: int) -> list[int]:
    """Fallback: use netstat to find PIDs listening on the port (Windows)."""
    pids = []
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, shell=False, timeout=10
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    try:
                        pids.append(int(parts[-1]))
                    except ValueError:
                        pass
    except Exception:
        pass
    return pids


def _kill_by_taskkill(pid: int) -> bool:
    """Kill a process by PID using taskkill (Windows fallback)."""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def cleanup_port(port: int, verbose: bool = True) -> bool:
    """
    Find and terminate any process listening on the given port.

    Returns True if the port is now free (or was already free).
    """
    pids_to_kill = set()

    # Strategy 1: psutil (most reliable, works cross-platform)
    if HAS_PSUTIL:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.status == "LISTEN" and conn.pid:
                pids_to_kill.add(conn.pid)
    else:
        # Strategy 2: netstat fallback (Windows mainly)
        if sys.platform == "win32":
            pids_to_kill.update(_get_pid_by_netstat(port))

    if not pids_to_kill:
        if verbose:
            print(f"[PortGuard] Port {port} is free.")
        return True

    killed = []
    for pid in pids_to_kill:
        # Don't kill ourselves
        if pid == 0 or (HAS_PSUTIL and pid == psutil.Process().pid):
            continue

        if HAS_PSUTIL:
            try:
                proc = psutil.Process(pid)
                name = proc.name()
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                    killed.append(f"{name}(pid={pid})")
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
                    killed.append(f"{name}(pid={pid}, forced)")
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                if verbose:
                    print(f"[PortGuard] Failed to kill pid={pid}: {e}")
        else:
            if _kill_by_taskkill(pid):
                killed.append(f"pid={pid}")

    # Give the OS a moment to release the socket
    time.sleep(0.5)

    # Verify the port is now free
    still_occupied = False
    if HAS_PSUTIL:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.status == "LISTEN":
                still_occupied = True
                break
    else:
        still_occupied = len(_get_pid_by_netstat(port)) > 0

    if killed and verbose:
        print(f"[PortGuard] Terminated processes on port {port}: {', '.join(killed)}")

    if still_occupied and verbose:
        print(f"[PortGuard] WARNING: Port {port} is still occupied after cleanup.")
        print(f"[PortGuard] Try running: python -c \"import psutil; [p.kill() for p in psutil.process_iter() if p.name().lower() in ('python.exe', 'pythonw.exe')]\"")
        return False

    return True


def find_free_port(start: int = 8080, end: int = 9999) -> int:
    """Find the first free port in the given range."""
    import socket
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No free port found in range {start}-{end}")


def register_exit_handler():
    """Register signal handlers to ensure graceful shutdown on Ctrl+C."""
    def _handler(signum, frame):
        print("\n[PortGuard] Received shutdown signal, exiting...")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handler)
