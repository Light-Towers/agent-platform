from agent.prompts import sub_agents_content
from tools.zhiku_tools import zhiku_retrieve

knowledge_base_agent = {
    "name": sub_agents_content['knowledge_base']['name'],
    "description": sub_agents_content['knowledge_base']['description'],
    "system_prompt": sub_agents_content['knowledge_base']['system_prompt'],
    "tools": [zhiku_retrieve]
}
