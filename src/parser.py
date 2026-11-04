from datetime import datetime
import re

from bs4 import BeautifulSoup

from .models import Batch, ScrapeResult, Target, normalized


class ParseError(ValueError):
    pass


HEADERS = ["batch no", "available seats", "from date", "to date", "batch time", "pou name", "course", "open for"]
EMPTY_MESSAGES = {"no batches found", "no batches available", "no records found", "no records available"}


def text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def parse_batches(html: str, target: Target, checked_at: str) -> ScrapeResult:
    soup = BeautifulSoup(html, "html.parser")
    panel = soup.find(id="upd_grid")
    if panel is None:
        raise ParseError("Missing verified results panel upd_grid")
    table = panel.find("table", id="GridView1")
    # Only explicit, narrowly scoped empty messages count as a valid empty result.
    messages = [normalized(text(n)).rstrip(".!") for n in panel.find_all(["td", "span", "div"])]
    if table is None:
        if any(m in EMPTY_MESSAGES for m in messages + [normalized(text(panel)).rstrip(".!")]):
            return ScrapeResult([], no_batches=True)
        raise ParseError("Missing GridView1; an empty panel is not a zero-seat result")
    rows = [r for r in table.find_all("tr") if r.find_parent("table") is table]
    header_row = next((r for r in rows if r.find("th")), None)
    if header_row is None:
        if len(rows) == 1 and normalized(text(rows[0])).rstrip(".!") in EMPTY_MESSAGES:
            return ScrapeResult([], no_batches=True)
        raise ParseError("Missing batch table headers")
    headers = [normalized(text(c)) for c in header_row.find_all("th", recursive=False)]
    if len(headers) != len(set(headers)) or not set(HEADERS).issubset(headers):
        raise ParseError("Batch table headers changed")
    batches = []
    seen = set()
    for row in rows:
        if row is header_row:
            continue
        if "gridpager" in row.get("class", []):
            continue
        cells = row.find_all("td", recursive=False)
        if len(cells) != len(headers):
            raise ParseError("Malformed batch row")
        values = dict(zip(headers, [text(c) for c in cells]))
        if any(not values[h] for h in HEADERS):
            raise ParseError("Batch row has missing values")
        if not re.fullmatch(r"[0-9]+", values["available seats"]):
            raise ParseError("Invalid available seats; expected a nonnegative integer")
        if normalized(values["pou name"]) != normalized(target.pou) or normalized(values["course"]) != normalized(target.course):
            raise ParseError("Result POU/course does not match requested filters")
        try:
            start = datetime.strptime(values["from date"], "%d/%m/%Y")
            end = datetime.strptime(values["to date"], "%d/%m/%Y")
            if end < start:
                raise ValueError
        except ValueError:
            raise ParseError("Invalid batch date range") from None
        batch = Batch(target.region, values["pou name"], values["course"], values["batch no"],
                      int(values["available seats"]), values["from date"], values["to date"],
                      values["batch time"], values["open for"], checked_at)
        if batch.key in seen:
            raise ParseError("Duplicate batch identifier in results")
        seen.add(batch.key)
        batches.append(batch)
    if not batches:
        raise ParseError("Header-only table is not an explicit no-batches response")
    return ScrapeResult(batches)
