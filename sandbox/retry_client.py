import asyncio
import time


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
