from __future__ import annotations

import ast
from pathlib import Path

from api.app import app
from api.assistant import router as assistant_router


def test_assistant_package_has_no_mutating_dependencies_or_identifiers():
    forbidden_import_roots = {"broker", "execution", "risk"}
    forbidden_identifiers = {
        "BrokerGateway", "get_gateway", "AsyncTradeExecutor", "ExecutionPolicy",
        "ExecutionIntent", "OrderRequest", "submit_order", "order_send",
        "consume", "add_item", "remove_item", "set_selected_broker",
    }
    for path in Path("jqe_ai").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden_import_roots for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_import_roots
            elif isinstance(node, ast.Name):
                assert node.id not in forbidden_identifiers
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_identifiers


def test_only_expected_assistant_routes_are_registered():
    routes = {(route.path, method) for route in assistant_router.routes for method in (getattr(route, "methods", None) or set())}
    assert routes == {
        ("/api/v1/assistant/status", "GET"),
        ("/api/v1/assistant/chat", "POST"),
    }
    included = [getattr(route, "original_router", None) for route in app.routes]
    assert assistant_router in included
