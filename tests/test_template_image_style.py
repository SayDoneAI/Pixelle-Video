"""
Unit tests for get_template_image_style function.

Verifies that the function correctly reads template:image-style meta tags
from HTML template files.
"""

import os
import tempfile

import pytest

from pixelle_video.utils.template_util import get_template_image_style


@pytest.fixture
def template_dir(tmp_path, monkeypatch):
    """Create a temporary template directory structure."""
    size_dir = tmp_path / "templates" / "1080x1920"
    size_dir.mkdir(parents=True)
    # Patch resolve_template_path to look in our tmp dir
    monkeypatch.setattr(
        "pixelle_video.utils.template_util.resolve_template_path",
        lambda p: str(size_dir / os.path.basename(p))
    )
    return size_dir


class TestGetTemplateImageStyle:
    """Verify get_template_image_style reads meta tags correctly."""

    def test_returns_style_from_meta_tag(self, template_dir):
        """Should extract content from template:image-style meta tag."""
        html = (
            '<!DOCTYPE html>\n<html>\n<head>\n'
            '    <meta charset="UTF-8">\n'
            '    <meta name="template:media-width" content="1024">\n'
            '    <meta name="template:media-height" content="1024">\n'
            '    <meta name="template:image-style" content="Soft watercolor illustration, pastel colors">\n'
            '</head>\n<body></body>\n</html>'
        )
        (template_dir / "test.html").write_text(html, encoding="utf-8")
        result = get_template_image_style("test.html")
        assert result == "Soft watercolor illustration, pastel colors"

    def test_returns_none_when_no_meta_tag(self, template_dir):
        """Should return None if template has no image-style meta tag."""
        html = (
            '<!DOCTYPE html>\n<html>\n<head>\n'
            '    <meta charset="UTF-8">\n'
            '    <meta name="template:media-width" content="1024">\n'
            '</head>\n<body></body>\n</html>'
        )
        (template_dir / "no_style.html").write_text(html, encoding="utf-8")
        result = get_template_image_style("no_style.html")
        assert result is None

    def test_returns_none_for_missing_file(self, monkeypatch):
        """Should return None when template file doesn't exist."""
        monkeypatch.setattr(
            "pixelle_video.utils.template_util.resolve_template_path",
            lambda p: "/nonexistent/path/missing.html"
        )
        result = get_template_image_style("missing.html")
        assert result is None

    def test_reads_real_template(self):
        """Should read image-style from an actual project template."""
        result = get_template_image_style("1080x1920/image_simple_black.html")
        assert result is not None
        assert "black-and-white" in result.lower() or "matchstick" in result.lower()

    def test_single_quotes_in_meta(self, template_dir):
        """Should handle single-quoted attribute values."""
        html = (
            "<!DOCTYPE html>\n<html>\n<head>\n"
            "    <meta name='template:image-style' content='Neon glow art'>\n"
            "</head>\n<body></body>\n</html>"
        )
        (template_dir / "single_q.html").write_text(html, encoding="utf-8")
        result = get_template_image_style("single_q.html")
        assert result == "Neon glow art"

    def test_style_with_commas_and_special_chars(self, template_dir):
        """Should handle styles containing commas and various punctuation."""
        style = "Bold satirical cartoon, exaggerated expressions, social commentary illustration"
        html = (
            '<!DOCTYPE html>\n<html>\n<head>\n'
            f'    <meta name="template:image-style" content="{style}">\n'
            '</head>\n<body></body>\n</html>'
        )
        (template_dir / "special.html").write_text(html, encoding="utf-8")
        result = get_template_image_style("special.html")
        assert result == style
