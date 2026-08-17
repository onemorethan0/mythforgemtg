# Notice — third-party and game content

The [MIT License](LICENSE) covers the **code in this repository only**. This file records what
Myth Forge depends on but does not own or distribute.

## Magic: The Gathering

Myth Forge is an **unofficial fan project**. It is not produced by, endorsed by, supported by, or
affiliated with Wizards of the Coast LLC.

*Magic: The Gathering* and all associated card names, rules text, mana symbols, frame designs and
other game content are trademarks and copyrights of Wizards of the Coast. Cards produced by this
tool are **proxies for personal, non-commercial playtesting**.

## Card data and images

Card data, oracle text, legality, prices and card images are fetched **at runtime** from the
[Scryfall API](https://scryfall.com/docs/api) and cached locally. None of it is redistributed in this
repository. Scryfall's terms and rate limits apply; the client sleeps 150 ms between requests and
sends an identifying User-Agent.

Deck-page synergy figures are fetched from EDHREC. This is an unofficial third-party endpoint, cached
locally with a 14-day staleness check, and every feature that uses it fails soft when it is
unreachable.

## Frame artwork

**This repository bundles no Wizards-copyrighted frame artwork.**

- The **built-in** frames, backgrounds, boxes, P/T badges, legendary crowns, mana symbols and fonts
  under `card_assets/` are sourced from **wingedsheep/mtg-card-generator**.
- The optional **official-style M15 / borderless** frames (`cc_frames.py`) are clean-room rendering
  code only. The frame PNGs are © Wizards of the Coast / their respective authors and are **supplied
  by you** from a local [Card Conjurer](https://github.com/Investigamer/cardconjurer) installation,
  pointed at via `MYTHFORGE_CC_DIR` or the in-app folder field.

> ⚠️ **Do not commit Card Conjurer assets to this or any public repository.** They are copyrighted
> and were the subject of a Wizards of the Coast cease-and-desist. `.gitignore` guards against
> accidental commits, but keep your Card Conjurer install **outside** the project folder.

## AI models

No model weights are distributed here. Checkpoints, LoRAs and other weights are downloaded by you
from their own sources and remain under their own licenses — including FLUX.1 (dev / schnell / Krea),
Stable Diffusion XL and Illustrious XL, SD 3.5, Qwen-Image, Hunyuan3D v2, LTX-Video, Wan 2.x, and the
GGUF language models served through llama.cpp. Several carry non-commercial or otherwise restrictive
terms. **Check the license of each model you install.**

The art-style presets reference community LoRAs by filename; where a source is known it is linked in
[`docs/INTERNALS.md`](docs/INTERNALS.md#art-style-presets) and [`MODELS.md`](MODELS.md). Those LoRAs
are not redistributed here either.

## Runtime dependencies

Python and JavaScript dependencies are declared in [`requirements.txt`](requirements.txt) and
[`frontend/package.json`](frontend/package.json) and installed from their respective registries under
their own licenses.
