-- Runs once, when the data volume is first initialised.
-- The dev database `todolist` is created from POSTGRES_DB; the tests (pytest) and the
-- browser tests (Playwright) each use their own database.
CREATE DATABASE todolist_test OWNER todolist;
CREATE DATABASE todolist_e2e OWNER todolist;
