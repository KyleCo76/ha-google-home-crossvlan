# Cross-VLAN Google Home Device Addresses Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a reviewable `ha-google-home` fork that accepts exact-name IPv4 mappings for cross-VLAN devices, surfaces IP-less devices, and tolerates slower device TLS requests.

**Architecture:** Patch 2 first preserves all homegraph devices while polling only the original addressable/authenticated subset and emits one actionable missing-IP warning per device and client runtime. Patch 1 stores a validated object mapping in config-entry options, passes manual-mode arguments only when the mapping is non-empty, and schedules a config-entry reload when the entity-shaping mapping changes. Patch 4 adds an in-place configurable request timeout; Patch 3 is included only if a bounded rediscovery design passes its no-endless-loop gate.

**Tech Stack:** Python 3.14 development environment, Home Assistant 2026.1.0 APIs, glocaltokens 0.7.6, `unittest`/pytest 9, `unittest.mock`, voluptuous, Ruff, mypy, Pylint, codespell, pre-commit.

---

## Preconditions and invariants

- Work only in `/home/kyle/Projects/ha-google-home-fork`.
- Baseline is upstream `de3e73218725913335a9650a270296cfb73e5b77`.
- `v1.13.3..de3e732` changes only two GitHub Actions dependency pins.
- glocaltokens `v0.7.6` has `addresses=` and `disable_discovery=` with the expected shapes.
- The approved design is `docs/plans/2026-08-11-cross-vlan-device-addresses-design.md`.
- Never add a fork remote or push.
- Never contact or modify the Home Assistant instance.
- Keep one implementation commit per patch; tests belong in the same commit as their patch.
- The final version/`CHANGES.md` work is a separate commit.

### Task 1: Add Patch 2 regression tests

**Files:**

- Create: `tests/__init__.py`
- Create: `tests/helpers.py`
- Create: `tests/test_api.py`

**Step 1: Add a typed client factory**

Create `tests/__init__.py` as an empty package marker. In `tests/helpers.py`, add
an executor stub and a factory that patches construction of the real
glocaltokens client while returning both the integration client and the mock:

```python
"""Test helpers for Google Home."""

from collections.abc import Callable
from typing import TypeVar, cast
from unittest.mock import MagicMock, patch

from aiohttp import ClientSession
from homeassistant.core import HomeAssistant

from custom_components.google_home.api import GlocaltokensApiClient

_T = TypeVar("_T")


class ImmediateExecutor:
    """Run executor jobs synchronously for unit tests."""

    async def async_add_executor_job(self, target: Callable[[], _T]) -> _T:
        """Run and return an executor target."""
        return target()


def make_client(**kwargs: object) -> tuple[GlocaltokensApiClient, MagicMock]:
    """Create an API client without constructing a real glocaltokens client."""
    with patch(
        "custom_components.google_home.api.GLocalAuthenticationTokens"
    ) as client_class:
        client = GlocaltokensApiClient(
            hass=cast("HomeAssistant", ImmediateExecutor()),
            session=cast("ClientSession", MagicMock()),
            **kwargs,
        )
    return client, client_class.return_value
```

If strict typing rejects `**kwargs: object`, replace it with explicit optional
parameters matching only those required by tests; do not weaken project-wide
typing.

**Step 2: Write failing Patch 2 tests**

In `tests/test_api.py`, use `unittest.IsolatedAsyncioTestCase` and
`unittest.mock.AsyncMock`. Cover these exact cases:

