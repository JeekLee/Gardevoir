"""Declarative base for ClickHouse models."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class CHBase(DeclarativeBase):
    metadata = MetaData()


__all__ = ["CHBase"]
