"""SCORM packages ("content packages" in Blackboard): their launch page as a note, plus its images.

Blackboard serves a package's unzipped files at /courses/1/<courseId>/content/<contentId>/, readable
with the same session as the REST API, so nothing is launched (no attempt is recorded).
"""

import json
import xml.etree.ElementTree as ET
from html import escape
from pathlib import PurePosixPath
from urllib.parse import urljoin

from bs4 import BeautifulSoup

HANDLER = "resource/x-plugin-scormengine"

# Player chrome and quiz widgets: not course content.
_DROP = ["script", "style", "noscript", "nav", "header", "footer", "button", "input", "select", "textarea"]
_DROP_CLASSES = ["quiz-feedback", "menu-toggle", "sidebar", "topbar"]


def package_dir(course_key: str, content_id: str) -> str:
    return f"/courses/1/{course_key}/content/{content_id}/"


def launch_href(manifest: bytes) -> str | None:
    """The page the default organization's first item opens (SCORM 1.2 and 2004 alike)."""
    root = ET.fromstring(manifest)
    local = lambda el: el.tag.rsplit("}", 1)[-1]  # namespaces differ by SCORM version
    resources = {r.get("identifier"): r.get("href") for r in root.iter() if local(r) == "resource"}
    orgs = [o for o in root.iter() if local(o) == "organization"]
    default = next((o for o in root.iter() if local(o) == "organizations"), None)
    default_id = default.get("default") if default is not None else None
    orgs.sort(key=lambda o: o.get("identifier") != default_id)
    for org in orgs:
        for item in org.iter():
            if local(item) == "item" and resources.get(item.get("identifierref")):
                return resources[item.get("identifierref")]
    return next((h for h in resources.values() if h), None)


def to_page_body(html: str, page_url: str) -> str:
    """The package page reshaped like an Ultra page body, so ultra_pages.convert can take it:
    images become data-bbfile links with absolute URLs, quiz options become list items."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_DROP):
        tag.decompose()
    for cls in _DROP_CLASSES:
        for tag in soup.find_all(class_=cls):
            tag.decompose()
    for label in soup.find_all("label"):
        label.name = "li"
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if not src or src.startswith("data:"):
            img.decompose()
            continue
        name = PurePosixPath(src.split("?")[0]).name
        meta = escape(json.dumps({"fileName": name}), quote=True)
        img.replace_with(BeautifulSoup(f'<a href="{escape(urljoin(page_url, src))}" data-bbfile="{meta}"></a>',
                                       "html.parser"))
    screens = soup.find_all("section", class_="screen")
    if screens:
        return "".join(str(s) for s in screens)
    return str(soup.body or soup)