```python
class TestUpdateGoogleDevicesInformation(IsolatedAsyncioTestCase):
    async def test_ipless_device_warns_on_first_refresh_even_if_already_unavailable(self):
        device = GoogleHomeDevice("device-1", "Bedroom display", "token")
        device.available = False
        client, _ = make_client()
        client.google_devices = [device]

        with (
            patch.object(client, "collect_data_from_endpoints", new_callable=AsyncMock) as collect,
            patch("custom_components.google_home.api._LOGGER.warning") as warning,
        ):
            result = await client.update_google_devices_information()

        self.assertEqual(result, [device])
        self.assertFalse(device.available)
        collect.assert_not_awaited()
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[-1], "Bedroom display")

    async def test_ipless_device_warns_once_per_client_runtime(self):
        # Call update twice with the same IP-less device ID and assert one warning.

    async def test_only_addressable_authenticated_devices_are_polled(self):
        # Use valid, IP-less, and token-less devices.
        # Assert only the valid device is awaited and all three are returned in order.

    async def test_each_ipless_device_id_warns_once_with_its_exact_name(self):
        # Use two IDs and names with case/spacing differences.
        # Assert two calls whose final formatting arguments equal the exact names.
```

The warning-format assertion must also verify that the message tells users the
name is exact and case/spacing-sensitive for manual address mappings.

**Step 3: Run the focused tests and confirm RED**

Run:

```bash
.venv/bin/pytest tests/test_api.py -q
```

Expected: failures because IP-less devices are omitted, the log is DEBUG-only,
and there is no per-runtime warned-ID set.

Do not change runtime code until these failures have been observed.

### Task 2: Implement and commit Patch 2

**Files:**

- Modify: `custom_components/google_home/api.py:47-72`
- Modify: `custom_components/google_home/api.py:141-166`
- Test: `tests/test_api.py`

**Step 1: Add runtime warning state**

Initialize one set on each API client:

```python
self._missing_ip_warning_device_ids: set[str] = set()
```

**Step 2: Preserve all devices and warn on cold start**

Replace the existing debug/filtered-return block with this behavior:

```python
for device in devices:
    if device.ip_address:
        continue

    device.available = False
    if device.device_id in self._missing_ip_warning_device_ids:
        continue

    self._missing_ip_warning_device_ids.add(device.device_id)
    _LOGGER.warning(
        "Failed to fetch timers/alarms because no IP address was found. "
        "Google-reported device name: %s. Use this exact, case- and "
        "spacing-sensitive name for a manual device-address mapping.",
        device.name,
    )

await asyncio.gather(
    *(
        self.collect_data_from_endpoints(device)
        for device in devices
        if device.ip_address and device.auth_token
    )
)
return devices
```

Keep the exact stock polling predicate. Do not re-arm IDs inside this patch.

**Step 3: Run Patch 2 tests and confirm GREEN**

Run:

```bash
.venv/bin/pytest tests/test_api.py -q
.venv/bin/ruff check custom_components/google_home/api.py tests
.venv/bin/ruff format --check custom_components/google_home/api.py tests
.venv/bin/mypy custom_components/google_home/api.py tests
.venv/bin/pylint custom_components/google_home/api.py tests
```

Expected: all commands exit 0. Make narrow typing/style corrections only.

**Step 4: Inspect and commit Patch 2 alone**

Run:

```bash
git diff --check
git diff -- custom_components/google_home/api.py tests
git status --short
git add custom_components/google_home/api.py tests/__init__.py tests/helpers.py tests/test_api.py
git commit -m "fix: surface Google Home devices without IPs"
```

Expected: one commit containing only Patch 2 and its test harness/tests.

### Task 3: Add failing Patch 1 API-call tests

**Files:**

- Modify: `tests/test_api.py`

**Step 1: Test the byte-identical stock call boundary**

Add async tests for clients constructed with no mapping and with `{}`. Configure
the mocked glocaltokens client to return `[]`, call `get_google_devices`, and
assert exactly:

```python
glocaltokens_client.get_google_devices.assert_called_once_with(
    zeroconf_instance=zeroconf_instance,
    force_homegraph_reload=True,
)
```

The assertion must prove that neither `addresses` nor `disable_discovery`
appears.

**Step 2: Test non-empty global manual mode**

Construct with `{"Bedroom display": "192.0.2.50"}` and assert exactly:

```python
glocaltokens_client.get_google_devices.assert_called_once_with(
    addresses={"Bedroom display": "192.0.2.50"},
    disable_discovery=True,
    zeroconf_instance=zeroconf_instance,
    force_homegraph_reload=True,
)
```

