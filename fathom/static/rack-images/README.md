# Rack device images

Front and rear WebP images of rack-mounted devices, shown on rack elevations
and in the rack library palette. Catalog templates
(`fathom/library/rackula/catalog.json`) point at them with `image_front` /
`image_rear`, a path relative to this directory
(`<vendor>/<slug>.<face>.webp`, served at `/static/rack-images/...`).

## Origin

Copied unchanged by `tools/rackula_catalog.py` from Rackula
(<https://github.com/RackulaLives/Rackula>, MIT, commit
`9c7af6dd28209a776aebdb92080bcf2916cd29e6`, `src/lib/assets/device-images/`).
Only these vendor folders are bundled, to keep the package small (total
≤ 4.5 MB): `_generic`, `apc`, `eaton`, `ac-infinity`, `ubiquiti`, `netgear`,
`cisco`, `tp-link`, `mikrotik`, `synology`, `qnap`, `dell`, `apple`, `lenovo`,
`supermicro`. Rackula's `_generic` folder (its own generic artwork, flattened
from its `server/`, `network/`, … subfolders) ships here as `generic/`,
because the static file route rejects path segments that start with `_` or
`.`. Catalog entries from other vendors ship without images.

Do not edit these files by hand: change the generator and run
`python tools/rackula_catalog.py --src /tmp/rackula`.

## Licence

Most images come from vastoholic's Draw.io rack shape library
(<https://github.com/vastoholic/draw-io>), "freely shareable to anyone who
wishes to use them in any project", by way of the NetBox community
devicetype-library (<https://github.com/netbox-community/devicetype-library>,
CC0 1.0) and Rackula (MIT, Copyright (c) 2026 Gareth Evans). Product names and
appearances belong to their manufacturers. Full notices are in
`THIRD_PARTY_NOTICES.md` at the repository root.
