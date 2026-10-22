"""Test suite for the AI Clinic Operations Assistant.

The suite is deliberately run against a real PostgreSQL database with Row
Level Security enabled, because most of the guarantees this project makes
(tenant isolation, the double-booking constraint, the audit log's
immutability) are database-level guarantees. SQLite or a mocked database
would not exercise them at all.
"""
