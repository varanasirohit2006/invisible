"""A small, allowlisted runner. No shell, generated code, deletes or overwrites.

The one intentional overwrite is an explicitly previewed Excel append: it uses
a backup, a temporary workbook, an unchanged-input check, and atomic replacement.
Multi-step runs are not transactions; completed steps remain visible on failure.
"""

import errno
import hashlib
import os
import re
import shutil
import stat
import string
import time
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from shared.models import Action, AutomationParams, FrozenPlan
from shared.paths import Scope, ScopeError, safe_filename

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError("Choose a regular file smaller than 256 MB.")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise ValueError(
            "The file is still changing. Wait for it to finish saving and preview again."
        )
    return digest.hexdigest()


def verify_inputs(plan: FrozenPlan, scope: Scope):
    for value, expected in plan.fingerprints.items():
        path = scope.check(value)
        if fingerprint(path) != expected:
            raise ValueError(
                f"{path.name} changed since preview. Create and approve a new preview."
            )


def invoice_fields(path: Path) -> dict[str, str]:
    import pdfplumber

    if path.suffix.lower() != ".pdf" or path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Invoice extraction requires a PDF smaller than 20 MB.")
    try:
        with pdfplumber.open(path) as document:
            if len(document.pages) > 20:
                raise ValueError("Invoice extraction supports PDFs with at most 20 pages.")
            text = "\n".join(page.extract_text() or "" for page in document.pages)[:300_000]
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("This PDF could not be read. Use a valid, unencrypted PDF.") from error
    patterns = {
        "invoice_number": [
            r"(?im)\binvoice\s*(?:number|no\.?|#|id)\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9_/-]{0,80})"
        ],
        "invoice_date": [
            rf"(?im){label}\s*:?\s*(\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}|\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{4}})"
            for label in (r"\binvoice\s+date", r"^\s*date")
        ],
        "amount": [
            rf"(?im)\b(?:{label})\s*:?\s*(?:USD|INR|EUR|GBP|Rs\.?)?\s*[$₹€£]?\s*([0-9][0-9,]*(?:\.[0-9]{{1,2}})?)"
            for label in (r"grand\s+total|amount\s+due|total\s+due", r"total")
        ],
    }
    result = {}
    for field, alternatives in patterns.items():
        for pattern in alternatives:
            match = re.search(pattern, text)
            if match:
                result[field] = match.group(1).strip()
                break
    return result


def normalized_invoice(fields: dict[str, str]) -> dict[str, str]:
    missing = [
        key.replace("_", " ")
        for key in ("invoice_number", "invoice_date", "amount")
        if not fields.get(key)
    ]
    if missing:
        raise ValueError(
            f"Could not read {', '.join(missing)}. Enter the missing invoice fields and preview again."
        )
    parsed_date = None
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            parsed_date = datetime.strptime(fields["invoice_date"], pattern).date().isoformat()
            break
        except ValueError:
            continue
    if not parsed_date:
        raise ValueError("Enter the invoice date as YYYY-MM-DD (slash dates use day/month/year).")
    try:
        amount = Decimal(fields["amount"].replace(",", ""))
        if not amount.is_finite() or amount < 0 or amount > Decimal("1000000000000"):
            raise InvalidOperation
    except InvalidOperation as error:
        raise ValueError("Enter a non-negative invoice amount using a decimal point.") from error
    return {**fields, "invoice_date": parsed_date, "amount": str(amount.quantize(Decimal("0.01")))}


def render_filename(template: str, values: dict[str, str]) -> str:
    for _, field, spec, conversion in string.Formatter().parse(template):
        if field is not None and (field not in values or spec or conversion):
            raise ValueError(
                "Use only {stem}, {date}, {invoice_number}, {invoice_date}, or {amount} in the filename."
            )
    # Sanitize the substituted identifier only. Literal paths in a template still
    # fail validation, and extracted fields / tracker values retain the original.
    filename_values = dict(values)
    if "invoice_number" in filename_values:
        filename_values["invoice_number"] = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]', "-", filename_values["invoice_number"]
        )
    return safe_filename(template.format_map(filename_values))


