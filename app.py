"""
Installation:
1) pip install streamlit beautifulsoup4 lxml streamlit-quill
2) streamlit run app.py

Optional alternative rich editor:
- pip install streamlit-tinymce
"""

from __future__ import annotations

import json
import re

import streamlit as st
from bs4 import BeautifulSoup
from bs4.element import Tag
from streamlit.components.v1 import html as html_component

try:
    from streamlit_quill import st_quill
except Exception:
    st_quill = None


ALLOWED_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "ul",
    "ol",
    "li",
    "br",
    "hr",
    "a",
    "img",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
}

UNWRAP_TAGS = {"span", "div", "font"}
GLOBAL_ATTRS_TO_DROP = {
    "style",
    "dir",
    "role",
    "id",
    "class",
    "width",
    "height",
    "align",
    "valign",
    "cellpadding",
    "cellspacing",
    "border",
}


def _is_aria_attr(attr_name: str) -> bool:
    return attr_name.lower().startswith("aria-")


def _remove_disallowed_tags(soup: BeautifulSoup, allowed_tags: set[str]) -> None:
    for tag in list(soup.find_all(True)):
        if tag.name in {"script", "style", "meta", "link", "iframe", "object", "embed"}:
            tag.decompose()
            continue

        if tag.name in allowed_tags or tag.name in UNWRAP_TAGS:
            continue

        # Preserve readable content while dropping non-semantic wrappers.
        tag.unwrap()


def _unwrap_styling_containers(soup: BeautifulSoup) -> None:
    for tag_name in UNWRAP_TAGS:
        for tag in list(soup.find_all(tag_name)):
            tag.unwrap()


def _clean_attrs_for_tag(tag: Tag) -> None:
    if tag.name == "a":
        keep = {"href", "target", "rel"}
        for attr in list(tag.attrs):
            if attr not in keep:
                del tag.attrs[attr]
        if "href" not in tag.attrs:
            tag.unwrap()
        return

    if tag.name == "img":
        keep = {"src", "alt"}
        for attr in list(tag.attrs):
            if attr not in keep:
                del tag.attrs[attr]
        if "src" not in tag.attrs:
            tag.decompose()
            return
        tag.attrs["width"] = "100%"
        return

    for attr in list(tag.attrs):
        if attr in GLOBAL_ATTRS_TO_DROP or _is_aria_attr(attr):
            del tag.attrs[attr]


