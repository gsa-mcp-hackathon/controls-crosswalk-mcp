"""Loaders turn one raw source file into rows for the store.

Each loader is a pure function of the parsed JSON. It never reads the network
and never writes the database itself; store.py owns the schema and inserts.
"""
