"""CPU-only regression coverage for ComfyUI route registration."""
from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
import tempfile
import types

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))


class PromptServerWithoutInstance:
    routes = web.RouteTableDef()


comfy_server = types.ModuleType("server")
comfy_server.PromptServer = PromptServerWithoutInstance
comfy_server.server = types.SimpleNamespace(port=18188)
sys.modules["server"] = comfy_server

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: tempfile.gettempdir()
sys.modules["folder_paths"] = folder_paths

from ai_film_editor_nodes.webui import server as ui  # noqa: E402


def test_no_instance_route_table_registers_and_is_idempotent():
    routes = web.RouteTableDef()
    PromptServerWithoutInstance.routes = routes
    ui.register()
    first_count = len(routes._items)
    assert first_count > 0

    ui.register()
    assert len(routes._items) == first_count

    importlib.reload(ui)
    ui.register()
    assert len(routes._items) == first_count


def test_missing_route_table_reports_clear_diagnostic():
    original_routes = PromptServerWithoutInstance.routes
    PromptServerWithoutInstance.routes = object()
    try:
        try:
            ui.register()
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("registration unexpectedly succeeded")
        assert "no usable ComfyUI route table" in message
        assert "PromptServer.instance.routes" in message
    finally:
        PromptServerWithoutInstance.routes = original_routes


def test_package_import_reports_registration_failure():
    result = subprocess.run(
        [sys.executable, "-c", "import ai_film_editor_nodes"],
        cwd=os.path.dirname(ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "[AFE] web UI registration FAILED:" in result.stdout


async def _check_discoverable_routes():
    routes = PromptServerWithoutInstance.routes
    app = web.Application()
    app.add_routes(routes)
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            index = await client.get("/afe/")
            assert index.status == 200
            assert "AI" in await index.text()

            static = await client.get("/afe/static/app.js")
            assert static.status == 200
            assert "fetch(" in await static.text()

            options = await client.get("/afe/api/options")
            assert options.status == 200
            assert (await options.json())["version"]


def test_static_and_api_routes_are_discoverable():
    asyncio.run(_check_discoverable_routes())


if __name__ == "__main__":
    for test in (test_no_instance_route_table_registers_and_is_idempotent,
                 test_missing_route_table_reports_clear_diagnostic,
                 test_package_import_reports_registration_failure,
                 test_static_and_api_routes_are_discoverable):
        test()
    print("webui registration tests passed")
