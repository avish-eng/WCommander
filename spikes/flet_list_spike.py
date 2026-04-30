from __future__ import annotations

import time
from dataclasses import dataclass

import flet as ft


INITIAL_ROW_COUNT = 100
MAX_ROW_COUNT = 100_000


@dataclass(slots=True)
class RowData:
    index: int
    name: str
    ext: str
    size: int


def make_rows(count: int) -> list[RowData]:
    exts = ["txt", "py", "md", "zip", "jpg", "json"]
    return [
        RowData(
            index=i,
            name=f"file_{i:06d}",
            ext=exts[i % len(exts)],
            size=(i * 137) % 50_000_000,
        )
        for i in range(count)
    ]


def build_row(row: RowData, selected: bool) -> ft.Control:
    bg = ft.Colors.with_opacity(0.12, ft.Colors.CYAN) if selected else None
    return ft.Container(
        padding=ft.padding.symmetric(horizontal=8, vertical=6),
        bgcolor=bg,
        content=ft.Row(
            spacing=12,
            controls=[
                ft.Text(str(row.index), width=90, color=ft.Colors.GREY_400),
                ft.Text(row.name, width=240, no_wrap=True),
                ft.Text(row.ext.upper(), width=70),
                ft.Text(f"{row.size:,}", width=120, text_align=ft.TextAlign.RIGHT),
            ],
        ),
    )


def main(page: ft.Page) -> None:
    page.title = "Flet List Spike"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 12
    page.window_min_width = 900
    page.window_min_height = 700

    current_row_count = INITIAL_ROW_COUNT
    rows = make_rows(current_row_count)
    selected_index = 0

    stats_text = ft.Text(color=ft.Colors.GREY_400)
    list_view = ft.ListView(expand=True, spacing=0)

    def rebuild_list() -> None:
        nonlocal list_view
        started = time.perf_counter()
        list_view.controls = [
            build_row(row, selected=(row.index == selected_index)) for row in rows
        ]
        elapsed = time.perf_counter() - started
        stats_text.value = (
            f"rows={current_row_count:,} | selected={selected_index:,} | "
            f"control build={elapsed:.2f}s"
        )
        page.update()

    def move_cursor(delta: int) -> None:
        nonlocal selected_index
        selected_index = max(0, min(current_row_count - 1, selected_index + delta))
        rebuild_list()

    def load_size(count: int) -> None:
        nonlocal current_row_count, rows, selected_index
        current_row_count = count
        rows = make_rows(current_row_count)
        selected_index = 0
        rebuild_list()

    header = ft.Container(
        padding=ft.padding.symmetric(horizontal=8, vertical=10),
        bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
        content=ft.Row(
            controls=[
                ft.Text("#", width=90, weight=ft.FontWeight.BOLD),
                ft.Text("Name", width=240, weight=ft.FontWeight.BOLD),
                ft.Text("Ext", width=70, weight=ft.FontWeight.BOLD),
                ft.Text("Size", width=120, weight=ft.FontWeight.BOLD),
            ],
        ),
    )

    controls = [
        ft.Text("Flet list spike", size=24, weight=ft.FontWeight.BOLD),
        ft.Text(
            "Start at 100 rows to verify rendering, then step up to 1k, 10k, and 100k. "
            "If 100 renders but 100k blanks or freezes, that is useful signal.",
            color=ft.Colors.GREY_400,
        ),
        ft.Row(
            spacing=8,
            controls=[
                ft.ElevatedButton("100", on_click=lambda _: load_size(100)),
                ft.OutlinedButton("1k", on_click=lambda _: load_size(1_000)),
                ft.OutlinedButton("10k", on_click=lambda _: load_size(10_000)),
                ft.OutlinedButton("100k", on_click=lambda _: load_size(MAX_ROW_COUNT)),
                ft.OutlinedButton("Cursor -1", on_click=lambda _: move_cursor(-1)),
                ft.OutlinedButton("Cursor +1", on_click=lambda _: move_cursor(1)),
                ft.OutlinedButton("Cursor +100", on_click=lambda _: move_cursor(100)),
                stats_text,
            ],
        ),
        header,
        ft.Container(
            expand=True,
            border=ft.border.all(1, ft.Colors.GREY_800),
            border_radius=8,
            content=list_view,
        ),
    ]

    page.add(ft.Column(expand=True, controls=controls))
    load_size(INITIAL_ROW_COUNT)


if __name__ == "__main__":
    ft.app(target=main)
