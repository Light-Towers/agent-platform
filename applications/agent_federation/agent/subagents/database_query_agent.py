from agent.prompts import sub_agents_content
from agent.tool_registry import get_tool

# 批 2：经 tool_registry 统一出口取工具（observe_tool 包装）
execute_sql_query = get_tool("execute_sql_query")
get_table_data = get_tool("get_table_data")
list_sql_tables = get_tool("list_sql_tables")

database_query_agent = {
    "name":sub_agents_content['db']['name'],
    "description":sub_agents_content['db']['description'],
    "system_prompt":sub_agents_content['db']['system_prompt'],
    "tools":[list_sql_tables,get_table_data,execute_sql_query]
}
