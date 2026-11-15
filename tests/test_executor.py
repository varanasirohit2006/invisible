import errno
import os
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from agent.executor import (
    build_plan,
    execute_plan,
    fingerprint,
    invoice_fields,
    move_without_overwrite,
)
from shared.models import AutomationParams
from shared.paths import ScopeError

from .conftest import write_invoice


def test_pdf_rename_move_and_excel_append_with_backup(tmp_path):
    source = tmp_path / "invoice.pdf"
    write_invoice(source)
    tracker = tmp_path / "Tracker.xlsx"
    workbook = Workbook()
    workbook.active.title = "Invoices"
    workbook.active.append(["Invoice number", "Date", "Amount", "File"])
    workbook.save(tracker)
    workbook.close()
    before = fingerprint(tracker)
    plan = build_plan(
        AutomationParams(
            source_file=str(source),
            new_name="Invoice_{invoice_number}.pdf",
            destination_folder=str(tmp_path / "archive"),
            extract_invoice=True,
            tracker_file=str(tracker),
        ),
        [str(tmp_path)],
        1,
    )
    assert plan.extracted_fields == {
        "invoice_number": "INV-2026-042",
        "invoice_date": "2026-11-06",
        "amount": "149.50",
    }
    assert source.exists() and fingerprint(tracker) == before
    result = execute_plan(
        plan, get_scope=lambda: ([str(tmp_path)], 1), backup_dir=tmp_path / "backups"
    )
    assert result["status"] == "succeeded", result
    destination = tmp_path / "archive" / "Invoice_INV-2026-042.pdf"
    assert destination.exists() and not source.exists()
    assert fingerprint(Path(result["backups"][0])) == before
    workbook = load_workbook(tracker)
    assert list(workbook["Invoices"].values)[1] == (
        "INV-2026-042",
        "2026-11-06",
        149.5,
        str(destination),
    )
    workbook.close()


def test_new_workbook_and_formula_like_invoice_number_remains_literal(tmp_path):
    source = tmp_path / "invoice.pdf"
    write_invoice(source)
    tracker = tmp_path / "Tracker.xlsx"
    plan = build_plan(
        AutomationParams(
            source_file=str(source),
            extract_invoice=True,
            tracker_file=str(tracker),
            invoice_number="=1+1",
        ),
        [str(tmp_path)],
        1,
    )
    result = execute_plan(
        plan, get_scope=lambda: ([str(tmp_path)], 1), backup_dir=tmp_path / "backups"
    )
    assert result["status"] == "succeeded", result
    workbook = load_workbook(tracker)
    assert workbook["Invoices"]["A1"].value == "Invoice number"
    assert workbook["Invoices"]["A2"].value == "=1+1"
    assert workbook["Invoices"]["A2"].data_type == "s"
    workbook.close()


def test_target_collision_never_overwrites(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original")
    plan = build_plan(
        AutomationParams(source_file=str(source), new_name="target.txt"), [str(tmp_path)], 1
    )
    target = tmp_path / "target.txt"
    target.write_text("unrelated content")
    result = execute_plan(
        plan, get_scope=lambda: ([str(tmp_path)], 1), backup_dir=tmp_path / "backups"
    )
    assert result["status"] == "failed"
    assert source.read_text() == "original"
    assert target.read_text() == "unrelated content"


def test_changed_source_stops_before_first_mutation(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original")
    plan = build_plan(
        AutomationParams(source_file=str(source), new_name="target.txt"), [str(tmp_path)], 1
    )
    source.write_text("updated after approval")
    result = execute_plan(
        plan, get_scope=lambda: ([str(tmp_path)], 1), backup_dir=tmp_path / "backups"
    )
    assert result["status"] == "failed"
    assert result["steps"] == []
    assert source.exists()
    assert not (tmp_path / "target.txt").exists()


def test_revocation_between_steps_preserves_partial_progress(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original")
    plan = build_plan(
        AutomationParams(
            source_file=str(source),
            new_name="renamed.txt",
            destination_folder=str(tmp_path / "archive"),
        ),
        [str(tmp_path)],
        1,
    )
    calls = iter([1, 1, 2])
    result = execute_plan(
        plan, get_scope=lambda: ([str(tmp_path)], next(calls)), backup_dir=tmp_path / "backups"
    )
    assert result["status"] == "failed"
    assert result["steps"][0]["status"] == "succeeded"
    assert (tmp_path / "renamed.txt").exists()
    assert not (tmp_path / "archive" / "renamed.txt").exists()


@pytest.mark.parametrize(
    "filename",
    [
        "../outside.txt",
        "CON.txt",
        "nested/name.txt",
        "{stem.__class__}.txt",
        "{unknown}.txt",
        "name.txt:stream",
        "name.txt.",
    ],
)
def test_invalid_filename_templates_are_rejected(tmp_path, filename):
    source = tmp_path / "source.txt"
    source.write_text("data")
    with pytest.raises((ScopeError, ValueError)):
        build_plan(AutomationParams(source_file=str(source), new_name=filename), [str(tmp_path)], 1)
    assert source.exists()


def test_paths_cannot_escape_approved_folder(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "source.txt"
    source.write_text("data")
    with pytest.raises(ScopeError):
        build_plan(
            AutomationParams(source_file=str(source), destination_folder=str(tmp_path / "outside")),
            [str(allowed)],
            1,
        )
    with pytest.raises(ScopeError):
        build_plan(
            AutomationParams(source_file=str(allowed / ".." / "source.txt"), new_name="x.txt"),
            [str(allowed)],
            1,
        )


def test_symlink_input_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("outside")
    link = allowed / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This Windows account does not have permission to create symlinks.")
    with pytest.raises(ScopeError):
        build_plan(AutomationParams(source_file=str(link), new_name="x.txt"), [str(allowed)], 1)


def test_invoice_total_and_date_do_not_pick_subtotal_or_due_date(tmp_path):
    source = tmp_path / "invoice.pdf"
    write_invoice(
        source,
        [
            "Invoice Number: INV-42",
            "Due Date: 2026-12-01",
            "Invoice Date: 2026-11-06",
            "Subtotal: USD 100.00",
            "Tax: USD 49.50",
            "Total Due: USD 149.50",
        ],
    )
    assert invoice_fields(source) == {
        "invoice_number": "INV-42",
        "invoice_date": "2026-11-06",
        "amount": "149.50",
    }


def test_failed_unlink_after_link_rolls_back_target(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("original")
    target = tmp_path / "target.txt"
    real_unlink = Path.unlink

    def failing_unlink(self, missing_ok=False):
        if self == source:
            raise OSError(errno.EACCES, "simulated unlink failure")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    monkeypatch.setattr(os, "name", "posix")
    with pytest.raises(OSError):
        move_without_overwrite(source, target)
    assert source.exists()
    assert not target.exists()


def test_invalid_pdf_has_an_actionable_error(tmp_path):
    source = tmp_path / "invalid.pdf"
    source.write_text("Not a PDF")
    with pytest.raises(ValueError, match="PDF could not be read"):
        invoice_fields(source)


def test_invalid_workbook_does_not_modify_inputs(tmp_path):
    source = tmp_path / "invoice.pdf"
    write_invoice(source)
    tracker = tmp_path / "invalid.xlsx"
    tracker.write_text("not an Excel file")
    with pytest.raises(ValueError, match="valid .xlsx"):
        build_plan(
            AutomationParams(
                source_file=str(source), extract_invoice=True, tracker_file=str(tracker)
            ),
            [str(tmp_path)],
            1,
        )
    assert tracker.read_text() == "not an Excel file"
    assert source.exists()
