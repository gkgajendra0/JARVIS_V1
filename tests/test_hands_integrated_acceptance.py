from __future__ import annotations

from jarvis.computer import hands_integrated_acceptance as acceptance


def test_integrated_dependency_checks_report_missing_specialist() -> None:
    calls: list[str] = []

    def finder(name: str) -> bool:
        calls.append(name)
        return name != "playwright"

    checks = acceptance._dependency_checks(finder=finder)
    by_name = {check.name: check for check in checks}

    missing = by_name["Hands dependency: Playwright structured browser control"]
    assert missing.ok is False
    assert "playwright" in missing.detail
    assert len(calls) == len(set(calls))


def test_integrated_operation_map_excludes_only_owner_enabled_visual_fallback() -> None:
    operations = acceptance._required_operation_names()

    assert "create_text_file" in operations
    assert "execute_browser_plan" in operations
    assert "shutdown_workstation" in operations
    assert "install_package" in operations
    assert "git_push_current" in operations
    assert "execute_visual_desktop_task" not in operations


def test_integrated_acceptance_paths_are_isolated_by_run_id() -> None:
    paths = acceptance._acceptance_paths("abc12345")

    assert paths == {
        "folder": "JARVIS_Hands_Acceptance_abc12345",
        "text": "JARVIS_Hands_Acceptance_abc12345/acceptance.txt",
        "docx": "JARVIS_Hands_Acceptance_abc12345/acceptance.docx",
        "xlsx": "JARVIS_Hands_Acceptance_abc12345/acceptance.xlsx",
        "pptx": "JARVIS_Hands_Acceptance_abc12345/acceptance.pptx",
    }


def test_integrated_owner_plan_is_representative_and_non_destructive() -> None:
    actions = acceptance._representative_actions(
        write_root="downloads",
        run_id="abc12345",
    )
    operations = [operation for _, operation, _ in actions]

    assert operations == [
        "system_status",
        "get_master_volume",
        "list_windows",
        "open_app",
        "create_text_file",
        "create_docx",
        "create_xlsx",
        "create_pptx",
        "execute_browser_plan",
        "list_displays",
        "list_bluetooth_devices",
        "search_software",
        "git_status",
    ]
    assert "trash_path" not in operations
    assert "pair_bluetooth_device" not in operations
    assert "install_package" not in operations
    assert "restart_workstation" not in operations
    assert "shutdown_workstation" not in operations
    assert "git_commit" not in operations
    assert "git_push_current" not in operations


def test_integrated_h1_mutation_is_only_approved_calculator_launch() -> None:
    actions = acceptance._representative_actions(
        write_root="downloads",
        run_id="abc12345",
    )
    app = next(
        parameters for _, operation, parameters in actions if operation == "open_app"
    )

    assert app == {"app": "calculator"}


def test_integrated_browser_scenario_uses_semantic_read_only_page_interaction() -> None:
    actions = acceptance._representative_actions(
        write_root="downloads",
        run_id="abc12345",
    )
    browser = next(
        parameters
        for _, operation, parameters in actions
        if operation == "execute_browser_plan"
    )

    assert browser == {
        "plan": [
            {"action": "navigate", "url": "https://example.com"},
            {"action": "read_page"},
        ]
    }
