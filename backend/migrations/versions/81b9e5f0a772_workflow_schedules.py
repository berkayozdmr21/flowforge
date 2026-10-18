"""Persistent workflow schedules and occurrence history."""

from alembic import op
import sqlalchemy as sa

revision = "81b9e5f0a772"
down_revision = "546c31b8b215"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "flow_id", sa.String(), sa.ForeignKey("workflows.id"), nullable=False
        ),
        sa.Column(
            "version_id",
            sa.String(),
            sa.ForeignKey("workflow_versions.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("next_run", sa.Float(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("fired", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("last_run_id", sa.String(), sa.ForeignKey("runs.id")),
        sa.Column("request_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("flow_id", "request_key"),
    )
    op.create_index(
        "ix_workflow_schedules_next_run", "workflow_schedules", ["next_run"]
    )
    op.create_table(
        "schedule_runs",
        sa.Column(
            "schedule_id",
            sa.String(),
            sa.ForeignKey("workflow_schedules.id"),
            primary_key=True,
        ),
        sa.Column("due", sa.Float(), primary_key=True),
        sa.Column(
            "run_id", sa.String(), sa.ForeignKey("runs.id"), nullable=False, unique=True
        ),
    )


def downgrade():
    op.drop_table("schedule_runs")
    op.drop_index("ix_workflow_schedules_next_run", table_name="workflow_schedules")
    op.drop_table("workflow_schedules")