Use RFC 5737 documentation addresses in tests; never use the deployment IP.

**Step 3: Run focused tests and confirm RED**

Run:

```bash
.venv/bin/pytest tests/test_api.py -q
```

Expected: constructor rejects `device_addresses` and/or the manual call lacks
the required arguments.

### Task 4: Add failing Patch 1 options and reload tests

**Files:**

- Create: `tests/test_config_flow.py`
- Create: `tests/test_init.py`

**Step 1: Test address validation**

Test a public module helper named `validate_device_addresses` directly. Assert:

- `{}` and a valid exact-name IPv4 mapping return equal dictionaries;
- non-mapping input raises `vol.Invalid`;
- blank and whitespace-only names raise;
- non-string values raise;
- malformed IPv4 raises;
- IPv6 raises;
- case and spacing in a valid key are returned unchanged.

**Step 2: Test options-flow behavior**

Instantiate `GoogleHomeOptionsFlowHandler`, attach a typed mock `hass`, set its
`handler` to a mock entry ID, and make
`hass.config_entries.async_get_known_entry` return an entry with existing
options. Assert:

- valid input creates an entry whose data contains the mapping unchanged;
- invalid input returns the `init` form with
  `errors[CONF_DEVICE_ADDRESSES] == "invalid_device_addresses"`;
- the invalid object remains the schema default so the user can correct it;
- the schema field is a native `ObjectSelector`;
- omitted/empty mapping remains allowed.

**Step 3: Test setup propagation and update behavior**

In `tests/test_init.py`, mock session, zeroconf, client, coordinator, entry, and
config-entry forwarding. Assert:

- `async_setup_entry` passes the stored mapping into `GlocaltokensApiClient`;
- changed mapping calls
  `hass.config_entries.async_schedule_reload(entry.entry_id)` and returns before
  mutating the existing coordinator interval;
- unchanged mapping plus a changed polling interval updates
  `coordinator.update_interval` in place and does not schedule reload.

Use `async_schedule_reload`, not `await async_reload`; Home Assistant 2026.1.0's
API explicitly prefers the scheduler from integration update listeners because
it cancels retry setup and avoids reload races.

**Step 4: Run Patch 1 tests and confirm RED**

Run:

```bash
.venv/bin/pytest tests/test_api.py tests/test_config_flow.py tests/test_init.py -q
```

Expected: missing constants, helper, constructor parameter, selector, and reload
behavior cause failures.

### Task 5: Implement and commit Patch 1

**Files:**

- Modify: `custom_components/google_home/const.py`
- Modify: `custom_components/google_home/types.py`
- Modify: `custom_components/google_home/config_flow.py`
- Modify: `custom_components/google_home/__init__.py`
- Modify: `custom_components/google_home/api.py`
- Modify: `custom_components/google_home/translations/en.json`
- Test: `tests/test_api.py`
- Test: `tests/test_config_flow.py`
- Test: `tests/test_init.py`

**Step 1: Add the option constant and type**

Add:

```python
CONF_DEVICE_ADDRESSES: Final = "device_addresses"
```

Make `device_addresses` a `NotRequired[dict[str, str]]` member of
`OptionsFlowDict`; preserve `update_interval` as required.

**Step 2: Implement strict IPv4 mapping validation**

In `config_flow.py`, import `Mapping`, `IPv4Address`, and
`homeassistant.helpers.selector`. Add:

```python
def validate_device_addresses(value: object) -> dict[str, str]:
    """Validate and copy an exact-name to IPv4-address mapping."""
    if not isinstance(value, Mapping):
        raise vol.Invalid("Device addresses must be a mapping")

    validated: dict[str, str] = {}
    for name, address in value.items():
        if not isinstance(name, str) or not name.strip():
            raise vol.Invalid("Device names must be non-empty strings")
        if not isinstance(address, str):
            raise vol.Invalid("Device addresses must be strings")
        try:
            IPv4Address(address)
        except ValueError as err:
            raise vol.Invalid("Device addresses must be valid IPv4 addresses") from err
        validated[name] = address
    return validated
```

