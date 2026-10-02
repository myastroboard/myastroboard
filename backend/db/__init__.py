"""SQLite storage for MyAstroBoard's persistent state (users, per-user documents, settings).

Shared infrastructure: feature packages import ``db``; ``db`` never imports a feature
package at module level (the legacy JSON importer reaches them lazily, inside functions).
"""
