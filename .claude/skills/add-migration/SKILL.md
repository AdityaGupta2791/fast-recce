---
name: add-migration
description: Generate an Alembic database migration from current SQLAlchemy model changes. Validates the migration before finalizing. Use when the user says "/add-migration" or asks to create a database migration, apply schema changes, or add a new table/column.
---

# /add-migration — FastRecce Alembic Migration Generator

Generates a new Alembic migration that captures pending schema changes (new tables, altered columns, added indexes). Runs `autogenerate` and validates the output before applying.

## When to Use

Invoke this skill when the user:
- Says `/add-migration <description>` (e.g. `/add-migration add sources table`)
- Asks to "create a migration" or "generate a migration"
- Just added or modified a SQLAlchemy model and needs a DB migration

## Arguments

- **description** (required): short human-readable description of the change. Will become part of the migration filename. Examples: `"add sources table"`, `"add email_verified to users"`.

## Prerequisites

Before running, verify:
1. `backend/.env` exists and has a valid `DATABASE_URL`
2. PostgreSQL is running (`docker-compose up -d postgres`)
3. The new/modified model is imported in `backend/alembic/env.py`
4. All prior migrations have been applied (`alembic current`)

If any prerequisite is missing, report the issue to the user and stop.

## Process

1. **Check model imports in `alembic/env.py`.** Every model file in `app/models/` must be imported so `autogenerate` can see them. If a new model file exists but isn't imported, add the import.

2. **Run autogenerate:**
   ```bash
   cd backend && alembic revision --autogenerate -m "<description>"
   ```

3. **Read the generated migration file** from `backend/alembic/versions/`. Inspect the `upgrade()` and `downgrade()` functions.

4. **Validate:**
   - No unexpected DROP statements (would indicate missing model imports)
   - Enum/CHECK constraints use the patterns from `docs/database-schema.md`
   - Indexes match the ones specified in the schema doc
   - PostGIS geometry columns use `Geography(geometry_type='POINT', srid=4326)`

5. **Report** the generated file path and the summary of changes (tables added, columns added, indexes created) to the user.

6. **Ask the user** whether to apply the migration now:
   - If yes: run `alembic upgrade head` and confirm success.
   - If no: leave the migration file for review.

## Common Pitfalls

- **"Target database is not up to date":** Run `alembic upgrade head` before creating a new migration.
- **Empty migration:** Usually means the model wasn't imported in `env.py`.
- **Autogenerate missed an index:** Add it manually to the migration file. Autogenerate has known limits on partial and GIST indexes.
- **PostGIS types show as `Geometry` instead of `Geography`:** Override manually in the migration — autogenerate doesn't always detect the distinction.

## Example Invocation

User: `/add-migration add sources table`