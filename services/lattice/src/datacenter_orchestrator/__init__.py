"""
datacenter_orchestrator

This package is a modular orchestration engine for data center CLOS fabrics.

We keep modules small and well separated:
core contains shared data structures and errors
sources contains ingestion plugins
fabric contains topology and capacity logic
ai contains planner interfaces
executor contains gNMI and rollback plumbing
verify contains post change validation logic
control contains policy gate and reconcile loop
"""
