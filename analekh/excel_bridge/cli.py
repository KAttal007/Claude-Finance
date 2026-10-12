"""Excel bridge (design doc 13, 19.2, 22.1): runs on the analyst's machine.

    uv sync --group bridge
    python -m analekh.excel_bridge scan            # index watched folders, show suggestions
    python -m analekh.excel_bridge link PATH SYMBOL # confirm a link; writes the hidden tag
    python -m analekh.excel_bridge watch           # re-scan when models change (terminal status)
    python -m analekh.excel_bridge apply CS_ID PATH # write an approved change set

Configuration (22.3): ANALEKH_API, WATCH_FOLDERS (semicolon separated), SAVE_MODE.
"""

import time
import uuid
from dataclasses import asdict
from pathlib import Path

import httpx
import typer

from analekh.config import get_settings
from analekh.excel_bridge import indexer, writer
from analekh.workbook.tags import Tag

app = typer.Typer(help="Analekh Excel bridge", no_args_is_help=True)


def _api() -> httpx.Client:
    return httpx.Client(base_url=get_settings().analekh_api, timeout=60)


@app.command()
def scan() -> None:
    """Index watched folders and ask the server which company each workbook belongs to."""
    hints = indexer.scan(get_settings().watch_folder_paths)
    if not hints:
        typer.echo("No workbooks found in WATCH_FOLDERS.")
        return
    with _api() as api:
        resp = api.post("/models/discover", json={"workbooks": [asdict(h) for h in hints]})
        resp.raise_for_status()
    for c in resp.json()["candidates"]:
        status = (
            "linked"
            if c.get("model_id")
            else (
                f"looks like {c['symbol']} ({c['method']}, {c['confidence']:.2f})"
                if c["symbol"]
                else "no match"
            )
        )
        typer.echo(f"{c['path']}: {status}")


@app.command()
def link(path: Path, symbol: str) -> None:
    """Confirm that a workbook is the model for SYMBOL; writes the hidden tag into it."""
    h = indexer.hints_for(path)
    with _api() as api:
        resp = api.post("/models/link", json={"symbol": symbol, "workbook": asdict(h)})
        resp.raise_for_status()
    model = resp.json()
    writer.link_tag(path, Tag(uuid.UUID(model["doc_tag"]), symbol.upper()))
    typer.echo(f"Linked {path.name} to {symbol.upper()} as model {model['id']}.")


@app.command()
def watch(interval: int = 30) -> None:
    """Re-scan when files in WATCH_FOLDERS change (watchdog), printing a status line."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    changed = {"dirty": True}

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):  # type: ignore[no-untyped-def]
            if str(event.src_path).lower().endswith(tuple(indexer.EXTENSIONS)):
                changed["dirty"] = True

    observer = Observer()
    for folder in get_settings().watch_folder_paths:
        if folder.exists():
            observer.schedule(Handler(), str(folder), recursive=True)
    observer.start()
    try:
        while True:
            if changed["dirty"]:
                changed["dirty"] = False
                scan()
            time.sleep(interval)
    finally:
        observer.stop()
        observer.join()


@app.command()
def apply(change_set_id: int, path: Path) -> None:
    """Write an approved change set into the workbook (versioned copy by default)."""
    with _api() as api:
        cs = api.get(f"/change-sets/{change_set_id}").json()
    if cs["status"] != "approved":
        raise typer.BadParameter(f"change set is {cs['status']}; decide every item first")
    writes = [
        writer.Write(
            i["sheet"],
            i["cell"],
            i["final_value"],
            i["formula_after"] if i["decision"] == "accepted" else None,
        )
        for i in cs["items"]
        if i["decision"] in ("accepted", "edited")
    ]
    dst = writer.apply(path, writes, get_settings().save_mode, f"cs{change_set_id}")
    typer.echo(f"Wrote {len(writes)} cells; saved {dst}")


if __name__ == "__main__":
    app()
