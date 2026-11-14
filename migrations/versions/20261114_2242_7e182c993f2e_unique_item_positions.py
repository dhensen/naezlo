"""unique item positions

Revision ID: 7e182c993f2e
Revises: 4ae9a5e8e1d8
Create Date: 2026-11-14 22:42:00.851861
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7e182c993f2e"
down_revision: str | Sequence[str] | None = "4ae9a5e8e1d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deleting an item used to leave a gap: renumber every list 1, 2, 3, ... in its order.
    op.execute(
        """
        UPDATE items SET position = numbered.position
        FROM (
            SELECT id, row_number() OVER (PARTITION BY list_id ORDER BY position, id) AS position
            FROM items
        ) AS numbered
        WHERE items.id = numbered.id AND items.position <> numbered.position
        """
    )
    op.drop_index(op.f("ix_items_list_id_position"), table_name="items")
    op.create_unique_constraint(
        op.f("uq_items_list_id_position"),
        "items",
        ["list_id", "position"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_items_list_id_position"), "items", type_="unique")
    op.create_index(
        op.f("ix_items_list_id_position"), "items", ["list_id", "position"], unique=False
    )
