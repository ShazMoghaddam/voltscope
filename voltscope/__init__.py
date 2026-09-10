"""Voltscope: structured extraction and validation for UK commercial energy bills.

The bill-intelligence module of VoltEdge. Point it at a folder of supplier
bills (PDFs or images); it extracts a fixed JSON schema via Claude, runs
deterministic validation checks, and writes one JSON file per bill.
"""

__version__ = "0.1.0"
