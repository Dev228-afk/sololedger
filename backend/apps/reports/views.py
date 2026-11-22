from __future__ import annotations

import csv
import datetime as dt
import io
from collections import defaultdict
from typing import Any

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.http import StreamingHttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api_schemas import MonthlyReportResponseSerializer
from apps.accounts.auth import SoloLedgerApiError, require_account
from apps.categorization.models import CategoryKind
from apps.transactions.models import Transaction
from apps.transactions.money import minor_to_decimal_str, sanitize_csv_cell
from apps.transactions.views import filter_transactions_queryset


def _parse_month_bounds(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    parts = raw.strip().split("-")
    if len(parts) != 2:
        raise SoloLedgerApiError(
            status_code=400,
            code="INVALID_FILTER",
            message=f"Invalid month '{raw}'; expected YYYY-MM.",
        )
    try:
        year = int(parts[0])
        month = int(parts[1])
        dt.date(year, month, 1)
        return year, month
    except ValueError as exc:
        raise SoloLedgerApiError(
            status_code=400,
            code="INVALID_FILTER",
            message=f"Invalid month '{raw}'; expected YYYY-MM.",
        ) from exc


class MonthlyReportView(APIView):
    @extend_schema(responses={200: MonthlyReportResponseSerializer})
    def get(self, request: Request) -> Response:
        account = require_account(request._request)
        currency = str(request.query_params.get("currency", "USD")).upper()
        if currency != "USD":
            raise SoloLedgerApiError(
                status_code=422,
                code="UNSUPPORTED_CURRENCY",
                message="Monthly report MVP supports currency=USD only.",
            )

        from_bounds = _parse_month_bounds(request.query_params.get("fromMonth"))
        to_bounds = _parse_month_bounds(request.query_params.get("toMonth"))

        qs = Transaction.objects.filter(account=account, currency="USD")
        if from_bounds:
            qs = qs.filter(posted_date__gte=dt.date(from_bounds[0], from_bounds[1], 1))
        if to_bounds:
            # Inclusive month end by setting exclusive first day of following month
            if to_bounds[1] == 12:
                next_month_start = dt.date(to_bounds[0] + 1, 1, 1)
            else:
                next_month_start = dt.date(to_bounds[0], to_bounds[1] + 1, 1)
            qs = qs.filter(posted_date__lt=next_month_start)

        if from_bounds and to_bounds:
            total_months = (to_bounds[0] - from_bounds[0]) * 12 + (to_bounds[1] - from_bounds[1]) + 1
            if total_months < 1 or total_months > 24:
                raise SoloLedgerApiError(
                    status_code=422,
                    code="INVALID_RANGE",
                    message="Report month range must be between 1 and 24 months.",
                )

        rows = (
            qs.annotate(month_start=TruncMonth("posted_date"))
            .values("month_start", "category__code", "category__name", "category__kind")
            .annotate(sum_minor=Sum("amount_minor"))
            .order_by("month_start", "category__code")
        )

        # Also compute monthly positive credits (income/refunds) & negative debits per month accurately in SQL
        monthly_debits_map: dict[str, int] = defaultdict(int)
        monthly_credits_map: dict[str, int] = defaultdict(int)
        for row in (
            qs.filter(amount_minor__lt=0)
            .exclude(category__kind=CategoryKind.TRANSFER)
            .annotate(month_start=TruncMonth("posted_date"))
            .values("month_start")
            .annotate(deb=Sum("amount_minor"))
        ):
            m_key = row["month_start"].strftime("%Y-%m")
            monthly_debits_map[m_key] = -int(row["deb"] or 0)

        for row in (
            qs.filter(amount_minor__gt=0)
            .exclude(category__kind=CategoryKind.TRANSFER)
            .annotate(month_start=TruncMonth("posted_date"))
            .values("month_start")
            .annotate(cred=Sum("amount_minor"))
        ):
            m_key = row["month_start"].strftime("%Y-%m")
            monthly_credits_map[m_key] = int(row["cred"] or 0)

        months_data: dict[str, dict[str, Any]] = {}
        category_grand_totals: dict[str, dict[str, Any]] = {}

        for row in rows:
            month_str = row["month_start"].strftime("%Y-%m")
            if month_str not in months_data:
                months_data[month_str] = {
                    "month": month_str,
                    "byCategory": [],
                    "_netSpendMinor": 0,
                }
            kind = row["category__kind"]
            if kind != CategoryKind.EXPENSE:
                continue
            code = row["category__code"]
            name = row["category__name"]
            # Exact accounting rule: refunds (+) reduce netSpend (-SUM(amount_minor)), allowing negative net spend cleanly
            net_spend_minor = -int(row["sum_minor"] or 0)
            months_data[month_str]["byCategory"].append(
                {
                    "code": code,
                    "name": name,
                    "netSpend": minor_to_decimal_str(net_spend_minor),
                }
            )
            months_data[month_str]["_netSpendMinor"] += net_spend_minor

            if code not in category_grand_totals:
                category_grand_totals[code] = {"code": code, "name": name, "_minor": 0}
            category_grand_totals[code]["_minor"] += net_spend_minor

        formatted_months = []
        for m_str in sorted(months_data.keys()):
            item = months_data[m_str]
            formatted_months.append(
                {
                    "month": m_str,
                    "byCategory": sorted(item["byCategory"], key=lambda x: x["code"]),
                    "netSpend": minor_to_decimal_str(item["_netSpendMinor"]),
                    "totalCredits": minor_to_decimal_str(monthly_credits_map.get(m_str, 0)),
                    "totalDebits": minor_to_decimal_str(monthly_debits_map.get(m_str, 0)),
                }
            )

        ranked_categories = [
            {
                "code": entry["code"],
                "name": entry["name"],
                "netSpend": minor_to_decimal_str(entry["_minor"]),
            }
            for entry in sorted(category_grand_totals.values(), key=lambda x: -x["_minor"])
        ]

        return Response(
            {
                "currency": "USD",
                "months": formatted_months,
                "categoryTotals": ranked_categories,
            }
        )


class LedgerCsvExportView(APIView):
    @extend_schema(responses={(200, "text/csv"): bytes})
    def get(self, request: Request) -> StreamingHttpResponse:
        account = require_account(request._request)
        qs = filter_transactions_queryset(account, request.query_params)

        def row_generator():
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(
                [
                    "Transaction ID",
                    "Posted Date",
                    "Description",
                    "Normalized Merchant",
                    "Signed Amount",
                    "Currency",
                    "Category Code",
                    "Review Status",
                    "Source",
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

            for txn in qs.iterator(chunk_size=250):
                # Escape text cells for Excel/spreadsheet safety while preserving signed numeric amount exact
                writer.writerow(
                    [
                        str(txn.id),
                        txn.posted_date.isoformat(),
                        sanitize_csv_cell(txn.description),
                        sanitize_csv_cell(txn.normalized_merchant),
                        minor_to_decimal_str(txn.amount_minor),
                        txn.currency,
                        sanitize_csv_cell(txn.category.code),
                        txn.review_status,
                        txn.category_source,
                    ]
                )
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)

        res = StreamingHttpResponse(row_generator(), content_type="text/csv; charset=utf-8")
        res["Content-Disposition"] = 'attachment; filename="sololedger-ledger.csv"'
        return res
