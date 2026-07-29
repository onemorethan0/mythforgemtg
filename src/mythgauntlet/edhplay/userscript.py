"""Generate a Tampermonkey userscript that shows custom card art on EDHPlay.

EDHPlay renders every card as an ``<img>`` whose ``src`` is a Scryfall image URL keyed by
that printing's UUID (e.g. ``cards.scryfall.io/normal/front/9/3/<uuid>.jpg``). There is no
server-side way to give a card a custom image, so the art is swapped **client-side**: a
userscript watches the DOM and rewrites the ``src`` of any card image whose UUID belongs to a
deck card we have custom art for.

Robustness comes from mapping **every** printing UUID of each card (from the printings store)
to that card's custom image -- so the swap fires no matter which printing EDHPlay happens to
show, and you don't have to pin printings. URL art is fetched once via ``GM_xmlhttpRequest``
(bypassing CORS / mixed-content) and cached as a blob URL; embedded art is a data URI used
directly.

Proven against the live site: injecting this swap replaces the card face in hand, on the
battlefield and in zoom previews. It is **local to your browser** -- opponents see the normal
card unless they run the same script. See docs/EDHPLAY_EXPORT.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from mythgauntlet.data.printings import PrintingDb
from mythgauntlet.edhplay.artsource import ArtRef, ArtSource
from mythgauntlet.model.card import normalize_name


@dataclass
class UserscriptResult:
    text: str
    matched: list[str]        # deck cards that got custom art
    unmatched_art: list[str]  # art-source entries with no matching deck card
    no_art: list[str]         # deck cards with no custom art
    uuid_count: int           # total printing UUIDs mapped


def _build_uuid_map(
    deck_names: list[str], art: ArtSource, pdb: PrintingDb
) -> tuple[dict[str, str], list[str], list[str], set[str]]:
    """Map every printing UUID of each art-having deck card -> its image ref value.

    Returns (uuid->value, matched cards, deck cards without art, hosts to @connect).
    """
    uuid_to_value: dict[str, str] = {}
    matched: list[str] = []
    no_art: list[str] = []
    connect: set[str] = set(art.connect_hosts)

    for name in deck_names:
        ref: ArtRef | None = art.by_name.get(normalize_name(name))
        if ref is None:
            no_art.append(name)
            continue
        uuids = [p.scryfall_id for p in pdb.printings(name) if p.scryfall_id]
        if not uuids:
            no_art.append(name)
            continue
        for u in uuids:
            uuid_to_value[u] = ref.value
        matched.append(name)
    return uuid_to_value, matched, no_art, connect


# The runtime is plain ES5-ish JS kept in a template so it reads like the userscript it becomes.
_RUNTIME = r"""(function () {
  'use strict';
  // uuid -> image value (a data: URI, or an http(s) URL fetched via GM_xmlhttpRequest).
  var ART = __ART_JSON__;
  var UUID_RE = /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/;
  var blobCache = {};   // value -> resolved data/blob URL ready for <img src>

  function resolve(value, cb) {
    if (value.indexOf('data:') === 0) { cb(value); return; }
    if (blobCache[value]) { cb(blobCache[value]); return; }
    if (typeof GM_xmlhttpRequest === 'undefined') { cb(value); return; }
    GM_xmlhttpRequest({
      method: 'GET', url: value, responseType: 'blob',
      onload: function (r) {
        try {
          var url = URL.createObjectURL(r.response);
          blobCache[value] = url; cb(url);
        } catch (e) { cb(value); }
      },
      onerror: function () { cb(value); }
    });
  }

  function swapImg(img) {
    if (!img || !img.src || img.dataset.mfDone === '1') return;
    var m = img.src.match(UUID_RE);
    if (!m) return;
    var value = ART[m[1]];
    if (!value) return;
    img.dataset.mfDone = '1';               // mark before async so we don't re-enter
    resolve(value, function (finalUrl) {
      if (img.src !== finalUrl) img.src = finalUrl;
      img.srcset = '';                       // kill responsive variants that would override
    });
  }

  function scan(root) {
    if (!root) return;
    if (root.tagName === 'IMG') { swapImg(root); return; }
    if (root.querySelectorAll) {
      var imgs = root.querySelectorAll('img');
      for (var i = 0; i < imgs.length; i++) swapImg(imgs[i]);
    }
  }

  scan(document);
  var obs = new MutationObserver(function (muts) {
    for (var i = 0; i < muts.length; i++) {
      var mu = muts[i];
      if (mu.type === 'attributes' && mu.target && mu.target.tagName === 'IMG') {
        // EDHPlay re-set the src (re-render); clear our flag so we can swap again.
        if (mu.attributeName === 'src' && mu.target.dataset.mfDone === '1'
            && mu.target.src.indexOf('blob:') !== 0 && mu.target.src.indexOf('data:') !== 0) {
          mu.target.dataset.mfDone = '';
          swapImg(mu.target);
        }
      } else {
        for (var j = 0; j < mu.addedNodes.length; j++) scan(mu.addedNodes[j]);
      }
    }
  });
  obs.observe(document.documentElement, {
    childList: true, subtree: true, attributes: true, attributeFilter: ['src']
  });
  console.log('[MythForge art] active; ' + Object.keys(ART).length + ' printings mapped.');
})();
"""


def _metadata_block(title: str, connect_hosts: set[str]) -> str:
    lines = [
        "// ==UserScript==",
        f"// @name         {title}",
        "// @namespace    mythgauntlet.edhplay",
        "// @version      1.0",
        "// @description  Show your MythForge custom card art on EDHPlay (local to your browser).",
        "// @match        https://edhplay.com/*",
        "// @match        https://www.edhplay.com/*",
        "// @run-at       document-start",
        "// @grant        GM_xmlhttpRequest",
    ]
    for host in sorted(connect_hosts):
        lines.append(f"// @connect      {host}")
    lines.append("// ==/UserScript==")
    return "\n".join(lines)


def build_userscript(
    deck_names: list[str],
    art: ArtSource,
    pdb: PrintingDb,
    *,
    title: str = "MythForge art on EDHPlay",
) -> UserscriptResult:
    """Produce a ready-to-install Tampermonkey userscript for a deck's custom art."""
    uuid_map, matched, no_art, connect = _build_uuid_map(deck_names, art, pdb)

    deck_keys = {normalize_name(n) for n in deck_names}
    unmatched_art = sorted(
        k for k in art.by_name if k not in deck_keys
    )

    art_json = json.dumps(uuid_map, ensure_ascii=False)
    body = _RUNTIME.replace("__ART_JSON__", art_json)
    text = _metadata_block(title, connect) + "\n\n" + body

    return UserscriptResult(
        text=text,
        matched=sorted(matched),
        unmatched_art=unmatched_art,
        no_art=sorted(no_art),
        uuid_count=len(uuid_map),
    )
