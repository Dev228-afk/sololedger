#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import random
from pathlib import Path

from faker import Faker

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "fixtures"
STATEMENTS_DIR = FIXTURES_DIR / "statements"
EDGE_DIR = FIXTURES_DIR / "import_edge_cases"

# Ground truth merchant catalog organized by merchant_family (allows clean dev/held-out family splits!)
# Includes a mix of exact-lexicon descriptions, keyword patterns, unfamiliar/ambiguous descriptions (<0.700), refunds & income.
MERCHANT_CATALOG: list[tuple[str, str, str, tuple[int, int], bool]] = [
    # (merchant_desc, category_code, merchant_family, (min_cents, max_cents), is_credit)
    ("DEMO CLOUD HOSTING", "SOFTWARE", "fam_cloud", (1800, 12000), False),
    ("SYNTHETIC CODE REPO PRO", "SOFTWARE", "fam_dev_saas", (1900, 4900), False),
    ("VECTOR DESIGN SUITE", "SOFTWARE", "fam_design", (2400, 6500), False),
    ("NOVA HOSTING CLUSTER", "SOFTWARE", "fam_nova_infra", (3200, 14500), False),
    ("BYTECRAFT TECH PLATFORM", "SOFTWARE", "fam_bytecraft", (2900, 8900), False),
    ("ACME OFFICE SUPPLIES", "OFFICE_SUPPLIES", "fam_acme_office", (1400, 7800), False),
    ("PAPER & TONER DEPOT", "OFFICE_SUPPLIES", "fam_paper_depot", (1600, 9500), False),
    ("CORNER SUPPLY HOUSE", "OFFICE_SUPPLIES", "fam_corner_supply", (1200, 5400), False),
    ("METRO RAIL PASS", "TRANSPORT", "fam_metro_rail", (2500, 13000), False),
    ("DOWNTOWN RIDE SHARE", "TRANSPORT", "fam_rideshare", (1100, 4600), False),
    ("REGIONAL TRANSIT SHUTTLE", "TRANSPORT", "fam_shuttle", (1900, 5800), False),
    ("CITY CAB EXPRESS", "TRANSPORT", "fam_city_cab", (1500, 4200), False),
    ("HARBOR ROASTERS CAFE", "MEALS", "fam_harbor_cafe", (650, 2900), False),
    ("BISTRO CLIENT LUNCH", "MEALS", "fam_bistro", (2200, 9400), False),
    ("CEDAR STREET GRILL", "MEALS", "fam_cedar_grill", (1800, 6200), False),
    ("SUMMIT COFFEE WORKS", "MEALS", "fam_summit_coffee", (700, 2600), False),
    ("NORTHGRID FIBER INTERNET", "UTILITIES", "fam_northgrid", (6500, 9900), False),
    ("CITY POWER & LIGHT", "UTILITIES", "fam_city_power", (7500, 18500), False),
    ("METRO TELECOM WIRELESS", "UTILITIES", "fam_metro_tel", (5500, 11000), False),
    ("PACIFIC CPA ADVISORY", "PROFESSIONAL_SERVICES", "fam_pacific_cpa", (15000, 65000), False),
    ("OAKRIDGE LEGAL STUDIO", "PROFESSIONAL_SERVICES", "fam_oakridge_law", (20000, 75000), False),
    ("ALDER CONSULTING PARTNERS", "PROFESSIONAL_SERVICES", "fam_alder_consult", (12000, 42000), False),
    ("SEARCH PROMO STUDIO", "MARKETING", "fam_search_promo", (5000, 35000), False),
    ("SOCIAL CAMPAIGN BOOST", "MARKETING", "fam_social_boost", (4000, 22000), False),
    ("WORKSHOP BOOK HOUSE", "EDUCATION", "fam_book_house", (2400, 9500), False),
    ("ONLINE SYSTEMS ACADEMY", "EDUCATION", "fam_sys_academy", (4900, 29900), False),
    ("ERGONOMIC DESK CO", "EQUIPMENT", "fam_ergo_desk", (12000, 59000), False),
    ("THUNDERBOLT DOCK STORE", "EQUIPMENT", "fam_dock_store", (8500, 28000), False),
    ("MONTHLY NEWS BRIEF", "SUBSCRIPTIONS", "fam_news_brief", (1200, 2900), False),
    ("CREATIVE STOCK VAULT", "SUBSCRIPTIONS", "fam_stock_vault", (2900, 7900), False),
    ("MEMBER JOURNAL CLUB", "SUBSCRIPTIONS", "fam_journal_club", (1500, 3900), False),
    ("CLIENT RETAINER PAYOUT", "INCOME", "fam_retainer", (125000, 420000), True),
    ("FREELANCE INVOICE ACH", "INCOME", "fam_invoice_ach", (85000, 310000), True),
    ("OWNER SAVINGS TRANSFER", "TRANSFER", "fam_owner_xfer", (50000, 200000), True),
    # Harder / unfamiliar merchant families requiring heuristic review or second-import correction rules
    ("NORTHWOOD MART #402", "OFFICE_SUPPLIES", "fam_northwood", (1800, 6700), False),
    ("VALLEY OUTPOST #19", "EQUIPMENT", "fam_valley_outpost", (4500, 14900), False),
    ("LAKESIDE MERCANTILE CO", "MEALS", "fam_lakeside", (1400, 5100), False),
    ("MERIDIAN ANNEX GROUP", "PROFESSIONAL_SERVICES", "fam_meridian", (11000, 28000), False),
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def format_cents(cents: int) -> str:
    neg = cents < 0
    val = abs(cents)
    s = f"{val // 100}.{val % 100:02d}"
    return f"-{s}" if neg else s


def generate_statements(seed: int, count: int, rows_per_statement: int) -> None:
    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)

    STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    EDGE_DIR.mkdir(parents=True, exist_ok=True)

    aliases = {
        "formats": [
            "DEBIT_CREDIT_STANDARD",
            "SIGNED_AMOUNT_CURRENCY",
            "SLASH_US_DATE_EXPORT",
            "COMPACT_TXN_EXPORT",
        ],
        "merchantAliases": [
            {"raw": "DEMO CLOUD HOSTING #882", "canonical": "DEMO CLOUD HOSTING"},
            {"raw": "ACME OFFICE SUPPLIES INV-104", "canonical": "ACME OFFICE SUPPLIES"},
            {"raw": "NORTHWOOD MART #402", "canonical": "NORTHWOOD MART"},
        ],
    }
    (FIXTURES_DIR / "merchant_aliases.json").write_text(
        json.dumps(aliases, indent=2) + "\n", encoding="utf-8"
    )

    gt_rows: list[list[str]] = []
    manifest_lines: list[str] = []

    base_start = dt.date(2026, 1, 1)

    for stmt_idx in range(1, count + 1):
        style = (stmt_idx - 1) % 4
        stmt_path = STATEMENTS_DIR / f"sample_{stmt_idx:02d}.csv"
        month_offset = (stmt_idx - 1) % 6
        stmt_start = dt.date(2026, 1 + month_offset, 1)

        with stmt_path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp, lineterminator="\n")
            if style == 0:
                writer.writerow(["Posted Date", "Merchant", "Debit", "Credit", "Transaction ID"])
            elif style == 1:
                writer.writerow(["Date", "Description", "Amount", "Currency"])
            elif style == 2:
                writer.writerow(["Transaction Date", "Payee", "Withdrawal", "Deposit", "Reference"])
            else:
                writer.writerow(["Posted Date", "Description", "Signed Amount", "Currency", "Txn ID"])

            for r_idx in range(rows_per_statement):
                day_delta = (r_idx * 27) // max(1, rows_per_statement)
                posted = stmt_start + dt.timedelta(days=day_delta)
                desc, cat, family, (lo, hi), is_credit = rng.choice(MERCHANT_CATALOG)
                cents_mag = rng.randint(lo, hi)

                # Inject ~4% legitimate category refunds (positive credit on expense merchant)
                if not is_credit and rng.random() < 0.04:
                    signed_cents = cents_mag
                else:
                    signed_cents = cents_mag if is_credit else -cents_mag

                ref_suffix = f"{stmt_idx:02d}{r_idx + 1:03d}"
                # Inject subtle reference suffix variation on half of rows without breaking normalization
                display_desc = f"{desc} #{ref_suffix}" if (r_idx % 5 == 0 and "#" not in desc) else desc
                txn_id = f"TXN-{stmt_idx:02d}-{r_idx + 1:04d}"

                if style == 0:
                    deb = format_cents(abs(signed_cents)) if signed_cents < 0 else ""
                    cred = format_cents(signed_cents) if signed_cents >= 0 else ""
                    writer.writerow([posted.strftime("%Y-%m-%d"), display_desc, deb, cred, txn_id])
                elif style == 1:
                    writer.writerow([posted.strftime("%Y-%m-%d"), display_desc, format_cents(signed_cents), "USD"])
                elif style == 2:
                    deb = format_cents(abs(signed_cents)) if signed_cents < 0 else ""
                    cred = format_cents(signed_cents) if signed_cents >= 0 else ""
                    writer.writerow([posted.strftime("%m/%d/%Y"), display_desc, deb, cred, txn_id])
                else:
                    writer.writerow(
                        [posted.strftime("%Y-%m-%d"), display_desc, format_cents(signed_cents), "USD", txn_id]
                    )

                gt_rows.append(
                    [
                        stmt_path.name,
                        str(r_idx + 2),
                        posted.isoformat(),
                        display_desc,
                        format_cents(signed_cents),
                        "USD",
                        cat,
                        family,
                    ]
                )

        manifest_lines.append(f"{sha256_file(stmt_path)}  statements/{stmt_path.name}")

    gt_path = FIXTURES_DIR / "ground_truth.csv"
    with gt_path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp, lineterminator="\n")
        w.writerow(
            [
                "statement_file",
                "source_line_no",
                "posted_date",
                "description",
                "signed_amount",
                "currency",
                "true_category",
                "merchant_family",
            ]
        )
        w.writerows(gt_rows)

    gt_sha = sha256_file(gt_path)
    (FIXTURES_DIR / "ground_truth.sha256").write_text(f"{gt_sha}  ground_truth.csv\n", encoding="utf-8")
    manifest_lines.append(f"{gt_sha}  ground_truth.csv")

    # Separate negative and edge-case fixtures mandated by V2 Section C/H
    (EDGE_DIR / "smoke_5rows.csv").write_text(
        "Date,Description,Amount,Currency\n"
        "2026-02-01,DEMO CLOUD HOSTING,-25.00,USD\n"
        "2026-02-02,ACME OFFICE SUPPLIES,-42.85,USD\n"
        "2026-02-03,NORTHWOOD MART #402,-31.40,USD\n"
        "2026-02-04,CLIENT RETAINER PAYOUT,1500.00,USD\n"
        "2026-02-05,VALLEY OUTPOST #19,-64.00,USD\n",
        encoding="utf-8",
    )

    (EDGE_DIR / "utf8_bom_crlf.csv").write_bytes(
        (
            "\ufeffPosted Date,Merchant,Debit,Credit,Transaction ID\r\n"
            '2026-02-06,"CAFÉ ÉCLAIR, LLC",18.50,,bom-1\r\n'
            '2026-02-07,"ONLINE SYSTEMS\nACADEMY PRO",99.00,,bom-2\r\n'
        ).encode("utf-8")
    )

    (EDGE_DIR / "multiline_quotes.csv").write_text(
        'Date,Description,Amount,Currency\n'
        '2026-02-08,"ACME OFFICE SUPPLIES\n2-PLY PAPER, BOX OF 10",-54.10,USD\n'
        '2026-02-09,"DEMO CLOUD HOSTING, REGION US-WEST",-19.99,USD\n',
        encoding="utf-8",
    )

    (EDGE_DIR / "ambiguous_dates.csv").write_text(
        "Date,Description,Amount,Currency\n"
        "02/03/2026,DEMO CLOUD HOSTING,-25.00,USD\n"
        "04/05/2026,ACME OFFICE SUPPLIES,-14.00,USD\n",
        encoding="utf-8",
    )

    (EDGE_DIR / "invalid_rows.csv").write_text(
        "Posted Date,Merchant,Debit,Credit,Currency\n"
        "2026-02-10,DEMO CLOUD HOSTING,25.00,10.00,USD\n"
        "bad-date,ACME OFFICE SUPPLIES,15.00,,USD\n"
        "2026-02-11,,12.00,,USD\n"
        "2026-02-12,PARIS HOTEL GROUP,140.00,,EUR\n"
        "2026-02-13,HARBOR ROASTERS CAFE,,,USD\n"
        "2026-02-14,METRO RAIL PASS,12.50,,USD\n",
        encoding="utf-8",
    )

    (EDGE_DIR / "formula_injection.csv").write_text(
        "Date,Description,Amount,Currency\n"
        '2026-02-15,"=HYPERLINK(""http://bad.example"",""ACME"")",-15.00,USD\n'
        "2026-02-16,+CMD|'/C calc'!A0,-22.00,USD\n"
        "2026-02-17,@SUM(1+1),-8.00,USD\n",
        encoding="utf-8",
    )

    (EDGE_DIR / "duplicate_legit_charges.csv").write_text(
        "Date,Description,Amount,Currency\n"
        "2026-02-18,HARBOR ROASTERS CAFE,-6.75,USD\n"
        "2026-02-18,HARBOR ROASTERS CAFE,-6.75,USD\n",
        encoding="utf-8",
    )

    (EDGE_DIR / "refund_net_negative.csv").write_text(
        "Date,Description,Amount,Currency\n"
        "2026-02-02,ERGONOMIC DESK CO,-100.00,USD\n"
        "2026-02-19,ERGONOMIC DESK CO REFUND,150.00,USD\n",
        encoding="utf-8",
    )

    (EDGE_DIR / "fake_exe.csv").write_bytes(b"MZ\x90\x00\x03\x00\x00\x00This program cannot be run in DOS mode")

    for edge_file in sorted(EDGE_DIR.iterdir()):
        manifest_lines.append(f"{sha256_file(edge_file)}  import_edge_cases/{edge_file.name}")

    (FIXTURES_DIR / "manifest.sha256").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "event": "generate_statements.complete",
                "seed": seed,
                "statements": count,
                "rowsPerStatement": rows_per_statement,
                "totalGroundTruthRows": len(gt_rows),
                "groundTruthSha256": gt_sha,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--rows", type=int, default=90)
    args = parser.parse_args()
    generate_statements(args.seed, args.count, args.rows)

