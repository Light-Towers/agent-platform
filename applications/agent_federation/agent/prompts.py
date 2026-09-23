# 目标加载yml中的数据，供创建主和子智能体使用
import logging
from pathlib import Path

import yaml  # yaml配置文件读取

logger = logging.getLogger(__name__)


# 定义一个加载函数，配置文件yaml加载成字典
def load_yaml(file_path):
    """
    加载指定位置的yaml配置文件
    :param file_path:  加载的文件的地址
    :return:  返回的加载结果 本质就是字典
    """
    with open(file_path, encoding='utf-8') as f :
        # safe_load 只会加载，不会触发！
        # load 加载过程中可能无意执行内部的嵌入函数！！ 可能发生注入脚本攻击
        return yaml.safe_load(f)

# 尝试读取主和子智能体的配置文件和数据（供后续使用）
# 项目的根地址
# project_root_path  = Path(__file__).parent.parent
project_root_path  = Path(__file__).parents[1] # prompts -> parents -> [agent , deep_search_pro]
prompt_dir = project_root_path / "prompt"
yaml_file_path = prompt_dir / "prompts.yml"

prompt_yaml_content = load_yaml(yaml_file_path)


# main_agent_content
main_agent_content = prompt_yaml_content["main_agent"]
# sub_agents_content
sub_agents_content = prompt_yaml_content["sub_agents"]

# Phase 3：加载 prompt/ 下所有 .yaml（intent.yaml, rewrite.yaml, planner.yaml）
intent_content = None
rewrite_content = None
planner_content = None

for _yaml_file in sorted(prompt_dir.glob("*.yaml")) + sorted(prompt_dir.glob("*.yml")):
    if _yaml_file == yaml_file_path:
        continue
    _key = _yaml_file.stem
    try:
        _data = load_yaml(_yaml_file)
        if _key == "intent":
            intent_content = _data
        elif _key == "rewrite":
            rewrite_content = _data
        elif _key == "planner":
            planner_content = _data
    except Exception as e:
        logger.warning("加载 prompt 文件失败: %s, 错误: %s", _yaml_file, e)
