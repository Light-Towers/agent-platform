"""NLGGenerator：NLG 生成器（模板 + LLM 重写组合）。"""

from dialogue_framework.nlg.response_rephraser import rephrase
from dialogue_framework.nlg.template_nlg import TemplateNLG


class NLGGenerator:
    def __init__(self, templates: dict[str, str] | None = None) -> None:
        self._template = TemplateNLG(templates)

    async def generate(
        self, template_name: str = "default", text: str = "", rephrase_enabled: bool = False, **kwargs
    ) -> str:
        rendered = self._template.render(template_name, text=text, **kwargs)
        if rephrase_enabled:
            return await rephrase(rendered)
        return rendered
