"""Read permitted source bodies, never paywalls, executable content or new hosts."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from financial_ai.data.documents import UnsafeDocument, document_text
from financial_ai.data.http import HttpRequest, HttpResponseTooLargeError, SharedHttpClient
from financial_ai.data.safe_transport import SafeTransport, UnsafeDestination
from financial_ai.security import safe_link


@dataclass
class ReadArticle:
    url: str
    title: str
    published_at: str | None
    retrieved_at: str
    status: str = "unread"
    classification: str = "unclassified article"
    classification_basis: str = "Publisher did not declare an article type"
    paragraphs: list[str] = field(default_factory=list)
    reason: str = ""
    raw_html: str = ""


def _nodes(value):
    if isinstance(value, list):
        for item in value[:100]:
            yield from _nodes(item)
    elif isinstance(value, dict):
        yield value
        if isinstance(value.get("@graph"), list):
            yield from _nodes(value["@graph"])


def extract_article(
    raw: str, result: ReadArticle, *, ticker: str, company_name: str = "", issuer_filing=False
):
    soup = BeautifulSoup(raw, "html.parser")
    types = set()
    for script in soup.select('script[type="application/ld+json"]')[:12]:
        try:
            for node in _nodes(json.loads(script.get_text())):
                declared = node.get("@type", [])
                declared = [declared] if isinstance(declared, str) else declared
                article_types = [str(t).rsplit("/", 1)[-1] for t in declared if "Article" in str(t)]
                if not article_types:
                    continue
                if node.get("isAccessibleForFree") in (False, "false", "False"):
                    result.status, result.reason = (
                        "paywalled",
                        "Publisher marks this article as subscription-only.",
                    )
                    return result
                types.update(article_types)
        except (ValueError, TypeError):
            continue
    if issuer_filing:
        result.classification = "issuer filing"
        result.classification_basis = "Original SEC filing resolved to the requested issuer"
    else:
        labels = [
            ("OpinionNewsArticle", "publisher-labelled opinion"),
            ("AnalysisNewsArticle", "publisher-labelled analysis"),
            ("ReportageNewsArticle", "publisher-labelled reporting"),
            ("AdvertiserContentArticle", "publisher-labelled sponsored content"),
            ("NewsArticle", "publisher-labelled news"),
        ]
        for declared, label in labels:
            if declared in types:
                result.classification, result.classification_basis = (
                    label,
                    f"Publisher JSON-LD @type: {declared}",
                )
                break
        section = soup.select_one('meta[property="article:section"]')
        if section and str(section.get("content", "")).casefold() in {
            "opinion",
            "editorial",
            "analysis",
        }:
            result.classification = "publisher-labelled " + str(section["content"]).casefold()
            result.classification_basis = "Publisher article:section metadata"
    container = None
    for selector in (
        '[itemprop="articleBody"]',
        ".caas-body",
        ".article-body",
        ".article-content",
        "article",
        "main",
    ):
        matches = soup.select(selector)
        if matches:
            container = max(matches, key=lambda tag: len(tag.get_text()))
            break
    if container is None and issuer_filing:
        container = soup.body or soup
    if container is None:
        result.status, result.reason = (
            "no_body",
            "No readable article body; the page may require JavaScript or consent.",
        )
        return result
    heading = container.find("h1") or soup.find("h1")
    actual_title = heading.get_text(" ", strip=True) if heading else ""
    if actual_title:
        result.title = actual_title[:500]
    # Check the selected source container, including hidden instructions, before
    # stripping scripts/navigation. Scripts elsewhere on the page are not context.
    try:
        markup = str(container)
        # Periodic SEC filings can exceed the general document-text cap because
        # of inline XBRL markup. Scan overlapping bounded views before extraction.
        for offset in range(0, len(markup), 1_000_000):
            document_text(markup[max(0, offset - 200) : offset + 1_000_000])
    except UnsafeDocument:
        result.status, result.reason = (
            "quarantined",
            "Embedded instruction patterns were excluded from model context.",
        )
        return result
    for node in container.select(
        'script, style, nav, aside, footer, header, form, [hidden], [aria-hidden="true"]'
    ):
        node.decompose()
    candidates = container.find_all(["p", "tr", "div"] if issuer_filing else ["p"])
    paragraphs = []
    for node in candidates:
        if node.find_parent("p") or (issuer_filing and node.name == "p" and node.find_parent("tr")):
            continue
        if (
            issuer_filing
            and node.name == "div"
            and (node.find(["div", "p", "table"]) or node.find_parent("tr"))
        ):
            continue
        if issuer_filing and node.name == "tr" and node.find("tr"):
            continue
        value = document_text(node.get_text(" ", strip=True))
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) >= (20 if issuer_filing else 60) and value not in paragraphs:
            paragraphs.append(value)
        if sum(len(p) for p in paragraphs) >= (500000 if issuer_filing else 40000):
            break
    body = " ".join(paragraphs)
    if re.search(
        r"subscribe to (?:continue|read)|subscription required|sign in to continue",
        body[:1000],
        re.I,
    ):
        result.status, result.reason = (
            "paywalled",
            "Readable content is gated by a subscription or sign-in notice.",
        )
        return result
    if len(body) < 500 or len(paragraphs) < 2:
        result.status, result.reason = (
            "no_body",
            "Only a teaser or insufficient article text was available.",
        )
        return result
    if not issuer_filing:
        aliases = [ticker]
        words = company_name.split()
        if words and len(words[0]) >= 3 and words[0].lower() not in {"the", "inc", "corp"}:
            aliases.append(words[0])
        pattern = r"(?<![A-Z0-9])(?:" + "|".join(re.escape(a) for a in aliases) + r")(?![A-Z0-9])"
        if not re.search(pattern, actual_title + " " + body[:2500], re.I):
            result.status, result.reason = (
                "unrelated",
                "The extracted body did not establish relevance to the selected company.",
            )
            return result
    result.status, result.paragraphs, result.raw_html = "read", paragraphs, raw
    return result


class ArticleReader:
    agent = "FinancialAIResearch"

    def __init__(self, settings, *, http=None, clock=time.monotonic):
        self.settings, self.clock = settings, clock
        self.hosts = frozenset(settings.article_allowed_hosts)
        self.http = http or SharedHttpClient(
            SafeTransport(self.hosts, return_redirects=True),
            timeout_seconds=6,
            max_retries=0,
            max_response_bytes=2_000_000,
            user_agent=self.agent + "/0.1",
        )
        self.sec_http = http or SharedHttpClient(
            SafeTransport(["www.sec.gov"], return_redirects=True),
            timeout_seconds=6,
            max_retries=0,
            max_response_bytes=8_000_000,
            user_agent=self.agent + "/0.1",
        )
        self.robots: dict[str, tuple[bool, str, RobotFileParser | None]] = {}
        self.lock = Lock()
        self.deadline = clock() + 24

    def _allowed_url(self, url):
        parsed = urlsplit(url)
        return bool(
            safe_link(url)
            and parsed.scheme == "https"
            and parsed.port in (None, 443)
            and parsed.hostname in self.hosts
            and not parsed.fragment
        )

    def _request(self, url):
        if self.clock() >= self.deadline:
            raise TimeoutError("Source collection deadline reached")
        headers = {}
        if urlsplit(url).hostname == "www.sec.gov" and self.settings.sec_user_agent:
            headers["User-Agent"] = self.settings.sec_user_agent
        client = self.sec_http if urlsplit(url).hostname == "www.sec.gov" else self.http
        return client.fetch(HttpRequest("article", url, headers=headers))

    def _robots(self, url):
        host = urlsplit(url).netloc
        with self.lock:
            if host not in self.robots:
                response = self._request("https://" + host + "/robots.txt")
                parser = RobotFileParser()
                if response.status_code == 404:
                    self.robots[host] = (True, "", None)
                elif response.status_code == 200:
                    if response.body.lstrip().startswith(b"<"):
                        return False, "Publisher access rules returned an unreadable page."
                    parser.parse(response.body.decode("utf-8", errors="replace").splitlines())
                    self.robots[host] = (True, "", parser)
                else:
                    self.robots[host] = (
                        False,
                        "Publisher access rules could not be checked.",
                        None,
                    )
            available, reason, rules = self.robots[host]
        if not available:
            return False, reason
        if rules and not rules.can_fetch(self.agent, url):
            return False, "Publisher robots policy disallows this source."
        if rules and rules.crawl_delay(self.agent):
            return (
                False,
                "Publisher crawl delay requires scheduled collection; this request is deferred.",
            )
        return True, ""

    def read(self, item, *, ticker, company_name="", issuer_filing=False):
        url = item["url"]
        result = ReadArticle(
            url,
            str(item.get("title") or "Original source"),
            item.get("publishedDate"),
            datetime.now(UTC).isoformat(),
        )
        try:
            for _ in range(3):
                if not self._allowed_url(url):
                    result.status, result.reason = (
                        "host_not_allowed",
                        "Source or redirect is outside the approved HTTPS article hosts.",
                    )
                    return result
                allowed, reason = self._robots(url)
                if not allowed:
                    result.status, result.reason = "publisher_restricted", reason
                    return result
                response = self._request(url)
                if response.status_code in (301, 302, 303, 307, 308):
                    location = next(
                        (v for k, v in response.headers.items() if k.lower() == "location"), ""
                    )
                    if not location:
                        break
                    url = urljoin(url, location)
                    if issuer_filing and (
                        urlsplit(url).hostname != "www.sec.gov"
                        or urlsplit(url).path != urlsplit(item["url"]).path
                    ):
                        result.status, result.reason = (
                            "blocked",
                            "Filing redirect changed the verified filing destination.",
                        )
                        return result
                    continue
                if response.status_code != 200:
                    result.status, result.reason = (
                        "access_failed",
                        f"Article returned HTTP {response.status_code}; its body was not used.",
                    )
                    return result
                result.url = url
                return extract_article(
                    response.body.decode("utf-8", errors="replace"),
                    result,
                    ticker=ticker,
                    company_name=company_name,
                    issuer_filing=issuer_filing,
                )
            result.status, result.reason = (
                "redirect_limit",
                "Article exceeded the bounded redirect policy.",
            )
        except UnsafeDestination:
            result.status, result.reason = (
                "blocked",
                "Source download failed destination or content-type validation.",
            )
        except HttpResponseTooLargeError:
            result.status, result.reason = "too_large", "Article exceeded the download size limit."
        except UnsafeDocument:
            result.status, result.reason = "quarantined", "Unsafe source text was excluded."
        except Exception:
            result.status, result.reason = (
                "unavailable",
                "Source download failed or exceeded its time budget.",
            )
        return result