Do not strip or normalize keys or values.

**Step 3: Add form-preserving object-selector handling**

In `async_step_init`, use the submitted input as defaults after a validation
error, otherwise use stored options. On valid input, replace the submitted
mapping with the validated copy before `async_create_entry`. Add the form field:

```python
vol.Optional(
    CONF_DEVICE_ADDRESSES,
    default=defaults.get(CONF_DEVICE_ADDRESSES, {}),
): selector.ObjectSelector()
```

Return field error `invalid_device_addresses` without creating an options entry.

**Step 4: Add conditional glocaltokens calls**

Accept `device_addresses: Mapping[str, str] | None = None` in the API-client
constructor and copy it to `_device_addresses`. Expose a read-only comparison
property. In the executor closure, use two explicit branches:

```python
if self._device_addresses:
    return self._client.get_google_devices(
        addresses=self._device_addresses,
        disable_discovery=True,
        zeroconf_instance=self.zeroconf_instance,
        force_homegraph_reload=True,
    )
return self._client.get_google_devices(
    zeroconf_instance=self.zeroconf_instance,
    force_homegraph_reload=True,
)
```

The explicit stock branch is the byte-identical-call guarantee.

**Step 5: Propagate options and schedule entity-shaping reloads**

Read `CONF_DEVICE_ADDRESSES` during setup and pass it to the API client. In
`async_update_entry`, retrieve both the current client and coordinator. Compare
the new mapping with the mapping held by the running client:

```python
if device_addresses != client.device_addresses:
    _LOGGER.debug("Device addresses updated, scheduling config entry reload...")
    hass.config_entries.async_schedule_reload(entry.entry_id)
    return
```

Only after this branch, retain the existing in-place polling interval update.

**Step 6: Add exact-name and global-manual-mode guidance**

Add English option text stating all of the following:

- keys must exactly match the Google-reported name, including case and spacing;
- values must be IPv4 addresses;
- a non-empty mapping disables discovery for every device;
- users must map every device they want addressable;
- leaving the mapping empty preserves automatic discovery.

Add `options.error.invalid_device_addresses` with the non-empty-name and
IPv4-only validation rule.

**Step 7: Run focused and full checks**

Run:

```bash
.venv/bin/pytest tests -q
.venv/bin/ruff check custom_components/google_home tests
.venv/bin/ruff format --check custom_components/google_home tests
.venv/bin/mypy custom_components/google_home tests
.venv/bin/pylint custom_components/google_home tests
.venv/bin/python -m json.tool custom_components/google_home/translations/en.json >/dev/null
```

Expected: all exit 0.

**Step 8: Inspect and commit Patch 1 alone**

Run:

```bash
git diff --check
git diff -- custom_components/google_home tests
git status --short
git add custom_components/google_home/const.py custom_components/google_home/types.py custom_components/google_home/config_flow.py custom_components/google_home/__init__.py custom_components/google_home/api.py custom_components/google_home/translations/en.json tests
git commit -m "feat: configure manual Google Home addresses"
```

Expected: one Patch 1 commit, including its tests and option description.

### Task 6: Evaluate Patch 3 against the no-endless-loop gate

**Files:**

- Inspect: `custom_components/google_home/api.py`
- Potential test: `tests/test_api.py`
- Document final decision: `CHANGES.md`

**Step 1: Prove or reject a bounded design before editing**

Evaluate the obvious guard from the brief:

```python
if not self.google_devices or any(
    device.ip_address is None for device in self.google_devices
):
```

Reject it if an IP-less device would force homegraph plus mDNS work every
coordinator cycle. Also reject any design that retries all intentionally
unmapped devices while global manual mode is active.

**Step 2: Consider only bounded alternatives**

An includable design must be small, disabled in manual mode, and have an
explicit bound such as one automatic rediscovery retry per API-client runtime.
Tests must prove both the retry and that later cycles stop retrying a permanent
failure.

**Step 3: Decide from diff and test evidence**

- If the bounded design remains minimal and all tests pass, implement it in a
  dedicated Patch 3 commit.
