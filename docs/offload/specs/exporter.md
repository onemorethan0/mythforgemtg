out: tests/test_exporter_build.py
model: qwen3:14b
include: exporter.py
---
Write `tests/test_exporter_build.py`: pytest tests for `build_zip`, `build_pdf` and the private `_make_page` / `_cut_mark` helpers in the source above. Read the exact signatures of `build_zip`, `build_video_zip` and `build_pdf` off the source (parameters, `ImageResolver`, return types) and call them exactly that way.

Use Pillow to make small solid-colour test images in `tmp_path`; pass a custom resolver where the source allows one so no real render directory is needed. Keep images tiny so tests run fast.

Cover:
1. `build_zip` returns something that `zipfile.ZipFile` can open, and the archive lists one PNG entry per card given a resolver that supplies an image.
2. The empty-archive case: read what the source does when no card has an image and assert exactly that (do not guess).
3. `build_pdf` output starts with the bytes `%PDF`.
4. `_make_page` returns a PIL image; with the max number of slots the source allows it does not raise; read the page size/slot count off the source.
5. `_cut_mark` draws on an `ImageDraw` without raising.
Do not test `build_video_zip` beyond what is simple and certain. If an expected value is not certain from the source, assert a property instead.
