from unittest.mock import AsyncMock, patch

import jinja2
import pytest

from promptflow.evals.synthetic._conversation import (
    ConversationBot,
    ConversationRole,
    ConversationTurn,
    LLMBase,
    OpenAIChatCompletionsModel,
)


# Mock classes for dependencies
class MockLLMBase(LLMBase):
    pass


class MockOpenAIChatCompletionsModel(OpenAIChatCompletionsModel):
    def __init__(self):
        super().__init__(name="mockAIcompletionsModel", endpoint_url="some-url", token_manager="token_manager")

    async def get_conversation_completion(self, messages, session, role):
        return {"response": {}, "request": {}, "time_taken": 0, "full_response": {}}


@pytest.fixture
def bot_user_params():
    return {
        "role": ConversationRole.USER,
        "model": MockOpenAIChatCompletionsModel(),
        "conversation_template": "Hello, {{ name }}!",
        "instantiation_parameters": {"name": "TestUser", "conversation_starter": "Hello, world!"},
    }


@pytest.fixture
def bot_assistant_params():
    return {
        "role": ConversationRole.ASSISTANT,
        "model": MockOpenAIChatCompletionsModel(),
        "conversation_template": "Hello, {{ chatbot_name }}!",
        "instantiation_parameters": {"chatbot_name": "TestBot"},
    }


@pytest.mark.unittest
class TestConversationBot:
    @pytest.mark.asyncio
    async def test_conversation_bot_initialization_user(self, bot_user_params):
        bot = ConversationBot(**bot_user_params)
        assert bot.role == ConversationRole.USER
        assert bot.name == "TestUser"
        assert isinstance(bot.conversation_template, jinja2.Template)

    @pytest.mark.asyncio
    async def test_conversation_bot_initialization_assistant(self, bot_assistant_params):
        bot = ConversationBot(**bot_assistant_params)
        assert bot.role == ConversationRole.ASSISTANT
        assert bot.name == "TestBot"
        assert isinstance(bot.conversation_template, jinja2.Template)

    @pytest.mark.asyncio
    async def test_generate_response_first_turn_with_starter(self, bot_user_params):
        bot = ConversationBot(**bot_user_params)
        session = AsyncMock()
        response, request, time_taken, full_response = await bot.generate_response(session, [], 0, 0)
        assert response["samples"][0] == "Hello, world!"
        assert time_taken == 0

    @pytest.mark.asyncio
    async def test_generate_response_with_history_and_role(self, bot_assistant_params):
        bot = ConversationBot(**bot_assistant_params)
        session = AsyncMock()
        conversation_history = [ConversationTurn(role=ConversationRole.USER, message="Hi!")]
        with patch.object(
            MockOpenAIChatCompletionsModel, "get_conversation_completion", new_callable=AsyncMock
        ) as mocked_method:
            mocked_method.return_value = {"response": {}, "request": {}, "time_taken": 0, "full_response": {}}
            response, request, time_taken, full_response = await bot.generate_response(session, conversation_history, 1)
            mocked_method.assert_called_once()
            assert "Hi!" in mocked_method.call_args[1]["messages"][1]["content"]
