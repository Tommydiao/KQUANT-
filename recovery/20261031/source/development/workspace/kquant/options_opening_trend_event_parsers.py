"""Explicit schedule adapters; unknown times or incomplete lists stay visible."""
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from zoneinfo import ZoneInfo

JSON_PARSER = "STRUCTURED-JSON-SCHEDULE-V1"
BEA_PARSER = "BEA-RELEASE-SCHEDULE-HTML-V1"
FOMC_PARSER = "FOMC-MEETINGS-HTML-V1"
PARSERS = {JSON_PARSER, BEA_PARSER, FOMC_PARSER}
MONTHS = {datetime(2000, m, 1).strftime("%B"): m for m in range(1, 13)}


class Node:
    def __init__(self, tag, attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def walk(self, tag=None):
        if tag is None or tag == self.tag:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk(tag)

    def text(self):
        if self.tag in {"script", "style"}:
            return ""
        return " ".join((c.text() if isinstance(c, Node) else c) for c in self.children).strip()

    def classes(self):
        return set((self.attrs.get("class") or "").split())


class Document(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack, self.count = [self.root], 0
        self.feed(raw.decode("utf-8"))

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 30000:
            raise ValueError("HTML_NODE_LIMIT")
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            if len(self.stack) >= 128:
                raise ValueError("HTML_DEPTH_LIMIT")
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _aware(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("EVENT_EXPLICIT_TIME_MISSING")
    return result.astimezone(UTC)


def _event(identity, name, start, end, *, precision="INSTANT", content=""):
    if not identity or not name.strip() or end < start:
        raise ValueError("EVENT_ID_OR_INTERVAL_INVALID")
    return {"id": identity, "name": name, "start_at": start.astimezone(UTC).isoformat(),
            "end_at": end.astimezone(UTC).isoformat(), "time_precision": precision,
            "raw_component_sha256": sha256(content.encode()).hexdigest()}


def _json(raw, binding):
    row = json.loads(raw)
    if (not isinstance(row, dict) or not isinstance(row.get("events"), list)
            or type(row.get("count")) is not int or row["count"] != len(row["events"])
            or "next_page" not in row or row["next_page"] is not None):
        raise ValueError("JSON_PAGINATION_OR_COUNT_INCOMPLETE")
    if len(row["events"]) > 2000:
        raise ValueError("CALENDAR_EVENT_LIMIT")
    if (_aware(row["coverage_start"]) > _aware(binding["coverage_start"])
            or _aware(row["coverage_end"]) < _aware(binding["coverage_end"])):
        raise ValueError("JSON_COVERAGE_INCOMPLETE")
    events, issues = [], []
    for item in row["events"]:
        try:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
                raise ValueError("JSON_EVENT_ID_INVALID")
            events.append(_event(item["id"], item["name"], _aware(item["start_at"]),
                                 _aware(item.get("end_at", item["start_at"])), content=json.dumps(item, sort_keys=True)))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            issues.append(str(exc) if isinstance(exc, ValueError) else "JSON_EVENT_SCHEMA_INVALID")
    return events, issues


def _zone(binding):
    if binding.get("time_zone") != "America/New_York":
        raise ValueError("SOURCE_TIME_ZONE_UNVERIFIED")
    return ZoneInfo(binding["time_zone"])


def _bea(raw, binding):
    root, zone = Document(raw).root, _zone(binding)
    events, issues, years = [], [], set()
    for table in root.walk("table"):
        headers = " ".join(n.text() for n in table.walk("th"))
        match = re.search(r"Year\s+(20\d{2})", headers)
        if not match:
            continue
        year = int(match[1])
        years.add(year)
        for tr in table.walk("tr"):
            cells = list(tr.walk("td"))
            if not cells:
                continue
            stamp = re.sub(r"\s+", " ", cells[0].text())
            at = re.fullmatch(r"([A-Za-z]+) (\d{1,2}) (\d{1,2}):(\d{2}) (AM|PM)", stamp)
            if not at or len(cells) < 3 or at[1] not in MONTHS:
                issues.append("BEA_RELEASE_TIME_OR_ROW_UNKNOWN")
                continue
            try:
                hour = int(at[3])
                if not 1 <= hour <= 12:
                    raise ValueError("BEA_TIME_INVALID")
                start = datetime(year, MONTHS[at[1]], int(at[2]), hour % 12 + (12 if at[5] == "PM" else 0),
                                 int(at[4]), tzinfo=zone)
                name = cells[2].text()
                events.append(_event(sha256((stamp + name).encode()).hexdigest(), name, start, start, content=tr.text()))
            except ValueError:
                issues.append("BEA_RELEASE_TIME_INVALID")
    required = {_aware(binding[k]).astimezone(zone).year for k in ("coverage_start", "coverage_end")}
    if not required <= years or not events:
        issues.append("BEA_ANNUAL_SCHEDULE_MISSING")
    if "To Be Announced" in root.text():
        issues.append("BEA_UNSCHEDULED_RELEASE_REQUIRES_REVIEW")
    return events, issues


def _fomc(raw, binding):
    root, zone = Document(raw).root, _zone(binding)
    year = _aware(binding["coverage_start"]).astimezone(zone).year
    if _aware(binding["coverage_end"]).astimezone(zone).year != year:
        raise ValueError("FOMC_CROSS_YEAR_COVERAGE_UNSUPPORTED")
    panels = [n for n in root.walk() if "panel" in n.classes()
              and any(h.text().strip() == f"{year} FOMC Meetings" for h in n.walk("h4"))]
    if len(panels) != 1:
        raise ValueError("FOMC_YEAR_PANEL_MISSING")
    events, issues = [], []
    meetings = [n for n in panels[0].walk() if "fomc-meeting" in n.classes()]
    for meeting in meetings:
        month_nodes = [n for n in meeting.walk() if "fomc-meeting__month" in n.classes()]
        date_nodes = [n for n in meeting.walk() if "fomc-meeting__date" in n.classes()]
        if len(month_nodes) != 1 or len(date_nodes) != 1:
            issues.append("FOMC_MEETING_SCHEMA_UNKNOWN")
            continue
        month, days = month_nodes[0].text(), date_nodes[0].text().replace("*", "").strip()
        match = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2}))?", days)
        if month not in MONTHS or not match:
            issues.append("FOMC_MEETING_DATE_UNKNOWN")
            continue
        try:
            start = datetime(year, MONTHS[month], int(match[1]), tzinfo=zone)
            end = datetime(year, MONTHS[month], int(match[2] or match[1]), tzinfo=zone) + timedelta(days=1)
            events.append(_event(f"fomc-{year}-{month}-{days}", "FOMC meeting", start, end,
                                 precision="DAY_RANGE_TIME_UNSPECIFIED", content=meeting.text()))
        except ValueError:
            issues.append("FOMC_MEETING_DATE_INVALID")
        for released in re.finditer(r"Released ([A-Za-z]+) (\d{1,2}), (20\d{2})", re.sub(r"\s+", " ", meeting.text())):
            try:
                start = datetime(int(released[3]), MONTHS[released[1]], int(released[2]), tzinfo=zone)
                events.append(_event("minutes-" + start.date().isoformat(), "FOMC minutes", start,
                                     start + timedelta(days=1), precision="DAY_TIME_UNSPECIFIED", content=released[0]))
            except (ValueError, KeyError):
                issues.append("FOMC_MINUTES_DATE_UNKNOWN")
    if len(meetings) != 8:
        issues.append("FOMC_SCHEDULE_COUNT_UNVERIFIED")
    return events, issues


def parse(raw, binding):
    if not raw or len(raw) > 512 * 1024:
        raise ValueError("SOURCE_EMPTY_OR_TOO_LARGE")
    parser = binding.get("parser")
    function = {JSON_PARSER: _json, BEA_PARSER: _bea, FOMC_PARSER: _fomc}.get(parser)
    if function is None:
        raise ValueError("SOURCE_PARSER_UNSUPPORTED")
    events, issues = function(raw, binding)
    unique = {}
    for event in events:
        if event["id"] in unique and unique[event["id"]] != event:
            issues.append("EVENT_ID_CONFLICT")
        unique[event["id"]] = event
    return {"parser": parser, "events": list(unique.values()), "issues": sorted(set(issues))}
