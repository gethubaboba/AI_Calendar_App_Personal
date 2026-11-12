from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from services import ai_service


class OllamaTest(IsolatedAsyncioTestCase):
    async def test_analysis_uses_configured_model(self):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Отчёт"))])
        with patch.object(ai_service.client.chat.completions, "create", new_callable=AsyncMock) as create:
            create.return_value = response
            result = await ai_service.get_ai_productivity_analysis([], [], "Тест")
        self.assertEqual(result, "Отчёт")
        self.assertEqual(create.await_args.kwargs["model"], ai_service.LOCAL_MODEL_NAME)
