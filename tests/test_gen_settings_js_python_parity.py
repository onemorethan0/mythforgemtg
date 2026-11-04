"""The Advanced panels are generated from frontend/src/config/genSettings.js, and the server reads
them through api.models.GenSettingsModel -> image_gen.GenSettings. Both files say the keys and
defaults "MUST match". This runs the real JS schema under Node and checks it against the Python
side, so adding or renaming a knob in one place fails loudly instead of silently sending a field
the server drops. Skipped when Node is not installed."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import MISSING, fields
from pathlib import Path

import pytest

from api.models import GenSettingsModel
from image_gen import GenSettings

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "frontend" / "src" / "config" / "genSettings.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None or not JS.exists(), reason="node or the JS schema is unavailable")


def _schema():
    script = ("import { GEN_SETTINGS_SCHEMA as S } from " + json.dumps(JS.as_uri()) + ";\n"
              "console.log(JSON.stringify(S.map(f => ({key: f.key, default: f.default === undefined ? null : f.default,"
              " type: f.type, min: f.min ?? null, max: f.max ?? null, options: (f.options||[]).map(o => o.value)}))));\n")
    out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _py_default(name):
    for f in fields(GenSettings):
        if f.name == name:
            return None if f.default is MISSING else f.default
    raise KeyError(name)


def test_every_ui_field_is_a_real_server_field():
    py_fields = {f.name for f in fields(GenSettings)}
    model_fields = set(GenSettingsModel.model_fields)
    for f in _schema():
        assert f["key"] in py_fields, f"UI sends '{f['key']}' but GenSettings has no such field"
        assert f["key"] in model_fields, f"UI sends '{f['key']}' but GenSettingsModel would drop it"


def test_ui_defaults_equal_the_server_defaults_where_the_server_has_one():
    for f in _schema():
        py = _py_default(f["key"])
        if py is None:
            continue            # the server means "model default" (steps: 28 dev / 8 schnell); the UI shows the dev value
        assert f["default"] == py, f"{f['key']}: UI default {f['default']!r} != server default {py!r}"


def test_a_select_fields_options_include_its_default():
    for f in _schema():
        # (a select whose options are filled in at runtime, like style_variant, has none here)
        if f["type"] == "select" and f["default"] is not None and f["options"]:
            assert f["default"] in f["options"], f"{f['key']}: default {f['default']!r} is not one of its options"


def test_slider_defaults_sit_inside_their_own_range():
    for f in _schema():
        if f["type"] in ("slider", "number") and f["min"] is not None and f["default"] is not None:
            assert f["min"] <= f["default"] <= f["max"], f"{f['key']}: default outside [{f['min']}, {f['max']}]"


def test_the_model_does_not_accept_fields_the_ui_never_sends():
    """The reverse direction: a server field with no UI control is dead weight, or a UI knob that
    was removed without the server noticing."""
    ui = {f["key"] for f in _schema()}
    # face_method / face_weight / style_variant are driven from their own steps, not the schema
    extras = set(GenSettingsModel.model_fields) - ui
    assert extras <= {"face_method", "face_weight", "style_variant", "sampler", "scheduler"}, extras