def validate_workbook(path: Path, sheet: str):
    if path.suffix.lower() != ".xlsx":
        raise ValueError("The tracker must be an .xlsx workbook; macros are not supported.")
    if re.search(r"[\\/*?:\[\]\x00-\x1f]", sheet) or sheet.startswith("'") or sheet.endswith("'"):
        raise ValueError("Enter a valid Excel sheet name.")
    if path.exists():
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ValueError("Choose a tracker smaller than 20 MB.")
        try:
            with zipfile.ZipFile(path) as archive:
                if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
                    raise ValueError("The expanded workbook is too large.")
        except zipfile.BadZipFile as error:
            raise ValueError("The tracker is not a valid .xlsx workbook.") from error
        from openpyxl import load_workbook

        try:
            workbook = load_workbook(path, read_only=True, keep_links=False)
        except Exception as error:
            raise ValueError("The tracker could not be read as an .xlsx workbook.") from error
        try:
            if sheet in workbook.sheetnames:
                worksheet = workbook[sheet]
                max_row = worksheet.max_row
                if max_row is None:
                    # Some writers omit dimensions. Stream one column to count
                    # rows, including sparse rows, without loading the workbook.
                    max_row = sum(1 for _ in worksheet.iter_rows(min_col=1, max_col=1))
                if max_row >= 1_048_576:
                    raise ValueError("The selected worksheet has no empty rows.")
        finally:
            workbook.close()


def build_plan(params: AutomationParams, folders: list[str], scope_revision: int) -> FrozenPlan:
    scope = Scope(folders)
    source = scope.check(params.source_file, exists=True)
    original_hash = fingerprint(source)
    fingerprints = {str(source): original_hash}
    actions: list[Action] = []
    extracted: dict[str, str] = {}
    if params.extract_invoice:
        extracted = invoice_fields(source)
        overrides = {
            "invoice_number": params.invoice_number,
            "invoice_date": params.invoice_date,
            "amount": params.invoice_amount,
        }
        extracted.update({key: value.strip() for key, value in overrides.items() if value.strip()})
        extracted = normalized_invoice(extracted)
        actions.append(
            Action(
                kind="extract_pdf",
                source=str(source),
                description="Read and verify the reviewed invoice fields.",
            )
        )
    if params.tracker_file and not params.extract_invoice:
        raise ValueError("Enable invoice extraction before adding a tracker row.")

    current = source
    values = {"stem": source.stem, "date": datetime.now(UTC).date().isoformat(), **extracted}
    if params.new_name.strip():
        target = scope.check(current.with_name(render_filename(params.new_name.strip(), values)))
        if target != current:
            if target.exists():
                raise FileExistsError(f"{target.name} already exists. Choose a different name.")
            fingerprints[str(target)] = None
            actions.append(
                Action(
                    kind="rename",
                    source=str(current),
                    target=str(target),
                    description=f"Rename {current.name} to {target.name}.",
                )
            )
            current = target
    if params.destination_folder.strip():
        target = scope.check(Path(params.destination_folder.strip()) / current.name)
        if target != current:
            if target.exists():
                raise FileExistsError(f"{target.name} already exists in the destination.")
            fingerprints[str(target)] = None
            actions.append(
                Action(
                    kind="move",
                    source=str(current),
                    target=str(target),
                    description=f"Move to {target.parent}. Create destination folders if needed.",
                )
            )
            current = target
    if params.tracker_file.strip():
        tracker = scope.check(params.tracker_file.strip())
        if str(tracker) in fingerprints:
            raise ValueError("The tracker must be separate from the file being organized.")
        validate_workbook(tracker, params.tracker_sheet)
        fingerprints[str(tracker)] = fingerprint(tracker)
        actions.append(
            Action(
                kind="append_excel",
                source=str(tracker),
                sheet=params.tracker_sheet,
                values=[
                    extracted["invoice_number"],
                    extracted["invoice_date"],
                    float(extracted["amount"]),
                    str(current),
                ],
                description=f"Append one row to {tracker.name} / {params.tracker_sheet}. Back up an existing workbook first.",
            )
        )
    if not any(action.kind != "extract_pdf" for action in actions):
        raise ValueError("Set a different filename, a destination folder, or an invoice tracker.")
    plan = FrozenPlan(
        actions=actions,
        fingerprints=fingerprints,
        scope_revision=scope_revision,
        extracted_fields=extracted,
    )
    verify_inputs(plan, scope)
    return plan


def move_without_overwrite(source: Path, target: Path):
    """Use no-replace primitives, including for cross-volume copies."""
    try:
        if os.name == "nt":
            os.rename(source, target)  # Windows rename rejects an existing target.
        else:
            os.link(source, target)
            try:
                source.unlink()
            except OSError:
                # A failed unlink must not leave the run half-moved; restore the
                # original state and let the caller report the failure.
                target.unlink(missing_ok=True)
                raise
        return
    except OSError as error:
        if error.errno != errno.EXDEV and getattr(error, "winerror", None) != 17:
            raise
    created = False
    try:
        with source.open("rb") as read, target.open("xb") as write:
            created = True
            shutil.copyfileobj(read, write, 1024 * 1024)
            write.flush()
            os.fsync(write.fileno())
        if fingerprint(source) != fingerprint(target):
            raise ValueError("The source changed while copying. It was not removed.")
        shutil.copystat(source, target)
        source.unlink()
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


