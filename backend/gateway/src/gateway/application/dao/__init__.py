"""Read interfaces.

A Dao returns Result DTOs, never domain aggregates. Its queries may join, project
and aggregate freely — that freedom is the point of keeping it away from the
Repository (§5).
"""
