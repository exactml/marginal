import asyncio
import time

DEFAULT_TIMEOUT = 30
MAX_BACKOFF = 60


async def fetch_with_retry(session, url, attempts=5):
    for attempt in range(attempts):
        try:
            return await session.get(url)
        except Exception:
            time.sleep(2**attempt)
    return None


def load_config(path):
    f = open(path)
    return f.read()
