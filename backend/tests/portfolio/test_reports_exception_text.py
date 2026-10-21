"""PDF conversion failures in portfolio/reports.py must not expose exception text (offline)."""
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.portfolio import reports

SECRET = "secret-token-XYZ"


def _boom(*args, **kwargs):
    raise RuntimeError(SECRET)


@pytest.fixture
def failing_pdfkit(monkeypatch):
    fake = types.ModuleType("pdfkit")
    fake.from_file = _boom
    monkeypatch.setitem(sys.modules, "pdfkit", fake)


@pytest.fixture
def report_files(monkeypatch, tmp_path):
    html = tmp_path / "portfolio_report.html"
    html.write_text("<html><body>report</body></html>", encoding="utf-8")
    monkeypatch.setattr(reports, "PORTFOLIO_REPORT_HTML", html)
    monkeypatch.setattr(reports, "PORTFOLIO_REPORT_PDF", tmp_path / "portfolio_report.pdf")
    return html


def test_convert_html_to_pdf_hides_exception_text(failing_pdfkit, tmp_path):
    out = reports.convert_html_to_pdf(str(tmp_path / "in.html"), str(tmp_path / "out.pdf"))
    assert out == {"success": False, "error": "PDF conversion error"}
    assert SECRET not in str(out)


def test_pdf_download_route_hides_exception_text(failing_pdfkit, report_files):
    app = FastAPI()
    app.include_router(reports.router)
    with TestClient(app) as client:
        r = client.get("/api/reports/download/portfolio/pdf")
    assert r.status_code == 500
    assert r.json() == {"detail": "PDF Conversion Failed: PDF conversion error"}
    assert SECRET not in r.text