def append_workbook(
    action: Action, scope: Scope, expected: str | None, backup_dir: Path
) -> str | None:
    from openpyxl import Workbook, load_workbook

    path = scope.check(action.source)
    validate_workbook(path, action.sheet or "Invoices")
    backup = None
    if path.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{uuid4().hex}-{path.name}"
        shutil.copy2(path, backup_path)
        if fingerprint(backup_path) != expected:
            raise ValueError("The workbook changed before its backup was created.")
        backup = str(backup_path)
        workbook = load_workbook(path, keep_links=False)
    else:
        workbook = Workbook()
        workbook.active.title = action.sheet or "Invoices"
    temporary = path.parent / f".iwd-{uuid4().hex}.xlsx"
    try:
        sheet_name = action.sheet or "Invoices"
        sheet = (
            workbook[sheet_name]
            if sheet_name in workbook.sheetnames
            else workbook.create_sheet(sheet_name)
        )
        if sheet.max_row == 1 and all(cell.value is None for cell in sheet[1]):
            for column, heading in enumerate(
                ["Invoice number", "Invoice date", "Amount", "File"], 1
            ):
                sheet.cell(1, column, heading)
        row = sheet.max_row + 1
        for column, value in enumerate(action.values, 1):
            cell = sheet.cell(row, column, value)
            if isinstance(value, str):
                cell.data_type = "s"  # A filename or invoice number beginning '=' stays literal.
        path.parent.mkdir(parents=True, exist_ok=True)
        scope.check(temporary)
        with temporary.open("xb") as handle:
            workbook.save(handle)
        scope.check(path)
        if fingerprint(path) != expected:
            raise ValueError("The tracker changed during the run. The edited copy was not applied.")
        if expected is None:
            move_without_overwrite(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        workbook.close()
        temporary.unlink(missing_ok=True)
    return backup


def execute_plan(
    plan: FrozenPlan,
    *,
    get_scope: Callable[[], tuple[list[str], int]],
    backup_dir: Path,
    on_progress: Callable[[list[dict]], None] | None = None,
    suppress: Callable[[list[str]], None] | None = None,
) -> dict:
    started = time.monotonic()
    results: list[dict] = []
    expected = dict(plan.fingerprints)
    backups: list[str] = []
    try:
        folders, revision = get_scope()
        if revision != plan.scope_revision:
            raise ScopeError("Folder permissions changed. Preview and approve the plan again.")
        verify_inputs(plan, Scope(folders))
        for index, action in enumerate(plan.actions):
            folders, revision = get_scope()
            if revision != plan.scope_revision:
                raise ScopeError("Folder permissions were revoked during this run.")
            scope = Scope(folders)
            source = scope.check(action.source)
            if fingerprint(source) != expected.get(str(source)):
                raise ValueError(f"{source.name} changed during this run.")
            if suppress:
                suppress([action.source, *([action.target] if action.target else [])])
            result = {
                "index": index + 1,
                "kind": action.kind,
                "description": action.description,
                "status": "running",
            }
            results.append(result)
            if on_progress:
                on_progress(results)
            if action.kind in {"rename", "move"}:
                source = scope.check(action.source, exists=True)
                target = scope.check(action.target or "")
                if target.exists():
                    raise FileExistsError(f"{target.name} already exists. No file was overwritten.")
                target.parent.mkdir(parents=True, exist_ok=True)
                scope.check(target)
                move_without_overwrite(source, target)
                expected[str(target)] = expected[str(source)]
                expected[str(source)] = None
            elif action.kind == "append_excel":
                backup = append_workbook(action, scope, expected.get(str(source)), backup_dir)
                if backup:
                    backups.append(backup)
                    result["backup"] = backup
                expected[str(source)] = fingerprint(source)
            elif action.kind == "extract_pdf":
                # Fields were extracted during preview; the source hash was checked above.
                result["fields"] = plan.extracted_fields
            result["status"] = "succeeded"
            if on_progress:
                on_progress(results)
        return {
            "status": "succeeded",
            "steps": results,
            "backups": backups,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as error:
        if results and results[-1]["status"] == "running":
            results[-1]["status"] = "failed"
        return {
            "status": "failed",
            "steps": results,
            "backups": backups,
            "error": str(error)[:1000],
            "duration_seconds": round(time.monotonic() - started, 3),
        }
