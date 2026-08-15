"""TemplateNLG：模板 NLG 生成。"""


class TemplateNLG:
    def __init__(self, templates: dict[str, str] | None = None) -> None:
        self._templates = templates or {}

    def render(self, template_name: str, **kwargs) -> str:
        tpl = self._templates.get(template_name, "{text}")
        return tpl.format(**kwargs)
