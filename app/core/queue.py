import asyncio

class JobQueue:
    """Асинхронная обёртка очереди для обработки задач."""
    def __init__(self) -> None:
        """Инициализирует внутреннюю asyncio-очередь."""
        self._q: asyncio.Queue[str] = asyncio.Queue()

    
    async def enqueue(self, job_id: str) -> None:
        """Помещает идентификатор задачи в очередь."""
        await self._q.put(job_id)
    
    async def dequeue(self) -> str:
        """Ожидает и возвращает следующий идентификатор задачи."""
        return await self._q.get()
    
    def task_done(self) -> None:
        """Помечает текущую задачу как обработанную."""
        self._q.task_done()
