"""前端静态产物托管的四条装配约束（PR-0 刀⑱，方案 §9.1）。

钉四件容易在后续改动里悄悄破掉的事：

1. **dist 不存在 ⇒ 不挂载**。AGENTS.md 明文的零依赖冒烟路径
   （``DATABASE_URL= uvicorn agent_server.main:app``）在没有跑过 ``pnpm build`` 的机器上必须
   照常启动；"挂上去后一路 404" 与 "没挂" 都让人以为是前端坏了，但只有前者会把启动本身
   也搭进去（``StaticFiles(directory=...)`` 在构造时就校验目录并 raise）。
2. **挂载只新增 ``/ui`` 一个面**。这一条用"挂与不挂两面的差集"来钉，而不是逐个列接口名：
   列名单的版本一改接口就红（假失败），差集的版本只在挂载真的遮蔽/新增路由时才红（真信号）。
   挪到 ``/`` 的症状是 API 全线静默 404，归因成本极高，所以必须有机读判据。
3. **页面与资源都带 ``Cache-Control: no-store``**。与 ``/console.html`` 那条
   ``test_shell_is_not_cacheable`` 同源纪律：滚动升级后不能把旧事件契约的缓存壳发给使用者。
4. **no-store 是子类给的，不是 Starlette 默认**。对照组用同一目录挂裸 ``StaticFiles``：
   若哪天 ``NoStoreStaticFiles`` 被"简化"回基类，对照组照绿、目标组转红 ⇒ 本文件不是空转。

两个方向都由 ``WEB_UI_DIST`` 显式给定：本机 ``web/dist`` 恰好存在（跑过 build）、CI 的
Python-only 机器恰好不存在，任何"按本机现状断言"的写法都会在另一类机器上自证失败。
唯一不靠 ``WEB_UI_DIST`` 的一组（``TestDefaultPathContract``）因此全部把 CWD 与
``__file__`` 一起 monkeypatch 到 tmp 树里造出的**装包态形状**上，不读本机仓库根。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from agent_core.guardrails.app_factory import build_api_app
from agent_server import main as main_mod
from agent_server.config import get_settings
from agent_server.main import create_app
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from starlette.routing import Mount

_INDEX = "<!doctype html><title>ap-web</title><h1>UI_SHELL_MARKER</h1>\n"


@pytest.fixture(autouse=True)
def _settings_cache_restored():
    """get_settings 是 @lru_cache：用例里改过 env 就必须前后各清一次，否则脏缓存外溢。

    本目录其它用例（如 test_health_fields）是按"lifespan 每次进入 TestClient 都会重跑"的前提
    写的；若把带 WEB_UI_DIST 的 Settings 留给它们，等于让本文件污染整个 session。
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_dist(tmp_path):
    """最小 dist：页面壳 + 一枚带 hash 的资源（覆盖 html=True 目录页与具体文件两条路径）。"""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(_INDEX, encoding="utf-8")
    (dist / "assets" / "index.abc123.js").write_text("console.log(1)\n", encoding="utf-8")
    return dist


def _use_dist(monkeypatch, value):
    monkeypatch.setenv("WEB_UI_DIST", str(value))
    get_settings.cache_clear()


def _mount_paths(app) -> list[str]:
    return sorted(r.path for r in app.routes if isinstance(r, Mount))


def _route_surface(app) -> set[str]:
    """路由面指纹：把 FastAPI 惰性保存的子路由包展开，拿到**全部**接口 path。

    实取的形状（fastapi 0.159.1 / starlette 1.9.0）：``app.routes`` 里普通接口是 ``Route`` / ``Mount``
    （带 ``.path``），而 ``include_router`` 塞进来的是一个 ``_IncludedRouter`` 包装（**无** ``.path``，
    真路由在 ``.original_router.routes`` 里）。第一版直接写 ``{r.path for r in app.routes}``，当场被
    AttributeError 打回——所以这里对“两者都没有”的对象直接 raise，不用 getattr 兜一具“看起来能跑”
    的空面：空面会让上面的差集断言变成永远绿的同语反复。
    """
    out: set[str] = set()
    stack = list(app.routes)
    while stack:
        r = stack.pop()
        if hasattr(r, "path"):
            out.add(r.path)
            continue
        inner = getattr(r, "original_router", None)
        if inner is None:
            raise AssertionError(f"未知道路对象 {type(r).__name__}，指纹口径需同步更新")
        stack.extend(inner.routes)
    return out


