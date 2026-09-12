"""Job runner + periodic ticks."""
import logging
import os
import socket
import threading
import time

from . import db, handlers, ratelimit
from .config import WORKER_CONCURRENCY
from .connections import sync_all_due

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("taste.worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
MAX_ATTEMPTS = 3


def job_loop(n):
    wid = f"{WORKER_ID}-{n}"
    while True:
        try:
            job = db.claim_job(wid)
        except Exception:
            log.exception("claim failed"); time.sleep(5); continue
        if not job:
            time.sleep(1.5); continue
        t0 = time.time()
        try:
            handlers.run_job(job)
            db.finish_job(job["id"], True)
            log.info("job %s %s done in %.1fs", job["id"], job["type"], time.time() - t0)
        except Exception as e:
            retry = job["attempts"] < MAX_ATTEMPTS
            log.exception("job %s %s failed (attempt %s)", job["id"], job["type"], job["attempts"])
            db.finish_job(job["id"], False, error=f"{type(e).__name__}: {e}", retry_in=60 * job["attempts"] if retry else None)


def tick_loop():
    last_hourly = 0
    while True:
        try:
            handlers.surface_tick()
            handlers.profile_tick()
            # requeue jobs whose worker died mid-run
            db.q("UPDATE jobs SET status = 'queued', locked_by = NULL WHERE status = 'running' AND locked_at < now() - interval '15 minutes'")
            if time.time() - last_hourly > 3600:
                last_hourly = time.time()
                sync_all_due()
                handlers.retry_pending()
                ratelimit.cleanup()
                db.q("DELETE FROM jobs WHERE status = 'done' AND finished_at < now() - interval '14 days'")
        except Exception:
            log.exception("tick failed")
        time.sleep(60)


def main():
    db.migrate()
    log.info("worker %s up, concurrency %s", WORKER_ID, WORKER_CONCURRENCY)
    for n in range(WORKER_CONCURRENCY):
        threading.Thread(target=job_loop, args=(n,), daemon=True).start()
    tick_loop()


if __name__ == "__main__":
    main()
