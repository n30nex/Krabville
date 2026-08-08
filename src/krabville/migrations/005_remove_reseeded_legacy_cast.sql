-- Old v2 runtimes seeded the legacy demo cast again whenever a process opened
-- the database. Remove only unreferenced legacy rows when a v2 cast exists.
DELETE FROM residents
WHERE id IN (
    SELECT legacy.resident_id
    FROM resident_identities AS legacy
    WHERE legacy.generation_seed LIKE 'legacy:%'
      AND EXISTS (
          SELECT 1 FROM resident_identities AS current
          WHERE current.generation_seed LIKE 'v2:%'
      )
      AND NOT EXISTS (
          SELECT 1 FROM resident_state AS state
          WHERE state.resident_id = legacy.resident_id
      )
      AND NOT EXISTS (
          SELECT 1 FROM household_members AS member
          WHERE member.resident_id = legacy.resident_id
      )
);
