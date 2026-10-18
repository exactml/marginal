import asyncio


async def fetch_with_retry(session, url, attempts=5):
    for attempt in range(attempts):
        try:
            return await session.get(url)
        except Exception:
            await asyncio.sleep(2**attempt)
    return None