- Otherwise make no Patch 3 code change and record in `CHANGES.md` that automatic
  `any-null` rediscovery was omitted because it creates an endless discovery and
  homegraph loop for permanent or intentionally unmapped devices.

Do not broaden this task into redesigning the refresh service or adding backoff.

### Task 7: Add failing Patch 4 tests

**Files:**

- Modify: `tests/test_api.py`
- Modify: `tests/test_config_flow.py`
- Modify: `tests/test_init.py`

**Step 1: Test timeout defaults and overrides**

Add tests asserting:

- a client created without an override exposes a 10-second request timeout;
- a client created with an override exposes that positive integer;
- the options form defaults to 10 and rejects zero/negative values;
- setup passes a configured timeout to the API client;
- a timeout-only options change updates the running client in place, changes no
  polling semantics, and does not schedule reload.

**Step 2: Test the aiohttp request boundary**

Mock `ClientTimeout` and the session async context manager, perform one request,
and assert:

```python
client_timeout.assert_called_once_with(total=effective_timeout)
```

Cover both default and configured values without making network calls.

**Step 3: Run focused tests and confirm RED**

Run:

```bash
.venv/bin/pytest tests -q
```

Expected: missing timeout option/property and the existing two-second constant
cause failures.

### Task 8: Implement and commit Patch 4

**Files:**

- Modify: `custom_components/google_home/const.py`
- Modify: `custom_components/google_home/types.py`
- Modify: `custom_components/google_home/config_flow.py`
- Modify: `custom_components/google_home/__init__.py`
- Modify: `custom_components/google_home/api.py`
- Modify: `custom_components/google_home/translations/en.json`
- Test: `tests/test_api.py`
- Test: `tests/test_config_flow.py`
- Test: `tests/test_init.py`

**Step 1: Add the option and raise the default**

Add:

```python
CONF_REQUEST_TIMEOUT: Final = "request_timeout"
TIMEOUT: Final = 10
```

Add required `request_timeout: int` typing to `OptionsFlowDict` because the form
supplies a default.

**Step 2: Store and use the effective timeout**

Add `request_timeout: int = TIMEOUT` to the API-client constructor, store it,
and expose a setter/property suitable for in-place option changes. Replace:

```python
ClientTimeout(total=TIMEOUT)
```

with:

```python
ClientTimeout(total=self.request_timeout)
```

**Step 3: Add positive-integer options handling**

Add a form field using:

```python
vol.Optional(
    CONF_REQUEST_TIMEOUT,
    default=defaults.get(CONF_REQUEST_TIMEOUT, TIMEOUT),
): vol.All(int, vol.Range(min=1))
```

Add concise English option text identifying seconds and the 10-second default.

**Step 4: Propagate setup and live updates**

Pass the effective timeout during setup. In `async_update_entry`, keep mapping
comparison/reload first, then update both polling interval and request timeout
in place.

**Step 5: Run tests and static checks**

Run:

```bash
.venv/bin/pytest tests -q
.venv/bin/ruff check custom_components/google_home tests
.venv/bin/ruff format --check custom_components/google_home tests
.venv/bin/mypy custom_components/google_home tests
.venv/bin/pylint custom_components/google_home tests
```

Expected: all exit 0. If a concrete risk appears, stop, retain the failing
evidence, and document exclusion instead of forcing Patch 4 through.

**Step 6: Inspect and commit Patch 4 alone**

Run:

```bash
git diff --check
git diff -- custom_components/google_home tests
git add custom_components/google_home tests
git commit -m "feat: configure Google Home request timeout"
```

Expected: one Patch 4 commit with no packaging or `CHANGES.md` edits.

### Task 9: Add fork version and CHANGES.md

**Files:**

- Modify: `custom_components/google_home/manifest.json`
- Create: `CHANGES.md`

**Step 1: Use an ordered fork version**

Set the manifest version to:

```json
"version": "1.13.4-crossvlan.1"
```

This is valid SemVer under Home Assistant's `AwesomeVersion` and compares
greater than stock `1.13.3`; unlike `1.13.3+crossvlan.1`, it is suitable for
HACS update tracking.

