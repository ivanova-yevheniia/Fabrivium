"""Outbound integrations with external engineering tools.

Everything here is DOWNSTREAM of the Fabrivium domain and simulation. No
module in this package may be imported by app.services or app.models — the
dependency runs one way only, so a vendor's assumptions can never reach the
engineering core.
"""
