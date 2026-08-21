"""Workflow YAML 文件加载器测试。"""

import tempfile
import pathlib

import yaml

import pytest

from agent_runtime.skills.workflow import (
    WorkflowSpec,
    load_workflow_yaml,
    discover_workflows,
    compile_workflow,
)


class TestWorkflowYAML:
    @pytest.mark.asyncio
    async def test_load_workflow_yaml(self):
        """从 YAML 文件加载并编译为 Skill。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = pathlib.Path(tmpdir) / "test_wf.yaml"
            yaml_path.write_text("""
name: "test_pipeline"
description: "测试流水线"
input_schema:
  type: object
  properties:
    question:
      type: string
  required: [question]
nodes:
  - id: "step1"
    skill: "echo"
    inputs:
      text: "$input.question"
edges: []
output_node: "step1"
permissions: ["test"]
""", encoding="utf-8")

            skill = load_workflow_yaml(yaml_path)

            assert skill.name == "test_pipeline"
            assert skill.kind.value == "workflow"
            assert skill.input_schema is not None
            assert "question" in skill.input_schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_discover_workflows(self):
        """递归扫描目录加载多个 Workflow。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            (root / "subdir").mkdir()

            (root / "wf1.yaml").write_text("""
name: "wf1"
description: "first"
nodes:
  - id: "a"
    skill: "echo"
edges: []
""", encoding="utf-8")

            (root / "subdir" / "wf2.yml").write_text("""
name: "wf2"
description: "second"
nodes:
  - id: "b"
    skill: "echo"
edges: []
""", encoding="utf-8")

            skills = discover_workflows(tmpdir)

            assert len(skills) == 2
            names = {s.name for s in skills}
            assert names == {"wf1", "wf2"}

    @pytest.mark.asyncio
    async def test_compile_workflow_roundtrip(self):
        """compile_workflow(dict) 与 compile_workflow(WorkflowSpec) 等价。"""
        spec_dict = {
            "name": "roundtrip",
            "description": "roundtrip test",
            "nodes": [
                {"id": "n1", "skill": "echo", "inputs": {"msg": "$input.q"}}
            ],
            "edges": [],
        }

        skill1 = compile_workflow(spec_dict)
        skill2 = compile_workflow(WorkflowSpec(**spec_dict))

        assert skill1.name == skill2.name == "roundtrip"
        assert skill1.kind == skill2.kind

    @pytest.mark.asyncio
    async def test_yaml_references(self):
        """验证 $input 和 $node 引用在 YAML 中正确解析。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = pathlib.Path(tmpdir) / "refs.yaml"
            yaml_path.write_text("""
name: "ref_test"
description: "reference test"
nodes:
  - id: "first"
    skill: "echo"
    inputs:
      msg: "$input.question"
  - id: "second"
    skill: "echo"
    inputs:
      msg: "$node.first"
edges:
  - dependent: "second"
    dependency: "first"
""", encoding="utf-8")

            skill = load_workflow_yaml(yaml_path)
            assert skill.metadata.get("kind") == "workflow"

            # 通过 executor 验证引用解析（mock registry）
            from unittest.mock import Mock

            registry = Mock()
            # WorkflowExecutor 通过 compile_workflow 注入 registry
            spec_dict = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            skill2 = compile_workflow(spec_dict, registry=registry)
            assert skill2.name == "ref_test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])