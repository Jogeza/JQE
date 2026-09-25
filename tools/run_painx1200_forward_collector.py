"""Start the locked, read-only PainX 1200 M1 forward collector."""

import asyncio

from monitoring.painx1200_forward_collector import run_painx1200_forward_collector
from research.painx1200_forward_candidate import write_locked_records


if __name__ == "__main__":
    write_locked_records()
    asyncio.run(run_painx1200_forward_collector())
