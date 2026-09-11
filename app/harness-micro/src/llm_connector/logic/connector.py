import json

from openai import AsyncOpenAI

from llm_connector.interfaces.connector import LLMConnectorInterface, AbstractLLMSession, MessageAuthors, Message


class LLMSession(AbstractLLMSession):
    """Сессия для общения с нейронкой
    Берет на себя ответственность за хранение прошлых сообщений"""

    def __init__(self, client: AsyncOpenAI):
        self.history: list[Message] = []
        if client is None:
            raise
        self.client = client

    def _load_history(self) -> str:
        data = {}

        for i in range(len(self.history)):
            message = self.history[i]
            data[f"message_{i + 1}"] = message.to_json()

        return json.dumps(data, ensure_ascii=False)

    async def send(self, message: Message) -> str:
        """Отправить запрос"""
        self.history.append(message)

        # TODO Отправка
        request = {
            "model": "",
            "input": self._load_history(),
        }

        raw_answer = await self.client.responses.create(**request)

        answer = Message(
            author=MessageAuthors.agent,
            instructions="",
            content=raw_answer.output_text
        )

        self.history.append(answer)

        return raw_answer.output_text

    # async def receive(self):
    #     """Извлечь результат"""
    #     pass


class LLMConnector(LLMConnectorInterface):

    def __init__(self):
        self.sessions: dict[int, AbstractLLMSession] = {}
        self.client = None

    async def create_session(self, unique_id: int) -> AbstractLLMSession:
        """Получить сессию для общения с нейронкой"""
        if unique_id in self.sessions.keys():
            raise  # Сессия с данным id существует
        session = LLMSession(client=self.client)
        self.sessions[unique_id] = session
        return session

    async def connect(self, url, apikey):
        """Подключиться к апи"""
        self.client = AsyncOpenAI(base_url=url, api_key=apikey)
