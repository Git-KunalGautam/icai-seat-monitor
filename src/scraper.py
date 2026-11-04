from datetime import datetime
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .config import Settings
from .http import make_session, request
from .models import ScrapeResult, Target, normalized
from .parser import ParseError, parse_batches, text


class ScrapeError(RuntimeError):
    pass


# Verified against the live page on 2026-11-04; option values are always resolved live.
REGION = "ddl_reg"
POU = "ddlPou"
COURSE = "ddl_course"
BUTTON = "btn_getlist"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def form_fields(soup: BeautifulSoup) -> tuple[str, dict[str, str]]:
    form = soup.find("form", id="form1")
    if form is None:
        raise ScrapeError("Missing WebForms form1; possible outage or access restriction")
    fields = {i["name"]: i.get("value", "") for i in form.select('input[type="hidden"][name]')}
    if not fields.get("__VIEWSTATE") or not fields.get("__EVENTVALIDATION"):
        raise ScrapeError("Missing ASP.NET hidden fields")
    for select in form.find_all("select"):
        option = select.find("option", selected=True) or select.find("option")
        if select.get("name") and option:
            fields[select["name"]] = option.get("value", text(option))
    return form.get("action", ""), fields


def option_value(soup: BeautifulSoup, control: str, label: str) -> str:
    select = soup.find("select", id=control)
    if select is None or select.get("name") != control:
        raise ScrapeError(f"Missing verified dropdown {control}")
    matches = [o for o in select.find_all("option") if normalized(text(o)) == normalized(label)]
    if len(matches) != 1 or not matches[0].get("value"):
        raise ScrapeError(f"Dropdown {control}: configured label absent or ambiguous: {label}")
    return matches[0]["value"]


def validate_selected(soup: BeautifulSoup, choices: dict[str, str]) -> None:
    for control, expected in choices.items():
        node = soup.find("select", id=control)
        selected = node.find("option", selected=True) if node else None
        if selected is None or selected.get("value") != expected:
            raise ScrapeError(f"Server did not retain selected filter {control}")


class ICAIScraper:
    def __init__(self, settings: Settings, session=None):
        self.settings = settings
        self.session = session or make_session(settings.trust_env)
        self.session.headers.update({"User-Agent": USER_AGENT})
        # The non-www POST returns 301 and loses the WebForms payload. Verified live.
        parts = urlsplit(settings.url)
        self.url = urlunsplit((parts.scheme, "www.icaionlineregistration.org", parts.path, "", ""))

    def close(self) -> None:
        self.session.close()

    def _load(self, method: str, soup=None, overrides=None) -> BeautifulSoup:
        url = self.url
        kwargs = {}
        if soup is not None:
            action, fields = form_fields(soup)
            url = urljoin(self.url, action)
            if urlsplit(url).netloc != urlsplit(self.url).netloc or urlsplit(url).scheme != "https":
                raise ScrapeError("Unexpected cross-origin form action")
            fields.update(overrides or {})
            kwargs["data"] = fields
        response = request(self.session, method, url, timeout=self.settings.timeout,
                           max_retries=self.settings.max_retries, service="ICAI", **kwargs)
        if response.status_code != 200:
            raise ScrapeError(f"ICAI returned HTTP {response.status_code}; redirects and restrictions are not followed")
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            raise ScrapeError("ICAI returned a non-HTML response")
        page = BeautifulSoup(response.text, "html.parser")
        form_fields(page)
        return page

    def fetch(self, target: Target) -> ScrapeResult:
        soup = self._load("GET")
        region = option_value(soup, REGION, target.region)
        onchange = soup.find(id=REGION).get("onchange", "")
        if "__doPostBack" not in onchange or REGION not in onchange:
            raise ScrapeError("Region postback missing; check user-agent or changed website")
        soup = self._load("POST", soup, {REGION: region, "__EVENTTARGET": REGION, "__EVENTARGUMENT": ""})
        validate_selected(soup, {REGION: region})
        choices = {REGION: region, POU: option_value(soup, POU, target.pou),
                   COURSE: option_value(soup, COURSE, target.course)}
        button = soup.find("input", id=BUTTON)
        if button is None or button.get("name") != BUTTON or normalized(button.get("value", "")) != "get list":
            raise ScrapeError("Missing verified Get List submit control")
        soup = self._load("POST", soup, {**choices, BUTTON: button["value"], "__EVENTTARGET": "", "__EVENTARGUMENT": ""})
        checked = datetime.now(ZoneInfo(self.settings.timezone)).isoformat(timespec="seconds")
        batches = []
        keys = set()
        current_page = 1
        for _ in range(100):
            validate_selected(soup, choices)
            result = parse_batches(str(soup), target, checked)
            if result.no_batches:
                if batches:
                    raise ParseError("Unexpected empty page during pagination")
                return result
            for batch in result.batches:
                if batch.key in keys:
                    raise ParseError("Repeated batch across pages; refusing partial results")
                keys.add(batch.key)
                batches.append(batch)
            # WebForms pager links are discovered in the actual response, never fabricated.
            next_links = []
            for link in soup.select('#GridView1 a[href]'):
                match = re.fullmatch(r"javascript:__doPostBack\('GridView1','Page\$(\d+)'\)", link["href"])
                if match and int(match[1]) > current_page:
                    next_links.append((int(match[1]), f"Page${match[1]}"))
                elif "Page$" in link["href"] and not match:
                    raise ScrapeError("Unsupported pagination link; validate new site behavior")
            if not next_links:
                return ScrapeResult(batches)
            next_page, argument = min(next_links)
            if next_page != current_page + 1:
                raise ScrapeError("Pagination would skip batch pages")
            soup = self._load("POST", soup, {**choices, "__EVENTTARGET": "GridView1", "__EVENTARGUMENT": argument})
            current_page = next_page
        raise ScrapeError("Batch pagination exceeded safety limit")
