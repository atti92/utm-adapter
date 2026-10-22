"""Execute the console's window rules without a browser or extra JS packages."""

from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is required for console logic checks")
def test_running_mission_window_does_not_become_dirty_when_start_passes() -> None:
    source = (Path(__file__).parents[1] / "src/utm_connector/ui/app.js").read_text()

    def function(name: str) -> str:
        body = source.split(f"function {name}(", 1)[1].split("\nfunction ", 1)[0]
        return f"function {name}(" + body

    functions = "\n".join(function(name) for name in (
        "missionWindowIsUsable", "inputAsIso", "validateMissionWindow", "missionMatchesForm"
    ))
    script = '''
const assert = require('node:assert/strict');
const TERMINAL_DECLARATIONS = new Set(['COMPLETED', 'CANCELLED', 'REJECTED']);
const start = new Date(Date.now() - 10000);
const end = new Date(Date.now() + 60000);
const state = {
  operation: {state: {declaration: 'ACCEPTED'}},
  capabilities: {mission_window: {requires_future_start: true}},
  mission: {mission: {valid_from: start.toISOString(), valid_until: end.toISOString(), corridor_radius_m: 200}}
};
const inputs = {
  'valid-from': {value: start.toISOString()},
  'valid-until': {value: end.toISOString()},
  'corridor-radius': {value: '200'}
};
const $ = id => inputs[id];
''' + functions + '''
assert.equal(missionWindowIsUsable(start, end), true);
assert.equal(missionMatchesForm(), true);
assert.throws(() => validateMissionWindow(), /start in the future/);
inputs['corridor-radius'].value = '300';
assert.equal(missionMatchesForm(), false);
state.operation.state.declaration = 'COMPLETED';
assert.equal(missionWindowIsUsable(start, end), false);
state.operation = null;
assert.equal(missionWindowIsUsable(start, end), false);
assert.equal(missionWindowIsUsable(end, start), false);
'''
    subprocess.run([NODE, "-"], input=script, text=True, check=True, capture_output=True)
