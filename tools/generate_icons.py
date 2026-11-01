"""Original geometric line glyphs. No third-party artwork is used."""
from pathlib import Path

ICONS = {
    "add": '<path d="M12 4v16M4 12h16"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v11h14V9M9 13h6"/>',
    "arrow-up": '<path d="M12 21V3M5 10l7-7 7 7"/>',
    "arrows": '<path d="M7 3v18m-4-4 4 4 4-4M17 21V3m-4 4 4-4 4 4"/>',
    "check": '<path d="m4 12 5 6L21 5"/>',
    "clock-three": '<circle cx="12" cy="12" r="9"/><path d="M12 6v6h5"/>',
    "comment-alt": '<path d="M4 3h16v14H9l-5 4V3Z"/><path d="M8 8h8M8 12h6"/>',
    "cross": '<path d="m5 5 14 14M5 19 19 5"/>',
    "cube": '<path d="m12 2 9 5v10l-9 5-9-5V7l9-5Zm-9 5 9 5 9-5M12 12v10"/>',
    "disk": '<path d="M3 3h15l3 3v15H3V3Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',
    "edit": '<path d="m4 16 12-12 4 4L8 20H4v-4Zm9-9 4 4"/>',
    "folder": '<path d="M2 6h8l2 3h10v11H2V6Z"/>',
    "folder-open": '<path d="M3 19V5h7l2 3h9v3M2 11h21l-4 9H4l-2-9Z"/>',
    "menu-dots": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "redo": '<path d="m15 3 6 6-6 6M21 9H10a7 7 0 0 0-7 7v5"/>',
    "undo": '<path d="m9 3-6 6 6 6M3 9h11a7 7 0 0 1 7 7v5"/>',
    "search": '<circle cx="10" cy="10" r="7"/><path d="m15 15 7 7"/>',
    "settings": '<path d="M4 5h16M4 12h16M4 19h16"/><circle cx="8" cy="5" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="19" r="2"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "trash": '<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7"/>',
    "user": '<circle cx="12" cy="7" r="4"/><path d="M3 22v-2a9 9 0 0 1 18 0v2"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="m2 2 20 20M3 8l-1 4s4 7 10 7c2 0 4-1 5-2M8 6l4-1c6 0 10 7 10 7l-3 4"/>',
    "chevron-dark": '<path d="m5 9 7 7 7-7"/>',
    "chevron-light": '<path d="m5 9 7 7 7-7"/>',
    "paperclip": '<path d="m8 13 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7L13 2M6 15l8-8"/>',
    "chamfer": '<path d="M3 21V3h12l6 6v12H3ZM15 3v6h6"/>',
    "fillet": '<path d="M3 21V3h10a8 8 0 0 1 8 8v10H3Z"/>',
    "fit": '<path d="M3 9V3h6M15 3h6v6M21 15v6h-6M9 21H3v-6"/><rect x="8" y="8" width="8" height="8"/>',
    "holes": '<rect x="3" y="3" width="18" height="18"/><circle cx="8" cy="8" r="2"/><circle cx="16" cy="16" r="2"/>',
    "palette": '<circle cx="7" cy="7" r="3"/><circle cx="17" cy="7" r="3"/><circle cx="7" cy="17" r="3"/><circle cx="17" cy="17" r="3"/>',
    "parameters": '<path d="M3 6h18M3 12h18M3 18h18M8 3v6M16 9v6M10 15v6"/>',
    "thickness": '<path d="M3 8h18M3 16h18M12 2v6m-3-3 3 3 3-3M12 22v-6m-3 3 3-3 3 3"/>',
}


def main():
    folder = Path(__file__).resolve().parents[1] / "assets/icons"
    for name, drawing in ICONS.items():
        color = "#ffffff" if name == "chevron-light" else "#000000"
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{drawing}</svg>\n'
        (folder / (name + ".svg")).write_text(svg, encoding="utf-8")
    (folder / "LICENSE").write_text((folder.parents[1] / "LICENSE").read_text(), encoding="utf-8")
    (folder / "README.md").write_text("# Original interface icons\n\nThese geometric line drawings are original Prompt to CAD artwork under the repository MIT license. Reproduce them with `python -m tools.generate_icons`. They replace the previously extracted third-party font glyphs; no Flaticon artwork is used by the current tree. The original purple pyramid branding is separate original application artwork.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
