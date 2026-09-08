# === LICENSE HEADER START ===
# Copyright (c) 2026 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

"""Parse Stripe unified payments CSV and reconcile against work sessions / income lines."""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

REQUIRED_HEADERS = {
    "id",
    "Created date (UTC)",
    "Amount",
    "Fee",
    "Statement Descriptor",
    "Status",
}

BALANCE_HISTORY_HEADERS = {
    "id",
    "Type",
    "Amount",
    "Fee",
    "Net",
    "Currency",
    "Created (UTC)",
    "Description",
}

DEFAULT_BALANCE_FEE_PROJECT = "Stripe fees"

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_REVIEW_ROWS = 500


def normalize_descriptor(value: str | None) -> str:
    """casefold + collapse whitespace for statement_descriptor ↔ project matching."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def _money(value: Any) -> Decimal | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _money_eq(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a.quantize(Decimal("0.01")) == b.quantize(Decimal("0.01"))


def _parse_created_utc(raw: str) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if "T" in s or " " in s else s[:10], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


@dataclass
class StripePaymentRow:
    stripe_charge_id: str
    created_at_utc: str  # ISO-ish for JSON/session
    work_date: str  # YYYY-MM-DD from created UTC
    gross_amount: str
    fee_amount: str
    net_amount: str
    currency: str
    status: str
    description: str
    statement_descriptor: str
    customer_email: str
    amount_refunded: str

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def gross_decimal(self) -> Decimal:
        return Decimal(self.gross_amount)

    @property
    def fee_decimal(self) -> Decimal:
        return Decimal(self.fee_amount)

    @property
    def work_date_obj(self) -> date:
        return date.fromisoformat(self.work_date)


def parse_unified_payments_csv(
    data: bytes,
    *,
    skip_non_paid: bool = True,
    skip_zero_gross: bool = True,
) -> tuple[list[StripePaymentRow], list[str]]:
    """
    Parse Stripe unified payments CSV bytes.
    Returns (rows, errors). Raises ValueError for fatal format issues.
    """
    if not data:
        raise ValueError("Empty file.")
    if len(data) > MAX_CSV_BYTES:
        raise ValueError(f"File too large (max {MAX_CSV_BYTES // (1024 * 1024)} MB).")

    # Strip UTF-8 BOM if present
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")

    headers = {h.strip() for h in reader.fieldnames if h}
    missing = REQUIRED_HEADERS - headers
    if missing:
        raise ValueError(
            "Not a Stripe unified payments CSV (missing columns: "
            + ", ".join(sorted(missing))
            + ")."
        )

    rows: list[StripePaymentRow] = []
    errors: list[str] = []
    for i, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_REVIEW_ROWS:
            errors.append(f"Stopped after {MAX_REVIEW_ROWS} rows (limit).")
            break

        charge_id = (raw.get("id") or "").strip()
        if not charge_id:
            errors.append(f"Row {i}: missing charge id.")
            continue

        status = (raw.get("Status") or "").strip()
        if skip_non_paid and status.casefold() != "paid":
            continue

        gross = _money(raw.get("Amount"))
        if gross is None:
            errors.append(f"Row {i}: invalid Amount.")
            continue
        refunded = _money(raw.get("Amount Refunded")) or Decimal("0.00")
        effective_gross = (gross - refunded).quantize(Decimal("0.01"))
        if skip_zero_gross and effective_gross <= 0:
            continue

        fee = _money(raw.get("Fee"))
        if fee is None:
            fee = Decimal("0.00")
        if fee < 0:
            fee = Decimal("0.00")

        created = _parse_created_utc(raw.get("Created date (UTC)") or "")
        if not created:
            errors.append(f"Row {i}: invalid Created date (UTC).")
            continue

        currency = (raw.get("Currency") or "").strip().upper() or "CAD"
        desc = (raw.get("Description") or "").strip()
        descriptor = (raw.get("Statement Descriptor") or "").strip()
        email = (raw.get("Customer Email") or "").strip()
        net = (effective_gross - fee).quantize(Decimal("0.01"))

        rows.append(
            StripePaymentRow(
                stripe_charge_id=charge_id,
                created_at_utc=created.strftime("%Y-%m-%d %H:%M:%S"),
                work_date=created.date().isoformat(),
                gross_amount=f"{effective_gross:.2f}",
                fee_amount=f"{fee:.2f}",
                net_amount=f"{net:.2f}",
                currency=currency,
                status=status,
                description=desc,
                statement_descriptor=descriptor,
                customer_email=email,
                amount_refunded=f"{refunded:.2f}",
            )
        )

    return rows, errors


def suggest_session_id(
    payment: StripePaymentRow,
    sessions: list[dict],
) -> int | None:
    """
    New imports default to creating a session (not attaching to an existing one).
    Returns None so the UI selects Create session. Same-day charges are grouped
    at apply time when Create is chosen for multiple rows.
    """
    return None


def _session_work_date(sess: dict) -> date | None:
    wd = sess.get("work_date")
    if wd is None:
        return None
    if isinstance(wd, date) and not isinstance(wd, datetime):
        return wd
    if isinstance(wd, datetime):
        return wd.date()
    try:
        return date.fromisoformat(str(wd)[:10])
    except ValueError:
        return None


def reconcile_payment(
    payment: StripePaymentRow,
    *,
    income_by_charge: dict[str, dict],
    income_fallback: list[dict],
    sessions: list[dict],
) -> dict:
    """
    Build a review row dict with status and suggested session.
    Statuses: matched | mismatch | missing
    New imports suggest Create session (suggested_session_id None).
    Already-imported rows suggest their existing income session for updates.
    """
    existing = income_by_charge.get(payment.stripe_charge_id)

    if not existing:
        # Fallback: date + gross + fee + normalized descriptor
        norm = normalize_descriptor(payment.statement_descriptor)
        for inc in income_fallback:
            if normalize_descriptor(inc.get("statement_descriptor") or "") != norm:
                continue
            if not _money_eq(_money(inc.get("amount")), payment.gross_decimal):
                continue
            if not _money_eq(_money(inc.get("fee_amount")) or Decimal("0.00"), payment.fee_decimal):
                continue
            existing = inc
            break

    base = {
        **payment.to_dict(),
        "stripe_status": payment.status,
        "suggested_session_id": None,
        "existing_income_id": int(existing["id"]) if existing else None,
        "existing_session_id": int(existing["session_id"]) if existing else None,
        "existing_gross": f"{_money(existing['amount']):.2f}" if existing else None,
        "existing_fee": (
            f"{(_money(existing.get('fee_amount')) or Decimal('0.00')):.2f}"
            if existing
            else None
        ),
        "project_norm": normalize_descriptor(payment.statement_descriptor),
    }

    if existing:
        gross_ok = _money_eq(_money(existing.get("amount")), payment.gross_decimal)
        fee_ok = _money_eq(
            _money(existing.get("fee_amount")) or Decimal("0.00"),
            payment.fee_decimal,
        )
        if gross_ok and fee_ok:
            base["status"] = "matched"
            base["status_label"] = "Matched"
        else:
            base["status"] = "mismatch"
            base["status_label"] = "Gross/fee mismatch"
        # Updates stay on the session that already holds this charge
        base["suggested_session_id"] = int(existing["session_id"])
        return base

    base["status"] = "missing"
    base["status_label"] = "Missing (not imported)"
    return base


def build_review_rows(
    payments: list[StripePaymentRow],
    *,
    sessions: list[dict],
    income_rows: list[dict],
) -> list[dict]:
    by_charge = {
        str(r["stripe_charge_id"]): r
        for r in income_rows
        if r.get("stripe_charge_id")
    }
    fallback = [r for r in income_rows if r.get("statement_descriptor") is not None]
    rows = [
        reconcile_payment(
            p,
            income_by_charge=by_charge,
            income_fallback=fallback,
            sessions=sessions,
        )
        for p in payments
    ]
    for r in rows:
        r["row_kind"] = "payment"
    return rows


def detect_stripe_csv_kind(data: bytes) -> str | None:
    """Return 'unified_payments', 'balance_history', or None."""
    if not data:
        return None
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return None
    headers = {h.strip() for h in reader.fieldnames if h}
    if REQUIRED_HEADERS.issubset(headers):
        return "unified_payments"
    if BALANCE_HISTORY_HEADERS.issubset(headers):
        return "balance_history"
    return None


@dataclass
class StripeBalanceFeeRow:
    """Stripe balance-history fee (e.g. Billing usage) — expense only."""

    stripe_txn_id: str
    created_at_utc: str
    work_date: str
    amount: str  # signed CSV amount
    fee: str
    net: str  # signed
    expense_amount: str  # abs(net) booked as expense
    currency: str
    description: str
    txn_type: str
    project: str

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def expense_decimal(self) -> Decimal:
        return Decimal(self.expense_amount)


def parse_balance_history_csv(data: bytes) -> tuple[list[StripeBalanceFeeRow], list[str]]:
    """
    Parse Stripe balance history CSV.
    Imports Type=stripe_fee rows (Billing usage / subscription platform fees).
    Skips charge rows (use unified payments for those).
    Expense amount = abs(Net) — what left the Stripe balance.
    """
    if not data:
        raise ValueError("Empty file.")
    if len(data) > MAX_CSV_BYTES:
        raise ValueError(f"File too large (max {MAX_CSV_BYTES // (1024 * 1024)} MB).")

    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")

    headers = {h.strip() for h in reader.fieldnames if h}
    missing = BALANCE_HISTORY_HEADERS - headers
    if missing:
        raise ValueError(
            "Not a Stripe balance history CSV (missing columns: "
            + ", ".join(sorted(missing))
            + ")."
        )

    rows: list[StripeBalanceFeeRow] = []
    errors: list[str] = []
    skipped_charges = 0
    skipped_other = 0

    for i, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_REVIEW_ROWS:
            errors.append(f"Stopped after {MAX_REVIEW_ROWS} fee rows (limit).")
            break

        txn_type = (raw.get("Type") or "").strip().casefold()
        if txn_type == "charge":
            skipped_charges += 1
            continue
        if txn_type != "stripe_fee":
            skipped_other += 1
            continue

        txn_id = (raw.get("id") or "").strip()
        if not txn_id:
            errors.append(f"Row {i}: missing transaction id.")
            continue

        net = _money(raw.get("Net"))
        if net is None:
            errors.append(f"Row {i}: invalid Net.")
            continue
        expense = abs(net).quantize(Decimal("0.01"))
        if expense <= 0:
            continue

        amount = _money(raw.get("Amount")) or Decimal("0.00")
        fee = _money(raw.get("Fee")) or Decimal("0.00")
        created = _parse_created_utc(raw.get("Created (UTC)") or "")
        if not created:
            errors.append(f"Row {i}: invalid Created (UTC).")
            continue

        currency = (raw.get("Currency") or "").strip().upper() or "CAD"
        desc = (raw.get("Description") or "").strip() or f"Stripe fee {txn_id}"

        rows.append(
            StripeBalanceFeeRow(
                stripe_txn_id=txn_id,
                created_at_utc=created.strftime("%Y-%m-%d %H:%M:%S"),
                work_date=created.date().isoformat(),
                amount=f"{amount:.2f}",
                fee=f"{fee:.2f}",
                net=f"{net:.2f}",
                expense_amount=f"{expense:.2f}",
                currency=currency,
                description=desc,
                txn_type=(raw.get("Type") or "").strip(),
                project=DEFAULT_BALANCE_FEE_PROJECT,
            )
        )

    if skipped_charges:
        errors.append(
            f"Skipped {skipped_charges} charge row(s) — import those via unified payments CSV."
        )
    if skipped_other:
        errors.append(f"Skipped {skipped_other} non-fee balance row(s).")

    return rows, errors


def reconcile_balance_fee(
    fee_row: StripeBalanceFeeRow,
    *,
    expense_by_txn: dict[str, dict],
) -> dict:
    existing = expense_by_txn.get(fee_row.stripe_txn_id)
    base = {
        **fee_row.to_dict(),
        "row_kind": "balance_fee",
        # Align with payment review fields used by the template / apply loop
        "stripe_charge_id": fee_row.stripe_txn_id,
        "statement_descriptor": fee_row.project,
        "gross_amount": "—",
        "fee_amount": fee_row.expense_amount,
        "net_amount": fee_row.net,
        "customer_email": "",
        "stripe_status": fee_row.txn_type,
        "project_norm": normalize_descriptor(fee_row.project),
        "suggested_session_id": None,
        "existing_income_id": None,
        "existing_session_id": int(existing["session_id"]) if existing else None,
        "existing_gross": None,
        "existing_fee": (
            f"{_money(existing.get('amount')):.2f}" if existing else None
        ),
    }
    if existing:
        if _money_eq(_money(existing.get("amount")), fee_row.expense_decimal):
            base["status"] = "matched"
            base["status_label"] = "Matched"
        else:
            base["status"] = "mismatch"
            base["status_label"] = "Amount mismatch"
        base["suggested_session_id"] = int(existing["session_id"])
        return base

    base["status"] = "missing"
    base["status_label"] = "Missing (not imported)"
    return base


def build_balance_fee_review_rows(
    fees: list[StripeBalanceFeeRow],
    *,
    expense_rows: list[dict],
) -> list[dict]:
    by_txn = {
        str(r["stripe_charge_id"]): r
        for r in expense_rows
        if r.get("stripe_charge_id")
    }
    return [reconcile_balance_fee(f, expense_by_txn=by_txn) for f in fees]
