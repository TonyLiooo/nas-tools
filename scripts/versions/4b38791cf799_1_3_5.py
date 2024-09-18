"""1.3.5

Revision ID: 4b38791cf799
Revises: 7480d259772e
Create Date: 2024-09-13 18:26:46.217717

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4b38791cf799'
down_revision = '7480d259772e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    try:
        with op.batch_alter_table("CONFIG_SITE") as batch_op:
            batch_op.add_column(sa.Column('LOCALSTORAGE', sa.Text, nullable=True))
    except Exception as e:
        pass


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('CONFIG_SITE', 'LOCALSTORAGE')
    # ### end Alembic commands ###
