from openai import AsyncOpenAI
from utils.config import CONFIG

from llm_connector.interfaces.connector import LLMConnectorInterface, AbstractLLMSession
from response_models.models import Prompt, ModelMessage, ToolResponse, Request, ToolData, ModelResponse


class LLMSession(AbstractLLMSession):
    """Сессия для общения с нейронкой
    Берет на себя ответственность за хранение прошлых сообщений"""

    def __init__(self, client: AsyncOpenAI):
        self.messages: list[Prompt | ModelMessage | ToolResponse] = []
        self.tools: list[ToolData] | None = None
        if client is None:
            raise
        self.client = client
        self.last_request: Request | None = None

    async def _execute(self, request: Request) -> ModelResponse:
        # Keep an immutable snapshot: retries must repeat the same provider
        # operation, not turn a transient response into conversation history.
        self.last_request = request.model_copy(deep=True)
        response = await self.client.chat.completions.create(
            **request.model_dump(exclude_none=True)
        )
        answer = ModelResponse.model_validate(response.model_dump())
        if answer.choices[0].finish_reason != "insufficient_system_resource":
            self.messages.append(answer.choices[0].message)
        return answer


    async def send_start(self, messages: list[Prompt], tools: list[ToolData]) -> ModelResponse:
        """Отправить стартовый запрос"""
        for message in messages:
            self.messages.append(message)

        self.tools = tools

        request = Request(
            model=CONFIG.llm.model,
            messages=self.messages,
            tools=self.tools
        )
        return await self._execute(request)

    async def send(self, messages: list[Prompt | ToolResponse]) -> ModelResponse:
        """Отправить запрос"""
        for message in messages:
            self.messages.append(message)

        request = Request(
            model=CONFIG.llm.model,
            messages=self.messages,
            tools=self.tools
        )
        return await self._execute(request)

    async def final_send(self, messages: list[Prompt | ToolResponse]) -> ModelResponse:
        """Отправить финальны запрос, гарантирующий json-ответ"""
        for message in messages:
            self.messages.append(message)

        request = Request(
            model=CONFIG.llm.model,
            messages=self.messages,
            tools=[],
            tool_choice="none",
            response_format={"type": "json_object"}
        )

        return await self._execute(request)

    async def retry_send(self) -> ModelResponse:
        if self.last_request is None:
            raise RuntimeError("Cannot retry before an initial request")
        return await self._execute(self.last_request.model_copy(deep=True))


    def close(self) -> bool:
        del self
        return True


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

    async def close_session(self, session_id: int) -> bool:
        """Закрыть сессию"""
        if session_id not in self.sessions.keys():
            raise  # Сессия с данным id не существует
        session = self.sessions.pop(session_id)
        session.close()
        return True

    async def connect(self, url, apikey):
        """Подключиться к апи"""
        self.client = AsyncOpenAI(base_url=url, api_key=apikey)
