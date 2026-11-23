import asyncio

from llm_connector.logic.connector import LLMSession
from response_models.models import Prompt, Role


def response(reason: str, content: str | None):
    class Response:
        def model_dump(self):
            return {
                "id": "response", "object": "chat.completion", "created": 1,
                "model": "deepseek-flash",
                "choices": [{"index": 0, "finish_reason": reason, "message": {
                    "role": "assistant", "content": content, "tool_calls": None,
                }}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
    return Response()


def test_final_retry_repeats_exact_json_request_without_transient_turn():
    class Completions:
        def __init__(self):
            self.requests = []
            self.responses = [
                response("insufficient_system_resource", "temporary"),
                response("stop", '{"issues":[],"strengths":[]}'),
            ]

        async def create(self, **request):
            self.requests.append(request)
            return self.responses.pop(0)

    completions = Completions()
    client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    session = LLMSession(client)
    prompt = Prompt(role=Role.system, content="final")

    first = asyncio.run(session.final_send([prompt]))
    assert first.choices[0].finish_reason == "insufficient_system_resource"
    second = asyncio.run(session.retry_send())

    assert second.choices[0].message.content == '{"issues":[],"strengths":[]}'
    assert completions.requests[0] == completions.requests[1]
    assert completions.requests[1]["tools"] == []
    assert completions.requests[1]["tool_choice"] == "none"
    assert completions.requests[1]["response_format"] == {"type": "json_object"}
    assert all(message.get("content") != "temporary"
               for message in completions.requests[1]["messages"])
