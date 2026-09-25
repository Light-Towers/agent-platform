import os
import threading

from agent_core.observability import ToolOutcome, ToolResult
from dotenv import load_dotenv
from langchain_core.tools import tool
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError

from agent.config import TIMEOUT_DB_QUERY
from tools._timeout import with_timeout
from tools.sql_guard import validate_sql_mysql
from tools.sql_validation import _validate_identifier

try:
    from agent_core.logging import get_logger
    _db_logger = get_logger(__name__)
except ImportError:
    import logging
    _db_logger = logging.getLogger(__name__)

try:
    from agent_core.tracing import start_span as _start_span
except ImportError:
    from contextlib import contextmanager as _contextmanager
    @_contextmanager
    def _start_span(*a, **kw):
        yield None

load_dotenv()

# ---------------------------------------------------------------------------
# 连接池（SQLAlchemy QueuePool + pymysql，线程安全懒初始化）
# ---------------------------------------------------------------------------
_engine = None
_engine_lock = threading.Lock()


def get_db_config():
    """Get database configuration from environment variables."""
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD")
    host = os.getenv("MYSQL_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    database = os.getenv("MYSQL_DATABASE")
    charset = os.getenv("MYSQL_CHARSET", "utf8mb4")

    required = {"user": user, "password": password, "database": database}
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(f"缺失数据库核心配置：{', '.join(missing)}")

    return {
        "user": user,
        "password": password,
        "host": host,
        "port": port,
        "database": database,
        "charset": charset,
    }


def _get_engine():
    """获取/创建 SQLAlchemy Engine（线程安全懒初始化）。

    使用 pymysql 驱动 + QueuePool 连接池：
    - MYSQL_POOL_SIZE: 连接池大小（默认 5）
    - MYSQL_POOL_MAX_OVERFLOW: 溢出连接数（默认 2）
    - MYSQL_POOL_RECYCLE: 连接回收周期秒（默认 3600，防 MySQL 8h 超时）
    - pool_pre_ping=True: 取连接前探活，自动丢弃死连接
    """
    global _engine
    if _engine is not None:
        return _engine

    with _engine_lock:
        if _engine is not None:
            return _engine

        cfg = get_db_config()
        url = f"mysql+pymysql://{cfg['user']}:{cfg['password']}@{cfg['host']}:{cfg['port']}/{cfg['database']}?charset={cfg['charset']}"

        pool_size = int(os.getenv("MYSQL_POOL_SIZE", "5"))
        max_overflow = int(os.getenv("MYSQL_POOL_MAX_OVERFLOW", "2"))
        pool_recycle = int(os.getenv("MYSQL_POOL_RECYCLE", "3600"))

        _engine = create_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_pre_ping=True,
            echo=False,
        )
        _db_logger.info(
            "DB 连接池已初始化 (pool_size=%d, max_overflow=%d, recycle=%ds, driver=pymysql)",
            pool_size, max_overflow, pool_recycle,
        )
        return _engine


def _get_connection():
    """从连接池获取底层 pymysql 连接（保持 cursor API 兼容）。"""
    return _get_engine().raw_connection()


@tool
@with_timeout(timeout=TIMEOUT_DB_QUERY)
def list_sql_tables()->str:
    """
    查询当前库中所有可用的表！
    作用：为了模型识别有哪些可用的表！方便进行后续的自定义sql查询
    :return: 有表： 可用的表有：表1,表2,表3....  没有表: 没有可用的表   出现异常：查询出现异常：异常信息
    """

    # outcome 语义经 ToolResult 承载（observe_tool 包装器统一上报，方案 v3.1）
    try:
        with _get_connection() as conn:
            with conn.cursor() as cursor:
                sql = "show tables"
                cursor.execute(sql)
                # 捕捉执行结果 要所有的表名称
                # [(表1),(表2),(表3)]
                tables = cursor.fetchall()
                if not tables:
                    return ToolResult(text="没有可用的表", outcome=ToolOutcome.EMPTY)
                # 可用的表有：表1,表2,表3....
                # [表1,表2,表3]
                table_names = [table[0] for table in tables]
                return f"可用的表有：{', '.join(table_names)}"
    except DBAPIError as e:
        return ToolResult(
            text=f"查询出现异常：{str(e)}",
            outcome=ToolOutcome.EXCEPTION,
            error_class="MySQLError",
            detail=str(e),
        )


