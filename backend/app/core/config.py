from __future__ import annotations

import logging
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class AppSettings(BaseSettings):
    """定义应用级配置对象。

    该配置类是整个系统的安全入口，负责从 `.env` 文件和运行时环境
    变量中加载所有关键参数，包括应用基础配置、MySQL 连接信息、
    Neo4j 图数据库连接信息以及本地 Qwen 模型 API 访问参数。

    在论文系统的工程化实现中，该类承担以下职责：

    1. 保证敏感信息不在代码中硬编码。
    2. 为 Windows 本地开发和 Linux 服务器部署提供统一配置接口。
    3. 为后续仓储层、服务层、API 层提供可注入的标准配置对象。

    Attributes:
        app_name: 应用名称，用于日志、文档与服务注册。
        app_env: 当前运行环境，例如 development、test、production。
        app_debug: 是否开启调试模式。
        api_v1_prefix: API V1 路由统一前缀。
        mysql_host: MySQL 主机地址。
        mysql_port: MySQL 端口。
        mysql_user: MySQL 用户名。
        mysql_password: MySQL 密码。
        mysql_database: MySQL 数据库名。
        neo4j_uri: Neo4j 连接地址。
        neo4j_username: Neo4j 用户名。
        neo4j_password: Neo4j 密码。
        neo4j_database: Neo4j 使用的数据库名。
        qwen_base_url: 本地或内网 Qwen API 基础地址。
        qwen_api_key: Qwen API 密钥或访问令牌。
        qwen_model: 默认使用的 Qwen 模型名称。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="re-knowledge-graph", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=False, alias="APP_DEBUG")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")

    mysql_host: str = Field(alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, alias="MYSQL_PORT")
    mysql_user: str = Field(alias="MYSQL_USER")
    mysql_password: str = Field(alias="MYSQL_PASSWORD")
    mysql_database: str = Field(alias="MYSQL_DATABASE")

    neo4j_uri: str = Field(alias="NEO4J_URI")
    neo4j_username: str = Field(alias="NEO4J_USERNAME")
    neo4j_password: str = Field(alias="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", alias="NEO4J_DATABASE")

    qwen_base_url: str = Field(default="http://10.109.118.166:11434/v1", alias="QWEN_BASE_URL")
    qwen_api_key: str = Field(alias="QWEN_API_KEY")
    qwen_model: str = Field(default="qwen3:8b", alias="QWEN_MODEL")

    def build_mysql_dsn(self) -> str:
        """构建 MySQL 数据源连接字符串。

        该方法用于将分散在环境变量中的数据库连接参数统一拼装为
        规范的 DSN 字符串，供 ORM、迁移工具或底层数据库客户端
        复用。

        Returns:
            str: 由主机、端口、用户名、密码和数据库名组成的 MySQL DSN。
        """
        return f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"

    def masked_dict(self) -> dict[str, str]:
        """生成适合日志打印的脱敏配置字典。

        在工程运维与实验调试过程中，经常需要输出当前配置快照以确
        认运行环境是否正确。该方法用于生成一个经过敏感字段脱敏的
        字典视图，避免密码、密钥等信息被直接暴露到日志或终端。

        Returns:
            dict[str, str]: 适合日志安全输出的配置映射。
        """
        return {
            "app_name": self.app_name,
            "app_env": self.app_env,
            "app_debug": str(self.app_debug),
            "api_v1_prefix": self.api_v1_prefix,
            "mysql_host": self.mysql_host,
            "mysql_port": str(self.mysql_port),
            "mysql_user": self.mysql_user,
            "mysql_password": "***",
            "mysql_database": self.mysql_database,
            "neo4j_uri": self.neo4j_uri,
            "neo4j_username": self.neo4j_username,
            "neo4j_password": "***",
            "neo4j_database": self.neo4j_database,
            "qwen_base_url": self.qwen_base_url,
            "qwen_api_key": "***",
            "qwen_model": self.qwen_model,
        }


def get_settings() -> AppSettings:
    """创建并返回应用配置对象。

    该函数通常作为依赖注入入口被 FastAPI、仓储层或服务层调用，
    用于统一获取当前运行环境下的配置实例。

    Returns:
        AppSettings: 已根据 `.env` 与系统环境变量完成装载的配置对象。
    """
    return AppSettings()