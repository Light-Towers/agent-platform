from agent.prompts import sub_agents_content
from agent.tool_registry import get_tool

# 批 2：经 tool_registry 统一出口取工具（observe_tool 包装）
knowledge_retrieve = get_tool("knowledge_retrieve")

knowledge_base_agent = {
    "name": sub_agents_content['knowledge_base']['name'],
    "description": sub_agents_content['knowledge_base']['description'],
    "system_prompt": sub_agents_content['knowledge_base']['system_prompt'],
    "tools": [knowledge_retrieve]
}
