"""多渠道测试。"""


from dialogue_framework.channels.console_channel import ConsoleChannel
from dialogue_framework.channels.inspect_proxy import InspectProxy


async def test_console_channel_send(capsys):
    channel = ConsoleChannel()
    await channel.send("hello")
    captured = capsys.readouterr()
    assert "hello" in captured.out


async def test_inspect_proxy_history():
    console = ConsoleChannel()
    proxy = InspectProxy(console)
    await proxy.send("test message")
    assert len(proxy.history) == 1
    assert proxy.history[0]["direction"] == "send"
    assert proxy.history[0]["message"] == "test message"
