from bs4 import BeautifulSoup
import pytest

from src.parser import ParseError, parse_batches


CHECKED = "2026-11-04T10:00:00+05:30"


def test_live_capture_all_zero(fixture_html, target):
    result = parse_batches(fixture_html("batches.html"), target, CHECKED)
    assert len(result.batches) == 6
    assert not result.no_batches
    assert all(b.available_seats == 0 for b in result.batches)
    assert result.batches[0].batch_number == "AdvICITSSMCS__JAIPUR_89"
    assert result.batches[-1].to_date == "24/12/2026"
    assert result.batches[0].last_checked_at == CHECKED


def test_headers_whitespace_order_and_unlimited_rows(fixture_html, target):
    soup = BeautifulSoup(fixture_html("batches.html"), "html.parser")
    table = soup.find(id="GridView1")
    # Swap first/last columns in every row to verify header-based mapping.
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        first, last = cells[0].extract(), cells[-1].extract()
        row.insert(0, last)
        row.append(first)
    table.find("th").string = " Open \n For "
    result = parse_batches(str(soup), target, CHECKED)
    assert len(result.batches) == 6
    assert result.batches[0].batch_number.endswith("89")


@pytest.mark.parametrize("value", ["", "unknown", "-1", "1.0", "3 seats", "1,000"])
def test_invalid_seats_fail_closed(fixture_html, target, value):
    soup = BeautifulSoup(fixture_html("batches.html"), "html.parser")
    soup.find(id="GridView1_lblPublishSize_0").string = value
    with pytest.raises(ParseError):
        parse_batches(str(soup), target, CHECKED)


@pytest.mark.parametrize("html", ["", "<html>Service unavailable</html>",
    '<div id="upd_grid"></div>', '<div id="upd_grid"><table id="GridView1"><tr><th>Seats</th></tr></table></div>'])
def test_empty_and_malformed_are_errors(target, html):
    with pytest.raises(ParseError):
        parse_batches(html, target, CHECKED)


@pytest.mark.parametrize("message", ["No batches found.", "No records found"])
def test_explicit_empty_response(target, message):
    result = parse_batches(f'<div id="upd_grid"><span>{message}</span></div>', target, CHECKED)
    assert result.no_batches and result.batches == []


def test_header_only_duplicate_and_wrong_location_fail(fixture_html, target):
    for mode in ("header", "duplicate", "location", "date"):
        soup = BeautifulSoup(fixture_html("batches.html"), "html.parser")
        if mode == "header":
            for row in soup.select(".gridRow, .gridAltRow"):
                row.decompose()
        elif mode == "duplicate":
            soup.find(id="GridView1_lblBatchHeaderId_1").string = "AdvICITSSMCS__JAIPUR_89"
        elif mode == "location":
            soup.find(id="GridView1_lblCityName_0").string = "OTHER CITY"
        else:
            soup.find(id="GridView1_lblFromDate_0").string = "bad date"
        with pytest.raises(ParseError):
            parse_batches(str(soup), target, CHECKED)
