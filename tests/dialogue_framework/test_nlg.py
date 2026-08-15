"""NLG 生成测试。"""


from dialogue_framework.nlg.nlg_generator import NLGGenerator
from dialogue_framework.nlg.template_nlg import TemplateNLG


async def test_template_nlg_default():
    nlg = TemplateNLG()
    result = nlg.render("default", text="hello")
    assert "hello" in result


async def test_nlg_generator_without_rephrase():
    gen = NLGGenerator()
    result = await gen.generate(template_name="default", text="test response", rephrase_enabled=False)
    assert "test response" in result