class TestConditionalMount:
    def test_missing_dist_means_no_mount(self, monkeypatch, tmp_path):
        """配了目录但不存在 ⇒ 不挂载，且 app 仍能构造出来（零依赖冒烟的形状）。"""
        _use_dist(monkeypatch, tmp_path / "never-built")
        app = create_app()
        assert _mount_paths(app) == []

    def test_present_dist_mounts_exactly_ui(self, monkeypatch, tmp_path):
        _use_dist(monkeypatch, _make_dist(tmp_path))
        app = create_app()
        assert _mount_paths(app) == ["/ui"]

    def test_mount_adds_only_the_ui_entry(self, monkeypatch, tmp_path):
        """挂与不挂两面的差集 == {"/ui"}，反向差集为空 ⇒ 挂载不遮蔽、不删除任何既有路由。"""
        _use_dist(monkeypatch, tmp_path / "never-built")
        without = _route_surface(create_app())
        _use_dist(monkeypatch, _make_dist(tmp_path))
        with_mount = _route_surface(create_app())
        # 非空转前置：展开后的面必须包含正式接口，否则上面两条差集在“双面都是空集”时也成立。
        assert "/query" in without and "/health" in without, sorted(without)
        assert with_mount - without == {"/ui"}, sorted(with_mount - without)
        assert without - with_mount == set(), sorted(without - with_mount)


class TestNoStoreServing:
    def test_index_and_asset_both_carry_no_store(self, monkeypatch, tmp_path):
        _use_dist(monkeypatch, _make_dist(tmp_path))
        app = create_app()
        with TestClient(app) as client:
            page = client.get("/ui/")
            assert page.status_code == 200, page.text
            assert "UI_SHELL_MARKER" in page.text
            assert page.headers["content-type"].startswith("text/html")
            assert page.headers.get("cache-control") == "no-store", page.headers

            asset = client.get("/ui/assets/index.abc123.js")
            assert asset.status_code == 200
            assert asset.headers.get("cache-control") == "no-store", asset.headers

    def test_plain_staticfiles_is_the_control_group(self, tmp_path):
        """对照组：基类不给 no-store ⇒ 上面那条读到 no-store 是子类的功劳。

        单独挂裸 ``StaticFiles`` 的极小 app（不经 create_app）：本格只回答"默认行为是什么"，
        不需要中间件与 lifespan。若哪天 Starlette 改了默认，本格会红——那正是要知道的漂移：
        届时子类可以撤，但撤的前提是这一格读出的新默认，不是"看起来差不多"。
        """
        dist = _make_dist(tmp_path)
        control = build_api_app(title="control", version="0")
        control.mount("/ui", StaticFiles(directory=str(dist), html=True), name="control_ui")
        with TestClient(control) as client:
            page = client.get("/ui/")
            assert page.status_code == 200
            assert "UI_SHELL_MARKER" in page.text
            assert page.headers.get("cache-control") != "no-store", page.headers


