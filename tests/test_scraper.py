from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from src.scraper import ICAIScraper, ScrapeError


def html_response(html, status=200):
    return Mock(status_code=status, text=html, headers={"Content-Type": "text/html; charset=utf-8"})


def mock_flow(fixture_html, tail=None):
    session = Mock()
    session.headers = {}
    session.request.side_effect = [html_response(fixture_html("initial.html")),
                                   html_response(fixture_html("region.html")),
                                   tail or html_response(fixture_html("batches.html"))]
    return session


def test_verified_webforms_flow(settings, fixture_html, target):
    session = mock_flow(fixture_html)
    result = ICAIScraper(settings, session).fetch(target)
    assert len(result.batches) == 6
    calls = session.request.call_args_list
    assert [c.args[0] for c in calls] == ["GET", "POST", "POST"]
    assert all(c.args[1] == "https://www.icaionlineregistration.org/launchbatchdetail.aspx" for c in calls)
    assert calls[1].kwargs["data"]["__EVENTTARGET"] == "ddl_reg"
    assert calls[1].kwargs["data"]["ddl_reg"] == "5"
    final = calls[2].kwargs["data"]
    assert final["ddlPou"] == "170"
    assert final["ddl_course"] == "45"
    assert final["btn_getlist"] == "Get List"
    assert final["__VIEWSTATE"] == "fixture-hidden-value"
    assert "Mozilla" in session.headers["User-Agent"]


def test_pou_values_discovered_not_hardcoded(settings, fixture_html, target):
    session = mock_flow(fixture_html)
    region = fixture_html("region.html").replace('value="170"', 'value="9999"')
    batches = fixture_html("batches.html").replace('value="170"', 'value="9999"')
    session.request.side_effect = [html_response(fixture_html("initial.html")), html_response(region), html_response(batches)]
    ICAIScraper(settings, session).fetch(target)
    assert session.request.call_args.kwargs["data"]["ddlPou"] == "9999"


def test_hidden_fields_refreshed_between_postbacks(settings, fixture_html, target):
    session = mock_flow(fixture_html)
    region = fixture_html("region.html").replace("fixture-hidden-value", "refreshed-value")
    session.request.side_effect = [html_response(fixture_html("initial.html")), html_response(region),
                                   html_response(fixture_html("batches.html"))]
    ICAIScraper(settings, session).fetch(target)
    assert session.request.call_args.kwargs["data"]["__EVENTVALIDATION"] == "refreshed-value"


@pytest.mark.parametrize("status", [301, 403, 500])
def test_http_errors_are_not_empty_results(settings, target, status):
    session = Mock(headers={})
    session.request.return_value = html_response("", status)
    with pytest.raises(RuntimeError):
        ICAIScraper(settings, session).fetch(target)


def test_selection_not_retained_is_an_error(settings, fixture_html, target):
    session = mock_flow(fixture_html, html_response(fixture_html("initial.html")))
    with pytest.raises(ScrapeError, match="did not retain"):
        ICAIScraper(settings, session).fetch(target)


def test_pagination_follows_discovered_links(settings, fixture_html, target):
    page1 = BeautifulSoup(fixture_html("batches.html"), "html.parser")
    table = page1.find(id="GridView1")
    pager = BeautifulSoup('''<tr class="gridpager"><td colspan="8"><a href="javascript:__doPostBack('GridView1','Page$2')">2</a></td></tr>''', "html.parser")
    table.append(pager.tr)
    page2 = fixture_html("batches.html").replace("AdvICITSSMCS__JAIPUR_", "SecondPage_")
    session = mock_flow(fixture_html)
    session.request.side_effect = [html_response(fixture_html("initial.html")), html_response(fixture_html("region.html")),
                                   html_response(str(page1)), html_response(page2)]
    result = ICAIScraper(settings, session).fetch(target)
    assert len(result.batches) == 12
    assert session.request.call_args.kwargs["data"]["__EVENTARGUMENT"] == "Page$2"
