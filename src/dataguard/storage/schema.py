"""Normalized SQLAlchemy audit schema shared by SQLite and PostgreSQL."""

from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, MetaData, String, Table

metadata = MetaData()

audit_events = Table(
    "audit_events", metadata,
    Column("event_id", String(36), primary_key=True),
    Column("event_type", String(40), nullable=False),
    Column("occurred_at", String(32), nullable=False),
    Column("trace_id", String(36)), Column("run_id", String(36)),
    Column("subject_id", String(128)), Column("resolved_role", String(32)),
    Column("mode", String(16)), Column("outcome", String(16), nullable=False),
    Column("corpus_version", String(64)),
    Column("retrieved_document_count", Integer, nullable=False),
    Column("unauthorized_context_count", Integer, nullable=False),
    Column("canary_match_count", Integer, nullable=False),
    Column("protected_fragment_match_count", Integer, nullable=False),
    Column("detector_action", String(16), nullable=False),
    Column("error_code", String(64)),
)
Index("ix_audit_events_order", audit_events.c.occurred_at, audit_events.c.event_id)
for column_name in ("trace_id", "run_id", "subject_id", "mode", "event_type"):
    Index(f"ix_audit_events_{column_name}", audit_events.c[column_name])

audit_retrieved_documents = Table(
    "audit_retrieved_documents", metadata,
    Column("event_id", String(36), ForeignKey("audit_events.event_id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, primary_key=True), Column("document_id", String(128), nullable=False),
    Column("rank", Integer, nullable=False), Column("similarity_score", Float, nullable=False),
    Column("authorized", Boolean, nullable=False), Column("included_in_context", Boolean, nullable=False),
    Column("denial_reason", String(32)),
)
audit_authorization_denials = Table(
    "audit_authorization_denials", metadata,
    Column("event_id", String(36), ForeignKey("audit_events.event_id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, primary_key=True), Column("document_id", String(128), nullable=False),
    Column("reason", String(32), nullable=False),
)
audit_detections = Table(
    "audit_detections", metadata,
    Column("event_id", String(36), ForeignKey("audit_events.event_id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, primary_key=True), Column("type", String(48), nullable=False),
    Column("evidence_id", String(128), nullable=False), Column("violation", Boolean, nullable=False),
    Column("action", String(16), nullable=False),
)