class TestDefaultPathContract:
    """``WEB_UI_DIST`` 留空时的默认探测基准 = **进程 CWD** 下的 ``web/dist``（方案 §9.4）。

    这条是刀⑲ 多阶段 Dockerfile 的对接契约：镜像里 ``COPY --from=web-builder`` 的目标必须落在
    这条路径上（镜像 WORKDIR ``/srv/agent-platform`` 既是运行时 CWD ⇒ ``/srv/agent-platform/web/dist``），
    否则构建绿、镜像里前端静默不挂载。挪默认点等于挪镜像装配契约，两处必须一起改。

    基准为什么从 ``__file__`` 上溯改成 CWD（2026-11-02 241 实跑，全案在方案 §9.4）：镜像里
    ``pip install .`` 那份 site-packages 才是被 import 的模块，往上数两层数到解释器目录 ⇒
    真容器 ``GET /ui/`` 404。下面每一格各钉一个方向，且都把 CWD 与 ``__file__`` 一起搬到 tmp 树，
    所以本机有没有 ``web/dist`` 不影响判据成立。
    """

    @staticmethod
    def _installed_shape(tmp_path):
        """造出镜像里那个几何：包在 ``<root>/usr/local/lib/python3.11/site-packages/agent_server/``，
        dist 在 ``<root>/srv/agent-platform/web/dist``（= WORKDIR/CWD 那份）。旧基准的
        ``parents[2]`` 会算到 ``<root>/usr/local/lib/python3.11``，那里永远没有 dist。"""
        pkg = tmp_path / "usr/local/lib/python3.11/site-packages/agent_server"
        pkg.mkdir(parents=True)
        fake_main = pkg / "main.py"
        fake_main.write_text("# 只为拿一个装包态的 __file__，不会被执行\n", encoding="utf-8")
        workdir = tmp_path / "srv/agent-platform"
        (workdir / "web" / "dist").mkdir(parents=True)
        return fake_main, workdir

    def test_default_probe_follows_process_cwd(self, monkeypatch, tmp_path):
        """装包态下：探测点必须是 CWD 那个 ``web/dist``，不是从 ``__file__`` 数出来的那个。"""
        fake_main, workdir = self._installed_shape(tmp_path)
        monkeypatch.setattr(main_mod, "__file__", str(fake_main))
        monkeypatch.delenv("WEB_UI_DIST", raising=False)
        monkeypatch.chdir(workdir)
        get_settings.cache_clear()
        assert main_mod._resolve_web_ui_dist() == workdir / "web" / "dist"

    def test_default_probe_is_a_function_of_cwd_not_of_the_filesystem_of_this_machine(
        self, monkeypatch, tmp_path
    ):
        """无条件格：不碰磁盘，直接钉“默认探测点就是 CWD 拼 web/dist”这条算术。

        上一格得靠 tmp 树里目录存在与否才能报红；本格不需要任何文件系统状态，所以换机器、
        换 ``web/dist`` 是否构建过都同样有牙（写成两格而不是合一格，是为了让“存在性”与
        “算术”两个失效方向各自对应一个读数）。
        """
        other = tmp_path / "somewhere"
        other.mkdir()
        monkeypatch.chdir(other)
        assert main_mod._default_web_ui_dist() == other / "web" / "dist"

    def test_no_upward_walk_from_the_module_file(self):
        """``_default_web_ui_dist`` 的函数体里不得出现 ``__file__`` / ``parents[``。

        这一格专为回退而设：往探测点里加一条 ``__file__`` 上溯的兼容兜底，在装包态下不是
        “修好了”，而是把 404 变成“静默挂上另一棵树”—— 那种绿比红难归因得多（方案 §9.4
        “拒绝混用两个基准”那句）。断言限定在函数体而不是整文件：main.py 里以后可以有
        别的上溯用法，不该被本契约误伤。
        """
        body = inspect.getsource(main_mod._default_web_ui_dist)
        assert "__file__" not in body, body
        assert "parents[" not in body, body

    def test_installed_shape_without_cwd_dist_means_no_mount(self, monkeypatch, tmp_path):
        """同一几何下 CWD 里没有 dist ⇒ 不挂，**不去看 ``__file__`` 那棵树**。"""
        fake_main, workdir = self._installed_shape(tmp_path)
        monkeypatch.setattr(main_mod, "__file__", str(fake_main))
        monkeypatch.delenv("WEB_UI_DIST", raising=False)
        monkeypatch.chdir(tmp_path)  # 有 srv/，但 CWD 本身下面没 web/dist
        get_settings.cache_clear()
        assert main_mod._resolve_web_ui_dist() is None
        assert Path.cwd() == tmp_path
