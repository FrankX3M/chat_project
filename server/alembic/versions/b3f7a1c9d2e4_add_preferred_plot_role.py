"""add preferred_plot_role to user_settings

Revision ID: b3f7a1c9d2e4
Revises: 4ece378b27b5
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3f7a1c9d2e4'
down_revision: Union[str, None] = '4ece378b27b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # task190826: критерий "ищу сюжет"/"предлагаю сюжет" для темы "Ролка"
    # (см. app/models/user.py::PlotRole, app/models/user_settings.py).
    plot_role_enum = sa.Enum('seeking_plot', 'offering_plot', name='plot_role')
    plot_role_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'user_settings',
        sa.Column('preferred_plot_role', plot_role_enum, nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_settings', 'preferred_plot_role')
    sa.Enum(name='plot_role').drop(op.get_bind(), checkfirst=True)
