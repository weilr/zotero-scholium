"""In-memory PDF regressions for bounded column scanning and vector clustering."""
import pymupdf
import pytest

from zotero_scholium import cli


@pytest.mark.parametrize("pages", [60, 61, 119, 120, 179])
def test_column_bounds_samples_at_most_sixty_pages(monkeypatch, pages):
    with pymupdf.open() as doc:
        for _ in range(pages):
            doc.new_page(width=612, height=792)
        reads = []
        original = pymupdf.Page.get_text

        def get_text(page, *args, **kwargs):
            reads.append(page.number)
            return original(page, *args, **kwargs)

        monkeypatch.setattr(pymupdf.Page, "get_text", get_text)
        assert cli.column_bounds(doc) is None
        assert len(reads) <= 60
        assert reads[0] == 0
        assert len(reads) == len(set(reads))


def scatter_page(doc):
    page = doc.new_page(width=612, height=792)
    shape = page.new_shape()
    for row in range(40):
        for col in range(60):
            x, y = 100 + col * 6, 250 + row * 6
            shape.draw_rect(pymupdf.Rect(x, y, x + 1, y + 1))
            shape.finish(color=(0, 0, 0))
    shape.commit()
    return page


def cluster_work(monkeypatch):
    sizes = []
    original = pymupdf.Page.cluster_drawings

    def cluster(page, *args, **kwargs):
        drawings = kwargs.get("drawings")
        sizes.append(len(page.get_drawings() if drawings is None else drawings))
        return original(page, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Page, "cluster_drawings", cluster)
    return sizes


def test_isolated_scatter_does_not_enter_quadratic_full_page_clustering(monkeypatch):
    with pymupdf.open() as doc:
        page = scatter_page(doc)
        sizes = cluster_work(monkeypatch)
        assert cli.page_figure_rects(page) == []
        assert sum(size * size for size in sizes) <= 2400 * 16


def test_scatter_keeps_images_large_figures_and_clusters_of_tiny_paths(monkeypatch):
    with pymupdf.open() as doc:
        page = scatter_page(doc)
        image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
        image.clear_with(100)
        page.insert_image(pymupdf.Rect(4, 60, 52, 140), pixmap=image, keep_proportion=False)
        page.draw_rect(pymupdf.Rect(548, 60, 608, 140))
        page.draw_rect(pymupdf.Rect(160, 80, 420, 220))
        # Every primitive is too small to be an obstacle; together they are a figure
        # that crosses the right text-column boundary and reaches into the margin.
        shape = page.new_shape()
        for row in range(4):
            for col in range(8):
                x, y = 530 + col * 3, 170 + row * 3
                shape.draw_rect(pymupdf.Rect(x, y, x + 1, y + 1))
                shape.finish(color=(0, 0, 0))
        shape.commit()
        sizes = cluster_work(monkeypatch)
        rects = cli.page_figure_rects(page)
        assert sorted(rects) == sorted([
            [4.0, 652.0, 52.0, 732.0],
            [548.0, 652.0, 608.0, 732.0],
            [530.0, 612.0, 552.0, 622.0],
            [160.0, 572.0, 420.0, 712.0],
        ])
        assert sum(size * size for size in sizes) <= 2400 * 16
        pi = cli.PageIndex(page, (55.0, 543.0))
        spec = cli.normalise_summary({"page": 1, "rect": [535, 170, 580, 195], "text": "figure"},
                                     cli.DEFAULTS, [(612, 792)])
        missed = []
        annotations = cli.layout_page_summaries(pi, [spec], rects, missed)
        assert missed == []
        assert "overlaps" in annotations[0]["layout_warning"]


def test_zero_width_paths_at_the_neighbor_tolerance_still_form_an_obstacle():
    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)
        for x in (540, 543, 546, 549):
            page.draw_line(pymupdf.Point(x, 210), pymupdf.Point(x, 222))
        assert cli.page_figure_rects(page) == [[540.0, 570.0, 549.0, 582.0]]


def test_disjoint_groups_keep_vector_obstacles_in_page_order():
    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.draw_rect(pymupdf.Rect(4, 250, 50, 310))
        page.draw_rect(pymupdf.Rect(550, 40, 600, 100))
        assert cli.page_figure_rects(page) == [
            [550.0, 692.0, 600.0, 752.0],
            [4.0, 482.0, 50.0, 542.0],
        ]
