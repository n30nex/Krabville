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

The `*-source-*.png` files are direct ImageGen 2 outputs. Chroma-key working
files are intentionally excluded from version control. Files under
`frontend/public/assets/` are the browser-ready outputs.

## ImageGen 2 Sources

| Source | Dimensions | Purpose | Bytes | SHA-256 |
| --- | ---: | --- | ---: | --- |
| `art/kvsim/town-map-source-v2.png` | 1536x1024 | Large connected Lagoon town source with homes, civic buildings, workplaces, roads, bridges, and water | 4,190,737 | `b56abf09ab1cf74a7cb7f1c7390e5d3e1090ce20489314eb750ff1df23d1fdbf` |
| `art/kvsim/life-stages-source-v2.png` | 1254x1254 | Baby, child, teen, and senior movement source sheet | 1,640,504 | `e289e30ccbdec200966b2ca992ee792038bedab80b3cd49f531b4172fc574459` |
| `art/kvsim/interiors-source-v2.png` | 1448x1086 | Original twelve-room source sheet | 2,501,023 | `230fd6280cc3d2f8b55dc0d0a9d5553017c438c2c28a86163d1b6298d32d967d` |
| `art/kvsim/interiors-source-v3.png` | 1254x1254 | Twenty-five distinct homes, workplaces, shops, care spaces, and civic interiors | 2,393,858 | `4bf869531f926fc51ba48359cfc126c8903ba58563e5f838d618361e23ea25ac` |
| `art/kvsim/weather-source-v1.png` | 1254x1254 | Sixty-four weather, season, particle, and ground-overlay sprites | 1,522,005 | `64a736e06150d426ec4fe63f8cb605442a9534c9ab86f9bfb2d86793f5da6bb3` |
| `art/kvsim/inventory-source-v1.png` | 1302x1208 | RPG-style everyday goods and possessions icon atlas | 2,209,529 | `ad750179c85b0c4599fd8963c67dfa997c4c3a348f87dbb78116dbefb9d58643` |
| `art/kvsim/inventory-alpha-v1.png` | 896x832 | Mechanically cleaned inventory working sheet retained so atlas normalization is reproducible | 888,901 | `18b5a93b7c11f6de42323d1a1461de248d4a03e4976079277b0c2061f778ee9c` |

## Production Assets

| Asset | Dimensions | Runtime use | Bytes | SHA-256 |
| --- | ---: | --- | ---: | --- |
| `frontend/public/assets/kvsim-town-v2.webp` | 3072x2048 | Pannable production world map | 1,836,176 | `81df5eee659cea0b2cbbde84bee675acba9391445cbb31a647803e7ca55abc97` |
| `frontend/public/assets/life-stages-v2.png` | 768x768 | 4x4 lifecycle sprite atlas with 192x192 cells | 415,188 | `c42701fd3098194eb191a2f37f68273348f9a64e036b8f3efd88b1a701c2830d` |
| `frontend/public/assets/interiors-v2.png` | 1024x768 | Previous 4x3 interior atlas retained for provenance | 1,316,784 | `c9dfffa14d77e8676abf10821848675f9eb23c52b721a9b61eccb02ca0b0aacd` |
| `frontend/public/assets/interiors-v3.png` | 1280x1280 | Production 5x5 atlas with 25 uniquely mapped 256x256 interiors | 2,377,742 | `657dbb21b7dc406aadbcbff073ce3d57711bd1248909afedcd22001c8ba8e9ed` |
| `frontend/public/assets/weather-seasons-v1.png` | 1024x1024 | Production 8x8 weather and four-season atlas with 128x128 cells | 554,145 | `303e3bcaf2a23723b673009437cfd73727eeb2adcb876d1a23009ae9b0b6f88e` |
| `frontend/public/assets/inventory-items-v1.png` | 896x896 | Production 14x14 inventory atlas with 196 semantic 64x64 cells | 817,716 | `70e270942288ff1b330709afbe311b51a7de4b29535ee01167a1f11f26ea6662` |

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
