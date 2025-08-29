# parse_micronet_ajax.py
from __future__ import annotations

from bs4 import BeautifulSoup

from .fetch import fetch_html
from .normalize import normalize_event


def parse_micronet_ajax(source, add_event):
    """
    Very light parser for Micronet/ChamberMaster calendars that render via AJAX.
    We primarily needed to ensure we wait for the list container to render.
    """
    url = source["url"]
    html = fetch_html(url, source=source)  # <-- wait hints respected
    soup = BeautifulSoup(html, "lxml")

    # A few common containers/selectors seen in Micronet skins:
    # - .cm-event-list .cm-event
    # - .eventList .event
    # - .cm-events-list .event
    items = soup.select(".cm-event-list .cm-event, .eventList .event, .cm-events-list .event")
    for el in items:
        title = (el.get_text(" ", strip=True) or "").strip()
        if not title:
            continue
        # Defer to your existing normalizer (dates are typically embedded or linked)
        evt = normalize_event(
            title=title,
            url=url,
            where=None,
            start=None,
            end=None,
            tzname=source.get("tzname"),
        )
        if evt:
            add_event(evt)
