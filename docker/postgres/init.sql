-- Runs once, when the data volume is first initialised.
-- The dev database `todolist` is created from POSTGRES_DB; tests use their own database.
CREATE DATABASE todolist_test OWNER todolist;
