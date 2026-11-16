# =============================================================================
# workers/scheduler.py  -  THE BACKGROUND LOOPS THAT CHECK WEBSITES
# =============================================================================
# When the app starts, it also starts a few "background tasks" that keep
# running next to the API. Think of a small restaurant:
#
#   SCHEDULER LOOP   The manager. Every few seconds he looks at the order board
#                    (the database) and puts new orders into a queue.
#   QUEUE            The order window where tickets wait.
#   WORKERS          The cooks (5 by default). Each takes a ticket from the
#                    queue, checks one website, saves the result, and takes
#                    the next ticket.
#   CLEANUP LOOP     The cleaner. Once an hour he deletes very old results.
#
# All of this uses "asyncio" tasks, so one Python process can wait for many
# websites at the same time without needing many threads.
#
# Read more (with a diagram): docs/07-monitoring-engine.md
# =============================================================================

import asyncio
import logging

from app.config import settings
from app.database import SessionLocal
from app.services.monitoring import check_monitor_by_id, claim_due_monitors, delete_old_results

logger = logging.getLogger(__name__)

CLEANUP_EVERY_SECONDS = 3600  # once an hour


# Owns all the background tasks. main.py creates one Scheduler, calls start() when the
# app starts and stop() when the app stops.
class Scheduler:
    # Prepares an empty queue. Nothing runs until start() is called.
    def __init__(self) -> None:
        # The queue holds monitor ids waiting to be checked.
        # maxsize makes the scheduler wait if the workers fall behind,
        # instead of piling up unlimited work in memory.
        self._queue: asyncio.Queue[int] = asyncio.Queue(maxsize=1000)
        self._tasks: list[asyncio.Task] = []

    # Starts all background tasks. Called once when the app starts.
    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._scheduler_loop(), name="scheduler"))
        self._tasks.append(asyncio.create_task(self._cleanup_loop(), name="cleanup"))
        for number in range(settings.worker_count):
            self._tasks.append(asyncio.create_task(self._worker_loop(number), name=f"worker-{number}"))
        logger.info("Monitoring started with %s workers", settings.worker_count)

    # Stops all background tasks. Called once when the app shuts down.
    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        # Wait until every task has really stopped.
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Monitoring stopped")

    # THE MANAGER: repeats forever. Finds due monitors and queues them.
    async def _scheduler_loop(self) -> None:
        while True:
            try:
                async with SessionLocal() as session:
                    monitor_ids = await claim_due_monitors(session)
                for monitor_id in monitor_ids:
                    await self._queue.put(monitor_id)
            except Exception:
                # A loop that crashes would silently stop all monitoring,
                # so we log the problem and carry on.
                logger.exception("Scheduler loop failed, will try again")
            await asyncio.sleep(settings.scheduler_interval_seconds)

    # A COOK: repeats forever. Takes a monitor id from the queue and checks it.
    async def _worker_loop(self, number: int) -> None:
        while True:
            monitor_id = await self._queue.get()
            try:
                await check_monitor_by_id(monitor_id)
            except Exception:
                logger.exception("Worker %s failed to check monitor %s", number, monitor_id)
            finally:
                self._queue.task_done()

    # THE CLEANER: repeats forever. Deletes old check results once an hour.
    async def _cleanup_loop(self) -> None:
        while True:
            try:
                async with SessionLocal() as session:
                    deleted = await delete_old_results(session)
                if deleted:
                    logger.info("Deleted %s old check results", deleted)
            except Exception:
                logger.exception("Cleanup failed, will try again")
            await asyncio.sleep(CLEANUP_EVERY_SECONDS)
