"""Resolve a *custom-art source* to one image per card.

The custom art you want on EDHPlay is the AI-generated card render from MythForge (or any
folder of card images). This module turns a source into ``{normalized_card_name: ArtRef}``,
where an ArtRef is either a URL the browser fetches at play time, or inline image bytes
embedded straight into the userscript.

Sources:

* ``mythforge:<job_id>`` -- pull a MythForge build's ``deck.json`` over HTTP (default base
  ``http://127.0.0.1:8000``) and point each card at its ``card-image/<render_key>`` render.
  Only cards MythForge actually rendered (``has_render``) are included.
* ``dir:<path>`` -- a folder of ``<Card Name>.png`` (or .jpg/.webp) files; matched by stem.
* ``manifest:<file>`` -- a text/JSON file of ``Card Name = path-or-url`` lines.

MythForge/dir sources are local, so the resulting art is what *you* see in your browser; other
players still see the normal printing unless they run the same script. See docs/EDHPLAY_EXPORT.md.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path

import requests

from mythgauntlet.config import USER_AGENT
from mythgauntlet.model.card import normalize_name

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
DEFAULT_MYTHFORGE_BASE = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class ArtRef:
    """A custom image for one card.

    kind='url'  -> value is a URL the userscript fetches at runtime (GM_xmlhttpRequest).
    kind='data' -> value is a full ``data:<mime>;base64,...`` URI embedded in the script.
    """

    kind: str
    value: str


@dataclass
class ArtSource:
    by_name: dict[str, ArtRef]              # normalized card name -> ArtRef
    connect_hosts: set[str]                 # hosts the userscript must @connect to
    missing_render: list[str]               # cards present but not yet rendered (info)
    note: str = ""


def _host_of(url: str) -> str:
    # http://127.0.0.1:8000/... -> 127.0.0.1
    after = url.split("://", 1)[-1]
    return after.split("/", 1)[0].split(":", 1)[0]


def _data_uri(path: Path) -> ArtRef:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return ArtRef("data", f"data:{mime};base64,{b64}")


def from_mythforge(
    job_id: str,
    *,
    base_url: str = DEFAULT_MYTHFORGE_BASE,
    embed: bool = False,
    timeout: float = 15.0,
) -> ArtSource:
    """Resolve a MythForge build job to per-card render URLs (or embedded bytes)."""
    base = base_url.rstrip("/")
    url = f"{base}/api/deck/{job_id}"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    cards = []
    if data.get("commander"):
        cards.append(data["commander"])
    cards.extend(data.get("deck") or [])

    by_name: dict[str, ArtRef] = {}
    connect: set[str] = set()
    missing: list[str] = []
    for c in cards:
        name = c.get("original_name") or c.get("name")
        rk = c.get("render_key")
        if not name or not rk:
            continue
        if not c.get("has_render", False):
            missing.append(name)
            continue
        img_url = f"{base}/api/deck/{job_id}/card-image/{rk}"
        if embed:
            r = requests.get(img_url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            r.raise_for_status()
            mime = r.headers.get("Content-Type", "image/png").split(";")[0]
            b64 = base64.b64encode(r.content).decode("ascii")
            by_name[normalize_name(name)] = ArtRef("data", f"data:{mime};base64,{b64}")
        else:
            by_name[normalize_name(name)] = ArtRef("url", img_url)
            connect.add(_host_of(img_url))
    return ArtSource(by_name, connect, missing,
                     note=f"MythForge job {job_id}: {len(by_name)} rendered")


def from_dir(path: str, *, embed: bool = True) -> ArtSource:
    """Resolve a folder of ``<Card Name>.<ext>`` images. Embedded by default (local files)."""
    root = Path(path)
    if not root.is_dir():
        raise NotADirectoryError(f"Art directory not found: {root}")
    by_name: dict[str, ArtRef] = {}
    for p in sorted(root.iterdir()):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        key = normalize_name(p.stem)
        if key in by_name:
            continue
        by_name[key] = _data_uri(p) if embed else ArtRef("url", p.as_uri())
    return ArtSource(by_name, set(), [], note=f"{len(by_name)} images from {root}")


def from_manifest(path: str, *, embed: bool = True) -> ArtSource:
    """Resolve a manifest: JSON ``{name: ref}`` or text ``Name = ref`` lines.

    A ref is a URL (kept as a runtime fetch) or a local file path (embedded, or file:// url).
    """
    text = Path(path).read_text(encoding="utf-8")
    pairs: dict[str, str] = {}
    stripped = text.lstrip()
    if stripped.startswith("{"):
        pairs = {k: str(v) for k, v in json.loads(text).items()}
    else:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            sep = "=" if "=" in line else (":" if ":" in line else "")
            if not sep:
                continue
            name, ref = line.split(sep, 1)
            pairs[name.strip()] = ref.strip()

    by_name: dict[str, ArtRef] = {}
    connect: set[str] = set()
    base = Path(path).parent
    for name, ref in pairs.items():
        key = normalize_name(name)
        if ref.startswith(("http://", "https://")):
            by_name[key] = ArtRef("url", ref)
            connect.add(_host_of(ref))
        else:
            p = Path(ref)
            if not p.is_absolute():
                p = base / p
            if not p.exists():
                continue
            by_name[key] = _data_uri(p) if embed else ArtRef("url", p.as_uri())
    return ArtSource(by_name, connect, [], note=f"{len(by_name)} entries from {path}")


def resolve(spec: str, *, base_url: str = DEFAULT_MYTHFORGE_BASE, embed: bool = False) -> ArtSource:
    """Dispatch an ``--art-source`` spec (``mythforge:``/``dir:``/``manifest:``)."""
    if spec.startswith("mythforge:"):
        return from_mythforge(spec.split(":", 1)[1], base_url=base_url, embed=embed)
    if spec.startswith("dir:"):
        # Local files can't be fetched from an https page at runtime -> always embed.
        return from_dir(spec.split(":", 1)[1], embed=True)
    if spec.startswith("manifest:"):
        return from_manifest(spec.split(":", 1)[1], embed=True)
    raise ValueError(
        "art source must start with 'mythforge:', 'dir:' or 'manifest:' "
        f"(got {spec!r})"
    )
