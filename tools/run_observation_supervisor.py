"""Run the supervised observation-only M5-close loop."""

import asyncio

from monitoring.observation_supervisor import run_observation_supervisor


if __name__ == "__main__":
    asyncio.run(run_observation_supervisor())

