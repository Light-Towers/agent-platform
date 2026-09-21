"""配置（pydantic-settings）。"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EXHIBITION_AGENT_",
        env_file=".env",
        extra="ignore",
    )

    warehouse_base_url: str = Field(
        default="http://127.0.0.1:9100",
        description="warehouse 领域 API 基址（mock 默认 9100）",
    )
    context_mode: str = Field(
        default="jwt",
        description="ExecutionContext 传递模式：jwt（默认 D1）| base64",
    )
    execution_mode: str = Field(
        default="DEV",
        description="执行档位（契约 v1.1 §C1）：STRICT（生产，IAM/网关 JWT 验签）| DEV（本地/测试，PLATFORM_LOCAL 不验签）。"
        "两档 401/403/scope 校验恒开，无 OFF 档。",
    )
    context_jwt_secret: str | None = Field(
        default=None,
        description="JWT 验签密钥（STRICT 档必填）",
    )
    warehouse_timeout: float = Field(default=10.0, description="warehouse 调用超时（秒）")
    log_level: str = Field(default="INFO")
    otel_endpoint: str | None = Field(
        default=None,
        description="OTLP 导出端点（空 → no-op 降级，本地/CI 无 collector 也全绿）",
    )
    otel_service_name: str = Field(
        default="exhibition-agent",
        description="OTel service.name 属性",
    )
    otel_enabled: bool = Field(
        default=False,
        description="OTel 总开关（需 endpoint 非空 + SDK 可用才真实导出）",
    )
    llm_obs_backend: str = Field(
        default="langfuse",
        description="LLM 可观测后端：langfuse（默认，开源 MIT）| langsmith（商业闭源）| noop",
    )

    @field_validator("execution_mode")
    @classmethod
    def _validate_execution_mode(cls, v: str) -> str:
        """无 OFF 档（契约 v1.1 §C1）：与 execution_mode_to_verify_signature 对齐，fail-fast。"""
        mode = v.upper()
        if mode not in ("STRICT", "DEV"):
            raise ValueError(f"未知执行档位：{v}（仅支持 STRICT / DEV，无 OFF 档）")
        return mode

    @field_validator("context_mode")
    @classmethod
    def _validate_context_mode(cls, v: str) -> str:
        mode = v.lower()
        if mode not in ("jwt", "base64"):
            raise ValueError(f"未知上下文传递模式：{v}（仅支持 jwt / base64）")
        return mode

    @model_validator(mode="after")
    def _check_strict_secret(self) -> "Settings":
        """STRICT 档验签密钥必填（启动期 fail-fast，不等到第一个请求才报错）。"""
        if self.execution_mode == "STRICT" and not self.context_jwt_secret:
            raise ValueError("STRICT 档要求 context_jwt_secret 非空（EXHIBITION_AGENT_CONTEXT_JWT_SECRET）")
        return self

    @property
    def verify_signature(self) -> bool:
        """STRICT 档验签，DEV 档不验签（契约 v1.1：环境只切验签，校验恒开）。"""
        return self.execution_mode == "STRICT"