@tool
@with_timeout(timeout=TIMEOUT_DB_QUERY)
def get_table_data(table_name)->str:
    """
    查询指定表名的数据！当前工具调用之前，必须先调用list_sql_tables完成表名的校验！
    此工具的作用：1.可以完成单表数据的查询 2. 可以为多表查询提供表结果信息（列名&数据格式）
    :param table_name: 表名
    :return: csv格式的数据（模拟表格数据格式）
             1.第一行是列信息，列之间使用,（英文的逗号）分割
             2.第二行开始是表数据，值之间也使用,(英文的逗号)分割
             3.行和行之间使用\n分割
             4.至多表数据查询100条
             例如：
                id,name,age\n -> 列头
                1,张三,18\n
                1,张三,18\n    -> 至多查询100条
                1,张三,18\n
                1,张三,18\n
    """
    # 埋点,调用工具了告诉前端哪个工具被调用了！！
    try:
        safe_name = _validate_identifier(table_name)
        with _get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                allowed = {row[0] for row in cursor.fetchall()}
                if safe_name not in allowed:
                    return ToolResult(
                        text=f"表名 '{safe_name}' 不存在，可用表：{', '.join(sorted(allowed))}",
                        outcome=ToolOutcome.GUARDED,
                        error_class="TableWhitelist",
                        detail=f"表名 '{safe_name}' 不存在",
                    )
                sql = f"SELECT * FROM `{safe_name}` LIMIT 100"
                cursor.execute(sql)
                # 4. cursor获取返回结果
                # 4.1 获取列的信息
                # 返回的查询结果的列的信息
                # description => [(id,列长度...),(),()]
                # 如果查询没有结果 -》 description 也是None
                description = cursor.description
                if not description:
                    return ToolResult(
                        text=f"数据表：{table_name}为空没有数据！",
                        outcome=ToolOutcome.EMPTY,
                        detail=f"表 {table_name} 无数据",
                    )
                # 4.2 获取查询结果
                # description =>  [(id,列长度...),(date,....),()] => 元组 index = 0 列名
                # [列1,列2,列3...]
                columns = [ desc[0] for desc in description ] # [1,2,3,4]
                # 表数据
                # [(1,张三),(2,李四),(3,二狗子)]
                rows = cursor.fetchall()
                # (1,张三) -> ('1','张三') -> '1,张三'
                # ['1,张三','1,张三','1,张三','1,张三','1,张三']
                results = [ ",".join(map(str,row)) for row in rows]

                # columns -> csv -> header
                # id,name,age
                header_str = ",".join(columns)
                # '1,张三'\n
                data_str = "\n".join(results)
                return f"{header_str}\n{data_str}"
    except DBAPIError as e:
        return ToolResult(
            text=f"查询出现异常：{str(e)}",
            outcome=ToolOutcome.EXCEPTION,
            error_class="MySQLError",
            detail=str(e),
        )


@tool
@with_timeout(timeout=TIMEOUT_DB_QUERY)
def execute_sql_query(query)->str:
    """
    执行自定义查询sql语句！切记：执行之前，需要通过执行 list_sql_tables明确表名！执行get_table_data
    明确表结构和数据格式！
    :param query: 要执行的自定义sql语句
    :return: csv格式的数据（模拟表格数据格式）
             1.第一行是列信息，列之间使用,（英文的逗号）分割
             2.第二行开始是表数据，值之间也使用,(英文的逗号)分割
             3.行和行之间使用\n分割
             4.至多表数据查询100条
             例如：
                id,name,age\n -> 列头
                1,张三,18\n
                1,张三,18\n    -> 至多查询100条
                1,张三,18\n
                1,张三,18\n
    """
    try:
        ok, reason, safe_query = validate_sql_mysql(query)
        if not ok:
            return ToolResult(
                text=f"SQL 校验未通过：{reason}",
                outcome=ToolOutcome.GUARDED,
                error_class="SqlGuard",
                detail=reason,
            )
        with _get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(safe_query)
                # 4. cursor获取返回结果
                # 4.1 获取列的信息
                # 返回的查询结果的列的信息
                # description => [(id,列长度...),(),()]
                # 如果查询没有结果 -》 description 也是None
                description = cursor.description
                if not description:
                    return ToolResult(
                        text=f"执行自定义SQL语句查询没有结果，sql为：{query}！",
                        outcome=ToolOutcome.EMPTY,
                        detail=f"sql: {query}",
                    )
                # 4.2 获取查询结果
                # description =>  [(id,列长度...),(date,....),()] => 元组 index = 0 列名
                # [列1,列2,列3...]
                columns = [ desc[0] for desc in description ] # [1,2,3,4]
                # 表数据
                # [(1,张三),(2,李四),(3,二狗子)]
                rows = cursor.fetchall()
                # (1,张三) -> ('1','张三') -> '1,张三'
                # ['1,张三','1,张三','1,张三','1,张三','1,张三']
                results = [ ",".join(map(str,row)) for row in rows]

                # columns -> csv -> header
                # id,name,age
                header_str = ",".join(columns)
                # '1,张三'\n
                data_str = "\n".join(results)
                return f"{header_str}\n{data_str}"
    except DBAPIError as e:
        return ToolResult(
            text=f"查询出现异常：{str(e)}",
            outcome=ToolOutcome.EXCEPTION,
            error_class="MySQLError",
            detail=str(e),
        )


if __name__ == "__main__":
    print(execute_sql_query("SELECT * FROM `drugs` dgs join sales_records srd on dgs.drug_id = srd.drug_id"))






