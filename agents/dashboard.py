from __future__ import annotations

import sys
import time
from pathlib import Path
from threading import Lock, Thread

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard.clock import now_iso
from dashboard.gh import sweep_pr_status
from dashboard.ledger import connect
from dashboard.poller import poll
from dashboard.server import Context, make_handler
from orchestrator.config import Config, load_config
from orchestrator.layout import Layout
from orchestrator.worktree import branch_name

from http.server import ThreadingHTTPServer


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    layout = Layout.under(repo)
    config = load_config(repo / "agents" / "config.json")
    db_path = repo / config.dashboard_db
    conn = connect(db_path)
    db_lock = Lock()
    prev_snapshot: dict[str, str] = {}

    def dir_poller() -> None:
        nonlocal prev_snapshot
        while True:
            try:
                with db_lock:
                    prev_snapshot, _ = poll(
                        conn, layout, prev_snapshot, observed_at=now_iso()
                    )
            except Exception as exc:
                print(f"dashboard: dir poller error: {exc}")
            time.sleep(config.dashboard_poll_interval_seconds)

    def pr_sweeper() -> None:
        while True:
            try:
                with db_lock:
                    sweep_pr_status(
                        conn, layout, branch_name, checked_at=now_iso()
                    )
            except Exception as exc:
                print(f"dashboard: pr sweep error: {exc}")
            time.sleep(config.dashboard_pr_sweep_interval_seconds)

    dir_thread = Thread(target=dir_poller, name="dir-poller", daemon=True)
    pr_thread = Thread(target=pr_sweeper, name="pr-sweeper", daemon=True)
    dir_thread.start()
    pr_thread.start()

    static_dir = Path(__file__).resolve().parent / "dashboard" / "static"
    ctx = Context(layout=layout, db_path=db_path, static_dir=static_dir)
    server = ThreadingHTTPServer(
        ("127.0.0.1", config.dashboard_port),
        make_handler(ctx),
    )
    print(
        f"dashboard: http://127.0.0.1:{config.dashboard_port} "
        f"(poll={config.dashboard_poll_interval_seconds}s, "
        f"pr_sweep={config.dashboard_pr_sweep_interval_seconds}s)"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\ndashboard: shutting down...")
        server.shutdown()
        server.server_close()
        conn.close()
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
