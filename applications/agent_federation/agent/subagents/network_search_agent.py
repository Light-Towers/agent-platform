# 目标： 创建网络搜索子智能体
# 方式1： dict -> deepagents PyPI 包  方式： compiledSubAgent -> langchain langgraph
from agent.prompts import sub_agents_content
from agent.tool_registry import get_tool

# 批 2：经 tool_registry 统一出口取工具（observe_tool 包装）
internet_search = get_tool("internet_search")

network_search_agent = {
    "name":sub_agents_content['tavily']['name'],
    "description":sub_agents_content['tavily']['description'],
    "system_prompt":sub_agents_content['tavily']['system_prompt'],
    "tools":[internet_search]
}
