# Cross-VLAN Google Home device addresses

Status: approved by Kyle on 2026-08-11

Upstream baseline: `de3e73218725913335a9650a270296cfb73e5b77`
(`master`, 14 commits after `v1.13.3`)

## Goal

Make `ha-google-home` work when Home Assistant can route to Google Home devices
but cannot discover them with mDNS. Users can provide a Google-reported device
name to IPv4-address mapping in the integration options. The integration must
also surface IP-less devices instead of silently returning an empty coordinator
payload.

This is a local fork for line-by-line review before Kyle pushes it. Nothing in
this project writes Home Assistant configuration or contacts the live Home
Assistant instance.

## Verified premises

### glocaltokens 0.7.6 gate

The actual `v0.7.6` source defines `get_google_devices` with both required
parameters:

- `disable_discovery: bool = False`
- `addresses: dict[str, str] | None = None`

With discovery disabled, glocaltokens validates the supplied values as IPv4
addresses and matches mapping keys against Google-reported device names. This
passes the blocking Step 0 gate.

Sources:

- <https://pypi.org/project/glocaltokens/0.7.6/>
- <https://github.com/leikoilja/glocaltokens/blob/v0.7.6/glocaltokens/client.py>

### Upstream baseline gate

The complete runtime diff from `v1.13.3` to the cloned upstream `master` is
empty. The only changes are dependency bumps in:

- `.github/workflows/manage-labels.yml`
- `.github/workflows/release-drafter.yml`

The fork therefore starts from current upstream `master` without inheriting an
unreviewed runtime delta.

## Patch 2: preserve and explain IP-less devices

Patch 2 is first and remains independently upstreamable.

`GlocaltokensApiClient` keeps a runtime set of device IDs for which a missing-IP
warning has already been emitted. On every coordinator refresh:

1. A device without an IP is marked unavailable.
2. If its stable device ID has not warned during this API-client runtime, emit a
   warning even when the device began the refresh unavailable.
3. The warning prints `device.name` unchanged and tells the user to copy that
   exact, case-and-spacing-sensitive name into the device-address mapping.
4. Only devices with both `ip_address` and `auth_token` are polled, preserving
   the stock polling subset.
5. After those polls finish, return the complete original device list in its
   original order. IP-less and token-less devices remain present.

The warning does not separately re-arm after recovery. A mapping change reloads
the config entry, rebuilds the client, and resets the warning set. The diagnostic
device entity remains the UI signal for any later mid-runtime regression.

Returning IP-less devices lets the existing sensor setup create the diagnostic
`_device` sensor while continuing to gate alarm and timer sensors on token and
availability.

## Patch 1: manual IPv4 mapping

Add a `device_addresses` object mapping to the config-entry options. Validation
accepts an absent mapping or `{}` and otherwise requires:

- a mapping object;
- string keys whose stripped form is non-empty;
- string values accepted by `ipaddress.IPv4Address`;
- no IPv6 values.

Keys are stored unchanged because glocaltokens matches them exactly against the
Google-reported device name. The option description and `CHANGES.md` must state
that matching is case- and spacing-sensitive.

The non-empty mapping is global manual mode for the glocaltokens call:

- pass `addresses=device_addresses`;
- pass `disable_discovery=True`;
- mDNS discovery is disabled for every device;
- users must map every device they want addressable.

An omitted second device remains in the coordinator payload through Patch 2 and
warns with its exact Google-reported name, giving the user the key needed to add
it.

When the mapping is absent or empty, call glocaltokens with exactly the original
argument set. Do not pass new parameters with default or empty values. This
keeps the stock discovery path byte-for-byte unchanged at the call boundary.

### Applying an option change

Alarm and timer entities are selected only when the sensor platform is set up.
A coordinator refresh cannot add entities omitted during the initial IP-less
setup. Therefore a changed device-address mapping triggers a config-entry
reload, which:

- discards the old API client and cached device list;
- performs an immediate first refresh with the new mapping;
- sets up the platform again from the new coordinator data;
- creates alarm and timer entities for newly addressable devices.

Polling-interval-only and request-timeout-only changes remain inexpensive
in-place updates and do not reload the entry.

## Patch 3: null-IP rediscovery gate

Patch 3 is optional. Include it only if a small isolated change can retry a
transient null-IP discovery result without causing endless homegraph or mDNS
work for a permanently unreachable or intentionally unmapped device.

Manual mode already solves the target deployment's null-IP condition. If the
no-endless-loop bar cannot be met cleanly, omit Patch 3 and explain why in
`CHANGES.md`.

## Patch 4: configurable request timeout

Patch 4 carries a presumption of inclusion because a two-second TLS request
timeout is likely too short across the VLAN boundary.

- Add a positive-integer request-timeout option.
- Raise the default from 2 seconds to 10 seconds.
- Pass the effective value to `ClientTimeout(total=...)`.
- Apply timeout-only option changes to the existing API client without reloading
  the config entry.

Omit Patch 4 only if its isolated diff or tests demonstrate a concrete risk, and
record that decision in `CHANGES.md`.

## Error handling and user guidance

- Invalid address mappings stay in the options form for correction and do not
  replace the stored options.
- Mapping validation errors explain the non-empty-name and IPv4-only rules.
- A missing or near-match mapping key produces the Patch 2 warning containing
  the exact name required to fix it.
- The options description and `CHANGES.md` explicitly say that a non-empty
  mapping disables discovery for every device, so all desired devices must be
  mapped.
- No address, account identifier, token, or deployment-specific device name is
  hardcoded in the integration.

## Test design

Patch 2 tests cover:

- cold-start warning even when the model already says unavailable;
- exactly one warning per device ID per API-client runtime;
- verbatim device name in the warning;
- no polling for a missing IP or auth token;
- polling only the stock `ip_address and auth_token` subset;
- returning every device in original order.

Patch 1 tests cover:

- absent mapping and `{}` producing the exact stock glocaltokens call;
- a valid non-empty mapping adding only `addresses` and
  `disable_discovery=True`;
- valid options storage and setup propagation;
- rejection of non-mappings, blank names, non-string values, malformed IPv4,
  and IPv6 while preserving form input;
- mapping-change entry reload;
- poll-interval-only changes staying in place.

Patch 4 tests cover:

- the 10-second default;
- a configured override;
- timeout-only live option updates without entry reload;
- `ClientTimeout(total=effective_timeout)` at the request boundary.

Patch 3, if included, receives focused retry and permanent-failure tests that
prove it meets the no-endless-loop inclusion bar.

Run the repository's complete test suite and every formatting, lint, and type
check exposed by its project configuration. Review the complete diff and each
commit independently.

## Commit sequence

1. Approved design record only.
2. Patch 2 and its focused tests.
3. Patch 1 and its focused tests.
4. Patch 3 and tests only if its inclusion gate passes.
5. Patch 4 and its focused tests, presumed included.
6. Manifest fork-version bump and `CHANGES.md`.

No remote push is part of this work. The final local `master` must be clean and
ready for Kyle's line-by-line review and later push to a fork whose default
branch is this patched branch.
