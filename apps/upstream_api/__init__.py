"""Isolated upstream read API surface (design D1).

The app owns the machine-authenticated ``/api/v1/`` routes, the Bearer
authentication helper, the JSON error envelope and the sanitized access
logging, so portal session auth and clinical apps stay untouched.
"""
