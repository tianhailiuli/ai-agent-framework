"""Entry point to start the AI Agent Framework web server."""

from ai_agent_framework.web.app import app
from ai_agent_framework import config
from ai_agent_framework.utils.port_guard import cleanup_port, find_free_port, register_exit_handler


def main():
    port = config.FLASK_PORT
    host = config.FLASK_HOST

    # 1. Auto-cleanup zombie processes occupying the port
    port_free = cleanup_port(port, verbose=True)
    if not port_free:
        # If cleanup failed, auto-switch to a free port
        new_port = find_free_port(start=port + 1)
        print(f"[Main] Port {port} still occupied, auto-switching to {new_port}")
        port = new_port

    # 2. Register graceful shutdown handlers (Ctrl+C)
    register_exit_handler()

    print(f"Starting AI Agent Framework on http://{host}:{port}")
    app.run(host=host, port=port, debug=config.FLASK_DEBUG, threaded=True)


if __name__ == "__main__":
    main()
