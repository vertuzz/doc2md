"""Download public legacy .doc samples into an ignored local folder."""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
DEFAULT_OUTPUT = Path("samples/financial")

SAMPLES = [
    (
        "siue_annual_report_project.doc",
        "https://www.siue.edu/~tking/doc/501project.doc",
    ),
    (
        "kansas_municipal_electric_annual_report.doc",
        "https://www.kcc.ks.gov/images/PDFs/annual-report/electric_12_municipal.doc",
    ),
    (
        "mcc_managing_the_money.doc",
        "https://mccchurch.org/files/2016/08/2_Managing-the-Money_US.doc",
    ),
    (
        "nc_public_staff_annual_report.doc",
        "https://publicstaff.nc.gov/media/186/open",
    ),
    (
        "foraker_finance_glossary.doc",
        "https://www.forakergroup.org/wp-content/uploads/filebase/Finance/Finance-Glossary-of-Terms.doc",
    ),
    (
        "scouting_council_annual_report_contents.doc",
        "https://filestore.scouting.org/filestore/mission/doc/Council_Annual_Report_contents.doc",
    ),
    (
        "veinternational_business_plan_key.doc",
        "https://veinternational.org/wp-content/uploads/sites/3/2012/11/BusinessPlan_KEY.doc",
    ),
    (
        "cerritos_cash_flows_notes.doc",
        "https://www.cerritos.edu/mfarina/_includes/docs/ACCT_102_Lecture_Notes_Chapter_13_Spr_2018.doc",
    ),
    (
        "microsoft_2000_annual_report.doc",
        "https://www.microsoft.com/investor/reports/ar00/downloads/msft_ar00.doc",
    ),
    (
        "faegre_10k_disclosure_controls_checklist.doc",
        "https://www.faegredrinker.com/webfiles/22%2010-K%20disclosure%20controls%20checklist.doc",
    ),
    (
        "goodwin_10q_form_check.doc",
        "https://www.publiccompanyadvisoryblog.com/wp-content/uploads/sites/13/2023/04/Goodwin-PCAP-Form-10-Q-Form-Check-Q1-2023-002.doc",
    ),
    (
        "dc_regs_rule_225.doc",
        "https://dcregs.dc.gov/Common/DCMR/RuleList.aspx?DownloadFile=1094545F-0000-C875-9704-83C33266EB91",
    ),
    (
        "aast_accounting_chapter_1.doc",
        "https://aast.edu/pheed/staffadminview/pdf_retreive.php?stafftype=staffcourses&url=157_28235_EA419_2012_4__2_1_Ch_01.doc",
    ),
    (
        "nispa_accounting_standards.doc",
        "https://www.nispa.org/files/conferences/2004/papers/200403300825020.NISPA%202%20dala_eng%20%28R%26V%29.doc?fs_papersPage=5",
    ),
    (
        "wipo_financial_report_2014.doc",
        "https://www.wipo.int/edocs/mdocs/govbody/en/a_55/a_55_7.doc",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    ok = 0
    skipped = 0
    failed = 0

    for filename, url in SAMPLES:
        target = args.output / filename
        if target.exists() and not args.force:
            print(f"skip {filename}: already exists")
            skipped += 1
            continue
        request = Request(url, headers={"User-Agent": "doc2markdown-sample-downloader/0.1"})
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read()
        except URLError as exc:
            print(f"fail {filename}: {exc}")
            failed += 1
            continue
        if not data.startswith(OLE_SIGNATURE):
            print(f"fail {filename}: response is not an OLE .doc file")
            failed += 1
            continue
        target.write_bytes(data)
        print(f"ok {filename}: {len(data)} bytes")
        ok += 1

    print(f"downloaded={ok} skipped={skipped} failed={failed} output={args.output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
