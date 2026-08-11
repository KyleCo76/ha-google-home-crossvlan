# Cross-VLAN fork changes

Fork version: `1.13.4-crossvlan.1`

This fork is based on upstream `master` at
`de3e73218725913335a9650a270296cfb73e5b77`, 14 commits after `v1.13.3`.
The intervening upstream changes are only GitHub Actions dependency updates; the
integration runtime is unchanged from `v1.13.3`.

## Compatibility gates

The blocking glocaltokens gate passed against the version pinned by the
integration, `glocaltokens==0.7.6`. Its versioned `get_google_devices` source
supports both `addresses: dict[str, str] | None` and
`disable_discovery: bool = False`:

- <https://pypi.org/project/glocaltokens/0.7.6/>
- <https://github.com/leikoilja/glocaltokens/blob/v0.7.6/glocaltokens/client.py>

## Included changes

### Patch 2: surface devices without IP addresses

- Return the complete ordered HomeGraph device list while polling only the
  stock `ip_address and auth_token` subset.
- Mark IP-less devices unavailable instead of silently removing them.
- Warn once per device ID and API-client runtime, including the first refresh
  after a cold start.
- Print the Google-reported device name verbatim in the warning. Manual mapping
  keys must match that name exactly, including case and spacing.

### Patch 1: configure manual IPv4 addresses

- Add an options object that maps exact Google-reported device names to IPv4
  addresses. Names must be non-empty strings, values must be IPv4 strings, and
  IPv6 is deliberately rejected.
- Preserve the stock glocaltokens call when the mapping is absent or `{}`.
- A non-empty mapping disables discovery for every device: map every device you
  want addressable. An unmapped device remains IP-less and its warning supplies
  the exact name to add.
- Reload the config entry when the mapping changes so the API client, cached
  device list, and setup-time entity set are rebuilt. Poll-interval-only and
  timeout-only changes remain in-place updates.

### Patch 3: null-IP cache retry omitted

The literal `any(device.ip_address is None)` cache-invalidation guard was not
included. A permanently IP-less device would force HomeGraph reload and mDNS on
every coordinator cycle and manual refresh. In global manual mode, an
intentionally unmapped device would make that loop deterministic. A delayed
one-shot retry avoids the endless loop but cannot restore alarm/timer entities
after setup has already shaped the entity set; an immediate one-shot retry only
repeats startup discovery and does not address mid-runtime recovery. Neither
marginal path justifies additional retry state in this fork.

### Patch 4: configurable request timeout

- Raise the device HTTPS request timeout default from 2 seconds to 10 seconds
  for cross-VLAN TLS connections to the device's self-signed `:8443` endpoint.
- Add a positive-integer timeout option and pass its effective value to
  `ClientTimeout(total=...)`.
- Apply timeout-only option changes to the running API client without reloading
  the config entry.

No deployment address, account identifier, credential, token, or
deployment-specific device name is hardcoded in the integration.

## Verification

The implementation suite reports `28 passed, 6 subtests passed`. These checks
also pass:

```text
.venv/bin/pytest -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy --explicit-package-bases custom_components/google_home tests
.venv/bin/pylint custom_components/google_home tests
.venv/bin/codespell
```

## HACS 2.0 installation

1. Remove the stock Google Home store entry before installing this fork.
2. Add the fork repository URL to HACS as a custom repository with category
   **Integration**.
3. Back out of the custom-repository dialog, search the HACS store for Google
   Home, and install the fork entry.
4. Keep this patched branch as the fork repository's default branch. The HACS
   2.0 frontend cannot select a branch for installation.