Verify:

```bash
.venv/bin/python -c 'from awesomeversion import AwesomeVersion; assert AwesomeVersion("1.13.4-crossvlan.1") > AwesomeVersion("1.13.3")'
```

**Step 2: Write the required CHANGES.md**

Keep it short but include:

- upstream baseline SHA and `v1.13.3` relationship;
- Step 0 verdict and versioned glocaltokens sources;
- Patch 2 behavior and exact-name warning semantics;
- Patch 1 object mapping, IPv4-only rule, exact case/spacing matching, and the
  global partial-mapping semantic: non-empty disables discovery for all devices,
  so map every desired device;
- Patch 3 inclusion or explicit no-endless-loop exclusion rationale;
- Patch 4 default/option and whether it was included;
- test/check commands and results;
- no hardcoded deployment values;
- HACS custom-repository steps: remove the stock store entry first, add Kyle's
  fork as an Integration custom repository, back out and search the store to
  install, and use the patched branch as the fork default because HACS 2.0's
  frontend cannot select branches.

Do not include credentials, account identifiers, or Kyle's deployment IP/name.

**Step 3: Validate and commit packaging/docs separately**

Run:

```bash
.venv/bin/python -m json.tool custom_components/google_home/manifest.json >/dev/null
.venv/bin/codespell CHANGES.md docs/plans
git diff --check
git diff -- custom_components/google_home/manifest.json CHANGES.md
git add custom_components/google_home/manifest.json CHANGES.md
git commit -m "docs: prepare cross-VLAN fork release"
```

Expected: one final packaging/documentation commit.

### Task 10: Full verification and review handoff

**Files:**

- Verify all tracked files and commits; do not edit unless a check identifies a
  defect.

**Step 1: Run the complete local test and static-analysis suite**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy custom_components/google_home tests
.venv/bin/pylint custom_components/google_home tests
.venv/bin/codespell
```

Expected: all exit 0.

**Step 2: Run the repository's exact pre-commit workflow**

Run with a disposable writable uv cache:

```bash
UV_CACHE_DIR=/tmp/ha-google-home-fork-uv-cache uvx pre-commit run --all-files --show-diff-on-failure --color=always
UV_CACHE_DIR=/tmp/ha-google-home-fork-uv-cache uvx pre-commit run --hook-stage manual python-typing-update --all-files --show-diff-on-failure --color=always
```

Expected: all hooks pass and make no changes. If hooks rewrite files, inspect,
re-run the relevant tests, and make a narrowly scoped follow-up commit rather
than amending Kyle's review history invisibly.

**Step 3: Audit every requirement against evidence**

Verify explicitly:

- Step 0 versioned signature evidence is present;
- Patch 2 is a standalone commit and passes focused tests;
- Patch 1 uses conditional arguments and passes stock/manual call tests;
- mapping validation and global partial-mapping guidance are present;
- mapping changes schedule entry reload while interval/timeout changes do not;
- Patch 3 decision meets the no-endless-loop bar;
- Patch 4 is included unless concrete risk evidence forced exclusion;
- manifest version is ordered above stock and has a fork suffix;
- `CHANGES.md` contains every requested HACS instruction;
- no deployment name or IP is hardcoded;
- no remote except upstream exists;
- no push occurred;
- the Home Assistant repository and live instance were untouched.

**Step 4: Inspect history and final diff**

Run:

```bash
git log --oneline --decorate upstream/master..HEAD
git diff --check upstream/master..HEAD
git diff --stat upstream/master..HEAD
git diff upstream/master..HEAD
git status --short --branch
git remote -v
```

Expected: clean `master`, only the intended reviewable commits, and only the
`upstream` remote.

**Step 5: Hand back without pushing**

Report:

- absolute local repository path;
- exact ordered commit list;
- Patch 3 decision and Patch 4 verdict;
- test/check results;
- the manifest version;
- a clickable `CHANGES.md` and full-diff command for Kyle's line-by-line review;
- explicit confirmation that nothing was pushed or deployed.
