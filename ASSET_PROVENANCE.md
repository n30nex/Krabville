# Asset Provenance

KVsim v2 artwork was created specifically for Canadaverse with OpenAI ImageGen
2. Existing project-owned Krabville map and resident artwork were supplied as
visual identity and palette references. No third-party game map, sprite atlas,
or UI asset was imported into the generated v2 asset family.

The project maintainer contributes the included generated and mechanically
derived files under this repository's Apache-2.0 license.

## Production Pipeline

ImageGen 2 produced the source renders in `art/kvsim/`. Local, deterministic
processing then performed only mechanical transformations:

1. Remove the keyed background from sprite and interior sheets.
2. Normalize transparency, padding, frame bounds, and grid alignment.
3. Resize with nearest-neighbour sampling where pixel edges must stay crisp.
4. Encode the large town map as WebP and retain PNG alpha for sprite atlases.
5. Validate dimensions and visually inspect the production files.

The `*-source-v2.png` files are direct ImageGen 2 outputs. Chroma-key working
files are intentionally excluded from version control. Files under
`frontend/public/assets/` are the browser-ready outputs.

## ImageGen 2 Sources

| Source | Dimensions | Purpose | Bytes | SHA-256 |
| --- | ---: | --- | ---: | --- |
| `art/kvsim/town-map-source-v2.png` | 1536x1024 | Large connected Lagoon town source with homes, civic buildings, workplaces, roads, bridges, and water | 4,190,737 | `b56abf09ab1cf74a7cb7f1c7390e5d3e1090ce20489314eb750ff1df23d1fdbf` |
| `art/kvsim/life-stages-source-v2.png` | 1254x1254 | Baby, child, teen, and senior movement source sheet | 1,640,504 | `e289e30ccbdec200966b2ca992ee792038bedab80b3cd49f531b4172fc574459` |
| `art/kvsim/interiors-source-v2.png` | 1448x1086 | Twelve-room source sheet for homes, care, commerce, health, and work | 2,501,023 | `230fd6280cc3d2f8b55dc0d0a9d5553017c438c2c28a86163d1b6298d32d967d` |

## Production Assets

| Asset | Dimensions | Runtime use | Bytes | SHA-256 |
| --- | ---: | --- | ---: | --- |
| `frontend/public/assets/kvsim-town-v2.webp` | 3072x2048 | Pannable production world map | 1,836,176 | `81df5eee659cea0b2cbbde84bee675acba9391445cbb31a647803e7ca55abc97` |
| `frontend/public/assets/life-stages-v2.png` | 768x768 | 4x4 lifecycle sprite atlas with 192x192 cells | 415,188 | `c42701fd3098194eb191a2f37f68273348f9a64e036b8f3efd88b1a701c2830d` |
| `frontend/public/assets/interiors-v2.png` | 1024x768 | 4x3 interior atlas with 256x256 cells | 1,316,784 | `c9dfffa14d77e8676abf10821848675f9eb23c52b721a9b61eccb02ca0b0aacd` |

The two existing adult resident atlases remain part of the production scene:

| Asset | Purpose | SHA-256 |
| --- | --- | --- |
| `frontend/public/assets/residents-a.png` | Adult resident sprite atlas A and visual identity reference | `00b7424ee4b738134f7af8c0e2301142af233674cf63df2f51e894d7f09cb08b` |
| `frontend/public/assets/residents-b.png` | Adult resident sprite atlas B and visual identity reference | `e2df4ed960837cef5c3af52fbd30cf69476d77e064867bbd14c9583b2aae192c` |

## Runtime-Generated Posters

Season posters are not ImageGen outputs. KVsim renders each 1920x1080 poster
locally from the season's event ledger, resident sprites, chronicles,
relationships, lifecycle changes, economy statistics, voting results, and model
usage. This keeps reports reproducible and avoids an image-model call at season
completion.

## External References

The Stanford Generative Agents project and Agent Office informed early product
research only. KVsim does not copy their runtimes, prompts, maps, characters,
or agent systems.
