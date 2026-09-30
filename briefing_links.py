"""Whole source links in plain text, Markdown, and Slack messages."""
import html
import re


def source_urls(text):
    # A URL nested in a query or a longer path must not acknowledge another item.
    pattern = r"(?<![A-Za-z0-9:/?=&%._-])https?://[^\s<>\[\]()|\"'`]+"
    return {html.unescape(match.group().rstrip(".,;!"))
            for match in re.finditer(pattern, text)}
