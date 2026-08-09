# Migration bootstrap

`migrate` is the only Compose service that may change the database schema or
run bootstrap seeding. It runs `krabville-manage bootstrap` once and has no
restart policy. `web`, `engine`, and `inference` require it to exit successfully
before they start.

Normal API, engine, inference, and management startup only validates the
required schema and SHA-256 checksums. It never applies a pending migration.
For local development outside Compose, run the explicit command first:

```bash
krabville-manage bootstrap
```

`krabville-manage init` remains an alias for existing local scripts.

Each migration and its `schema_migrations` row are committed in one SQLite
transaction. Migration `015` pins checksums for the pre-checksum history;
later migrations record their checksum when applied. Never edit an applied SQL
file. Add the next numbered migration instead.

On failure, Compose does not start dependent services and leaves the migration
container exited non-zero. Inspect the exact error with:

```bash
docker compose --env-file deploy/.env ps -a migrate
docker compose --env-file deploy/.env logs migrate
```

A checksum mismatch requires restoring the applied SQL file byte-for-byte. An
unapplied migration that failed can be corrected and the normal Compose start
retried; statements from that failed file are rolled back.
