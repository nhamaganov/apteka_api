import asyncio

class JobQueue:
    def __init__(self) -> None:
        self._q: asyncio.Queue[str] = asyncio.Queue()

    
    async def enqueue(self, job_id: str) -> None:
        await self._q.put(job_id)
    
    async def dequeue(self) -> str:
        return await self._q.get()
    
    def task_done(self) -> None:
        self._q.task_done()