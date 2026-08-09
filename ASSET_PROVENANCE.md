# Asset Provenance

KVsim v2 and v2.1 artwork was created specifically for Canadaverse with OpenAI ImageGen
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
| `art/kvsim/town-map-source-v21-spring.png` | 1536x1024 | Geometry-matched spring Lagoon exterior source | 4,239,938 | `216f28aa843250dfa053366e009e4badaf729a7208a6a11bd65506d10bb3e5a4` |
| `art/kvsim/town-map-source-v21-summer.png` | 1536x1024 | Expanded summer map with apartments, commerce, recreation, and civic destinations | 4,153,241 | `1344bc0599b94068046ddd6e7f835558b9fee1f59564d96444dda82facb3a8e0` |
| `art/kvsim/town-map-source-v21-fall.png` | 1536x1024 | Geometry-matched fall Lagoon exterior source | 4,016,298 | `80c306f3c692d419807f73603331b49033e21240ba196c49ae9ff82d91bf4fdc` |
| `art/kvsim/town-map-source-v21-winter.png` | 1536x1024 | Geometry-matched winter Lagoon exterior source | 4,481,637 | `0c508d14ecb34d90647f09fb4bef6a798bc42b470aab1d32ddf99666d646a5bf` |
| `art/kvsim/interiors-source-v4.png` | 1254x1254 | Sixteen additional apartment, shop, recreation, service, and community interiors | 2,294,609 | `ddc8f2b59c3e9ffe318b68d7d45be21c11e733d7e06102c50667305a88f40d2e` |
| `art/kvsim/inventory-source-v2.png` | 1254x1254 | 256 additional food, clothing, home, childcare, electronics, hobby, and service minis | 2,333,665 | `e954f4b62f6674702cd9405f59d44cf789a6993c6e24a41107143f6b834e043b` |
| `art/kvsim/inventory-corrections-source-v21.png` | 1254x1254 | Exact replacements for inventory cells that failed atlas validation | 1,772,767 | `792e32426c7629b71b66f783278ac1f77cd9d3291dc1a92cd88e1632bcbfbc10` |
| `art/kvsim/event-props-source-v21.png` | 1254x1254 | First 64 civic, relationship, weather, work, and discovery frames | 1,857,972 | `7a49ab2573b7a2efa15705311d51c21a5563198f13789a7f7a1c79aaa3c29296` |
| `art/kvsim/event-props-source-v21-extra.png` | 1254x1254 | Second 64 housing, family, economy, services, aging, and repair frames | 2,306,546 | `6edcab10ba412c7e4e396c709b0305a0ddf8cb2d1ca9e0d16697385c57142377` |

## Production Assets

| Asset | Dimensions | Runtime use | Bytes | SHA-256 |
| --- | ---: | --- | ---: | --- |
| `frontend/public/assets/kvsim-town-v21-spring.webp` | 4608x3072 | Seasons 1-5 spring map and building exteriors | 4,709,660 | `4e4a70ed6186e068fcf561ee4fef3331260b6bfa47e23fc1c00f1c3027328acc` |
| `frontend/public/assets/kvsim-town-v21-summer.webp` | 4608x3072 | Seasons 6-10 summer map and building exteriors | 4,192,482 | `27043980168fc3fb96aa5dd47f667836d9a4aeb4bf0c618c3a566cfc08481674` |
| `frontend/public/assets/kvsim-town-v21-fall.webp` | 4608x3072 | Seasons 11-15 fall map and building exteriors | 4,654,918 | `aecdf5ce929fe9dd64c7bf55c1dc3ce07873a827fad5b45858ae4feab85aaca1` |
| `frontend/public/assets/kvsim-town-v21-winter.webp` | 4608x3072 | Seasons 16-20 winter map and building exteriors | 4,787,828 | `cf2acdba0e20a0fab2abb603c4af18e42107cbb2587de7a9f0a7bb32d63796b1` |
| `frontend/public/assets/life-stages-v2.png` | 768x768 | 4x4 lifecycle sprite atlas with 192x192 cells | 415,188 | `c42701fd3098194eb191a2f37f68273348f9a64e036b8f3efd88b1a701c2830d` |
| `frontend/public/assets/interiors-v4.png` | 1792x1536 | Production 7x6 atlas with 41 populated 256x256 interiors | 4,023,550 | `275084c4cbc7f8b82ce8872143d6b42ce0028a4469839363ced98dda9825eb2e` |
| `frontend/public/assets/weather-seasons-v1.png` | 1024x1024 | Production 8x8 weather and four-season atlas with 128x128 cells | 554,145 | `303e3bcaf2a23723b673009437cfd73727eeb2adcb876d1a23009ae9b0b6f88e` |
| `frontend/public/assets/inventory-items-v2.png` | 1536x1216 | Production 24x19 inventory atlas with 452 addressable 64x64 cells | 2,151,063 | `6ebc8ce09abb77605cb12c24c9ea169ce401d2e29c0558b080349a4c7953106d` |
| `frontend/public/assets/event-props-v21.png` | 1024x2048 | Production 8x16 atlas with 128 animated consequence frames | 2,001,329 | `b6884bdb92cc69a5b9bdd2f60f4f509d7eaab81413ea91d0a75782f45562fc47` |

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
