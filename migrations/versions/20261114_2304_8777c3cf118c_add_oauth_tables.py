"""add oauth tables

Revision ID: 8777c3cf118c
Revises: b82bcf0756e0
Create Date: 2026-11-14 23:04:43.995004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8777c3cf118c"
down_revision: str | Sequence[str] | None = "b82bcf0756e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=64), nullable=True),
        sa.Column("redirect_uris", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=True),
        sa.Column("grant_types", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("client_id", name=op.f("pk_oauth_clients")),
    )
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_oauth_authorization_codes_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("fk_oauth_authorization_codes_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_authorization_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_authorization_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_oauth_authorization_codes_code_hash")),
    )
    op.create_index(
        op.f("ix_oauth_authorization_codes_agent_id"),
        "oauth_authorization_codes",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_authorization_codes_client_id"),
        "oauth_authorization_codes",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_authorization_codes_user_id"),
        "oauth_authorization_codes",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "oauth_access_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorization_code_id", sa.Uuid(), nullable=True),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_oauth_access_tokens_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["authorization_code_id"],
            ["oauth_authorization_codes.id"],
            name=op.f("fk_oauth_access_tokens_authorization_code_id_oauth_authorization_codes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("fk_oauth_access_tokens_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_access_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_access_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_access_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_oauth_access_tokens_agent_id"), "oauth_access_tokens", ["agent_id"], unique=False
    )
    op.create_index(
        op.f("ix_oauth_access_tokens_authorization_code_id"),
        "oauth_access_tokens",
        ["authorization_code_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_access_tokens_client_id"), "oauth_access_tokens", ["client_id"], unique=False
    )
    op.create_index(
        op.f("ix_oauth_access_tokens_user_id"), "oauth_access_tokens", ["user_id"], unique=False
    )
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorization_code_id", sa.Uuid(), nullable=True),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_oauth_refresh_tokens_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["authorization_code_id"],
            ["oauth_authorization_codes.id"],
            name=op.f("fk_oauth_refresh_tokens_authorization_code_id_oauth_authorization_codes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("fk_oauth_refresh_tokens_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_oauth_refresh_tokens_agent_id"), "oauth_refresh_tokens", ["agent_id"], unique=False
    )
    op.create_index(
        op.f("ix_oauth_refresh_tokens_authorization_code_id"),
        "oauth_refresh_tokens",
        ["authorization_code_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_refresh_tokens_client_id"),
        "oauth_refresh_tokens",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_refresh_tokens_user_id"), "oauth_refresh_tokens", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_refresh_tokens_user_id"), table_name="oauth_refresh_tokens")
    op.drop_index(op.f("ix_oauth_refresh_tokens_client_id"), table_name="oauth_refresh_tokens")
    op.drop_index(
        op.f("ix_oauth_refresh_tokens_authorization_code_id"), table_name="oauth_refresh_tokens"
    )
    op.drop_index(op.f("ix_oauth_refresh_tokens_agent_id"), table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_index(op.f("ix_oauth_access_tokens_user_id"), table_name="oauth_access_tokens")
    op.drop_index(op.f("ix_oauth_access_tokens_client_id"), table_name="oauth_access_tokens")
    op.drop_index(
        op.f("ix_oauth_access_tokens_authorization_code_id"), table_name="oauth_access_tokens"
    )
    op.drop_index(op.f("ix_oauth_access_tokens_agent_id"), table_name="oauth_access_tokens")
    op.drop_table("oauth_access_tokens")
    op.drop_index(
        op.f("ix_oauth_authorization_codes_user_id"), table_name="oauth_authorization_codes"
    )
    op.drop_index(
        op.f("ix_oauth_authorization_codes_client_id"), table_name="oauth_authorization_codes"
    )
    op.drop_index(
        op.f("ix_oauth_authorization_codes_agent_id"), table_name="oauth_authorization_codes"
    )
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_clients")
