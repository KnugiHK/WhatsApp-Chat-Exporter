from html.parser import HTMLParser
from typing import Iterable
import urllib.parse
from markupsafe import Markup, escape

_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

class _AllowlistParser(HTMLParser):
    def __init__(
        self, 
        allowed_tags: Iterable[str], 
        allowed_attributes: dict[str, set[str]] | None = None,
        url_schemes: Iterable[str] | None = None
    ) -> None:
        super().__init__(convert_charrefs=False)
        self.allowed_tags = {tag.lower() for tag in allowed_tags}
        
        self.allowed_attributes = {}
        if allowed_attributes:
            for tag, attrs in allowed_attributes.items():
                self.allowed_attributes[tag.lower()] = {attr.lower() for attr in attrs}
                
        self.url_schemes = {scheme.lower() for scheme in (url_schemes or set())}
        self.parts: list[str] = []
        
        # Track tags that were successfully opened so we know whether to allow their closing tags
        self.active_allowed_tags: list[str] = []

    def _filter_attributes(self, tag: str, attrs: list[tuple[str, str | None]]) -> str | None:
        """
        Returns a formatted string of safe attributes.
        If ANY attribute is not allowed (or fails URL scheme validation), 
        returns None to indicate the entire tag should be escaped.
        """
        allowed_attrs_for_tag = self.allowed_attributes.get(tag, set())
        allow_all_attrs = "*" in allowed_attrs_for_tag
        safe_attrs = []
        
        for attr_name, attr_value in attrs:
            attr_lower = attr_name.lower()
            
            # If the attribute isn't allowed, reject the whole tag
            if not allow_all_attrs and attr_lower not in allowed_attrs_for_tag:
                return None
                
            # Validate URL attributes
            if attr_lower in {"href", "src", "action"} and attr_value:
                clean_value = attr_value.strip()
                parsed = urllib.parse.urlparse(clean_value)
                scheme = parsed.scheme.lower()
                
                # If it has a scheme and it's not allowed, reject the whole tag
                if scheme and scheme not in self.url_schemes:
                    return None

            if attr_value is None:
                safe_attrs.append(attr_lower)
            else:
                safe_attrs.append(f'{attr_lower}="{escape(attr_value)}"')
                
        if safe_attrs:
            return " " + " ".join(safe_attrs)
        return ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self.allowed_tags:
            safe_attrs_str = self._filter_attributes(tag_lower, attrs)
            if safe_attrs_str is not None:
                self.parts.append(f"<{tag_lower}{safe_attrs_str}>")
                if tag_lower not in _VOID_TAGS:
                    self.active_allowed_tags.append(tag_lower)
            else:
                self.parts.append(str(escape(self.get_starttag_text())))
        else:
            self.parts.append(str(escape(self.get_starttag_text())))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self.allowed_tags:
            safe_attrs_str = self._filter_attributes(tag_lower, attrs)
            if safe_attrs_str is not None:
                # Omit trailing slash for consistency (e.g., <br/> becomes <br>)
                self.parts.append(f"<{tag_lower}{safe_attrs_str}>")
            else:
                self.parts.append(str(escape(self.get_starttag_text())))
        else:
            self.parts.append(str(escape(self.get_starttag_text())))

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        # Only allow the closing tag if its opening tag was successfully emitted
        if tag_lower in self.active_allowed_tags:
            self.parts.append(f"</{tag_lower}>")
            # Remove the most recently opened tag of this type (to handle nested identical tags properly)
            for i in reversed(range(len(self.active_allowed_tags))):
                if self.active_allowed_tags[i] == tag_lower:
                    self.active_allowed_tags.pop(i)
                    break
        else:
            self.parts.append(f"&lt;/{escape(tag)}&gt;")

    def handle_data(self, data: str) -> None:
        self.parts.append(str(escape(data)))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(str(escape(f"<!--{data}-->")))


def sanitize_except(
    html: str, 
    tags: Iterable[str] = ("br",), 
    attributes: dict[str, set[str]] | None = None,
    url_schemes: Iterable[str] | None = None
) -> Markup:
    parser = _AllowlistParser(
        allowed_tags=tags, 
        allowed_attributes=attributes, 
        url_schemes=url_schemes
    )
    parser.feed(html)
    parser.close()
    return Markup("".join(parser.parts))