def _clean_all_attributes(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(True):
        _clean_attrs_for_tag(tag)


def _remove_empty_blocks(soup: BeautifulSoup) -> None:
    block_tags = ["p", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6"]
    meaningful_media = ["img", "table", "ul", "ol", "hr"]
    for name in block_tags:
        for tag in list(soup.find_all(name)):
            text = tag.get_text("", strip=True).replace("\xa0", "")
            has_meaningful_media = bool(tag.find(meaningful_media))
            if not text and not has_meaningful_media:
                tag.decompose()


def _remove_empty_inline_tags(soup: BeautifulSoup) -> None:
    inline_tags = ["strong", "b", "em", "i", "u", "a"]
    for name in inline_tags:
        for tag in list(soup.find_all(name)):
            text = tag.get_text("", strip=True).replace("\xa0", "")
            has_meaningful_media = bool(tag.find(["img"]))
            if not text and not has_meaningful_media:
                tag.decompose()


def _simplify_redundant_markup(soup: BeautifulSoup) -> None:
    # Headings are already semantic emphasis; nested inline emphasis tags are redundant.
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        for inline in list(heading.find_all(["strong", "b", "em", "i", "u"])):
            inline.unwrap()

    # When a paragraph contains only an image wrapped by inline emphasis tags,
    # unwrap those tags to keep output minimal: <p><strong><img ...></strong></p> -> <p><img ...></p>
    for para in soup.find_all("p"):
        direct_tags = [child for child in para.children if isinstance(child, Tag)]
        if len(direct_tags) != 1:
            continue
        wrapper = direct_tags[0]
        if wrapper.name not in {"strong", "b", "em", "i", "u"}:
            continue

        para_text = para.get_text("", strip=True).replace("\xa0", "")
        has_img = bool(wrapper.find("img"))
        if not para_text and has_img:
            wrapper.unwrap()


def _post_regex_cleanup(html: str) -> str:
    html = re.sub(r"<p>(?:\s|&nbsp;|\xa0|<br\s*/?>)*</p>", "", html, flags=re.IGNORECASE)
    html = re.sub(
        r"<p>\s*(?:<(?:strong|b|em|i|u|a)>\s*)*(?:<br\s*/?>\s*)*(?:</(?:strong|b|em|i|u|a)>\s*)*</p>",
        "",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(r"(?:<br\s*/?>\s*){3,}", "<br><br>", html, flags=re.IGNORECASE)
    html = re.sub(r"\n{3,}", "\n\n", html)
    html = re.sub(r">\s+<", "><", html)
    return html.strip()


def sanitize_html(raw_html: str) -> str:
    if not raw_html or not raw_html.strip():
        return ""

    soup = BeautifulSoup(raw_html, "lxml")

    root = soup.body if soup.body else soup

    _remove_disallowed_tags(root, ALLOWED_TAGS)
    _unwrap_styling_containers(root)
    _clean_all_attributes(root)
    _simplify_redundant_markup(root)
    _remove_empty_inline_tags(root)
    _remove_empty_blocks(root)

    # Use inner HTML so we don't emit html/head/body wrappers.
    if soup.body:
        cleaned_html = "".join(str(node) for node in soup.body.contents)
    else:
        cleaned_html = str(soup)

    return _post_regex_cleanup(cleaned_html)


def _format_html_for_multiline_output(cleaned_html: str) -> str:
    if not cleaned_html:
        return ""

    # Keep output compact but readable by splitting around structural blocks.
    multiline = re.sub(
        r">\s*<(p|h1|h2|h3|h4|h5|h6|ul|ol|li|table|thead|tbody|tfoot|tr|td|th|hr)",
        r">\n<\1",
        cleaned_html,
        flags=re.IGNORECASE,
    )
    multiline = re.sub(r"\n{3,}", "\n\n", multiline)
    return multiline.strip()


def _preview_html_shell(content: str) -> str:
    safe_content = content or "<p>No content yet.</p>"
    return f"""
    <div style=\"background:#ffffff;color:#0f172a;border:1px solid #d1d5db;border-radius:12px;padding:16px;line-height:1.65;font-size:16px;overflow:auto;\">
      {safe_content}
    </div>
    """


def _copy_button_component(content: str) -> str:
    payload = json.dumps(content)
    return f"""
    <div style=\"margin: 0.25rem 0 0.75rem 0;\">
        <button id=\"copy-clean-html\" style=\"
            background:#0b1220;
            color:#e5e7eb;
            border:1px solid #334155;
            border-radius:10px;
            padding:10px 14px;
            font-size:14px;
            font-weight:600;
            cursor:pointer;
        \">Copy Sanitized HTML</button>
        <span id=\"copy-status\" style=\"margin-left:10px;color:#16a34a;font-size:13px;\"></span>
    </div>
    <script>
        const textToCopy = {payload};
        const btn = document.getElementById('copy-clean-html');
        const status = document.getElementById('copy-status');

        btn.onclick = async () => {{
            if (!textToCopy) {{
                status.textContent = 'Nothing to copy yet.';
                status.style.color = '#ef4444';
                return;
            }}
            try {{
                await navigator.clipboard.writeText(textToCopy);
                status.textContent = 'Copied';
                status.style.color = '#16a34a';
            }} catch (err) {{
                status.textContent = 'Copy failed. Use Command+C from the output box.';
                status.style.color = '#ef4444';
            }}
        }};
    </script>
    """


def _render_visual_editor(default_value: str) -> str:
    if st_quill is None:
        st.warning(
            "Rich text editor dependency is missing. Install with: pip install streamlit-quill"
        )
        return st.text_area(
            "Paste content (fallback input)",
            value=default_value,
            height=350,
            key="visual_fallback_input",
        )

    return st_quill(
        value=default_value,
        html=True,
        placeholder="Paste from Word/Google Docs here...",
        key="rich_editor",
    )


def _ensure_session_defaults() -> None:
    if "raw_html" not in st.session_state:
        st.session_state.raw_html = ""


def _input_mode_selector() -> str:
    if hasattr(st, "segmented_control"):
        mode = st.segmented_control(
            "Input Mode",
            options=["📝 Visual Rich Text", "💻 HTML Code"],
            default="📝 Visual Rich Text",
            key="input_mode",
        )
    else:
        mode = st.radio(
            "Input Mode",
            options=["📝 Visual Rich Text", "💻 HTML Code"],
            horizontal=True,
            key="input_mode",
        )
    return mode


def main() -> None:
    st.set_page_config(page_title="HTML Cleaner", layout="wide")
    _ensure_session_defaults()
    editor_height = 420

    st.markdown(
        """
        <style>
        .stTextArea textarea {
            font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
            font-size: 14px;
            line-height: 1.55;
        }
        [data-testid="stTextArea"] textarea {
            background: #0f172a;
            color: #e5e7eb;
            border: 1px solid #334155;
            border-radius: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("Rich Text / HTML Bloat Cleaner")
    st.caption(
        "Paste Word/Google Docs content, remove inline styling, and export semantic HTML."
    )

    left_col, right_col = st.columns(2, gap="large")

    with left_col:
        st.subheader("Input")
        mode = _input_mode_selector()

        if mode == "📝 Visual Rich Text":
            visual_html = _render_visual_editor(st.session_state.raw_html)
            st.session_state.raw_html = visual_html or ""
        else:
            st.session_state.raw_html = st.text_area(
                "Paste raw HTML",
                value=st.session_state.raw_html,
                height=editor_height,
                key="html_source",
                placeholder="<p dir=\"ltr\"><span style=\"font-size:14pt\">...</span></p>",
                help="After pasting in HTML mode, press Command+Enter (or Ctrl+Enter) to apply instantly.",
            )

    raw_html = st.session_state.raw_html
    cleaned_html = sanitize_html(raw_html)
    readable_html = _format_html_for_multiline_output(cleaned_html)

    with right_col:
        st.subheader("Sanitized Output")
        html_component(_copy_button_component(cleaned_html), height=60)
        st.text_area(
            "Clean HTML (multiline)",
            value=readable_html,
            height=editor_height,
            key="sanitized_output_multiline",
            disabled=True,
        )
        st.download_button(
            "Download Clean HTML",
            data=cleaned_html.encode("utf-8"),
            file_name="cleaned_content.html",
            mime="text/html",
            use_container_width=True,
        )

    st.markdown("---")
    st.subheader("Live Preview Comparison")
    preview_left, preview_right = st.columns(2, gap="large")

    with preview_left:
        st.markdown("**Original Input Preview**")
        html_component(_preview_html_shell(raw_html), height=360, scrolling=True)

    with preview_right:
        st.markdown("**Sanitized Output Preview**")
        html_component(_preview_html_shell(cleaned_html), height=360, scrolling=True)


if __name__ == "__main__":
    main()
