"""Delete specific test chat messages from a conversation (prod cleanup).

Targets ONLY the QA/test messages pasted on 2026-08-11 (suno / hii / bhai hai
sath kia / zes / i hate you / ok / yes i...), and ONLY inside conversations
where one of the given emails is a participant — a bare "ok" from any other
user can never match.

Usage (dry run first — prints what WOULD be deleted, touches nothing):
    python scripts/delete_chat_messages.py --database-url "<PROD_DATABASE_URL>" --email nadianazar2422@gmail.com

Then delete for real:
    python scripts/delete_chat_messages.py --database-url "<PROD_DATABASE_URL>" --email nadianazar2422@gmail.com --execute

Notes:
- --email may be passed multiple times; matches conversations having ANY of them.
- Deletes dependent rows first (message_reads, message_attachments), then the
  messages themselves. Hard delete.
- The URL must be the asyncpg one (postgresql+asyncpg://...); a plain
  postgresql:// URL is upgraded automatically.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Exact texts of the pasted test messages. Case-insensitive full-string match,
# except the deliberately truncated "yes i..." which is a prefix match.
EXACT = ["ok", "zes", "hii", "suno ?", "suno", "bhai hai sath kia", "i hate you"]
PREFIX = ["yes i"]


def build_where() -> str:
    exact_list = ", ".join(f"lower('{t}')" for t in EXACT)
    prefix_conds = " OR ".join(f"lower(m.content) LIKE lower('{p}%')" for p in PREFIX)
    return f"(lower(trim(m.content)) IN ({exact_list}) OR {prefix_conds})"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--email", action="append", required=True,
                        help="participant email filter (repeatable)")
    parser.add_argument("--execute", action="store_true",
                        help="actually delete (default: dry run)")
    args = parser.parse_args()

    url = args.database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(
        url, poolclass=NullPool,
        connect_args={"statement_cache_size": 0, "ssl": True},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    emails = [e.lower() for e in args.email]
    find_sql = text(f"""
        SELECT m.id, m.conversation_id, m.timestamp, u.email AS sender, m.content
          FROM messages m
          LEFT JOIN users u ON u.id = m.sender_id
         WHERE {build_where()}
           AND m.conversation_id IN (
               SELECT cp.conversation_id
                 FROM conversation_participants cp
                 JOIN users pu ON pu.id = cp.user_id
                WHERE lower(pu.email) = ANY(:emails)
           )
         ORDER BY m.timestamp
    """)

    async with session_factory() as db:
        rows = (await db.execute(find_sql, {"emails": emails})).fetchall()
        if not rows:
            print("No matching messages found. Nothing to do.")
            return

        print(f"{'WILL DELETE' if args.execute else 'DRY RUN — would delete'} {len(rows)} message(s):")
        for r in rows:
            print(f"  {r.id} | conv={r.conversation_id} | {r.sender} | {str(r.timestamp)[:16]} | {r.content[:60]!r}")

        if not args.execute:
            print("\nRe-run with --execute to delete these rows.")
            return

        ids = [r.id for r in rows]
        deleted_reads = (await db.execute(
            text("DELETE FROM message_reads WHERE message_id = ANY(:ids) RETURNING id"),
            {"ids": ids})).fetchall()
        deleted_atts = (await db.execute(
            text("DELETE FROM message_attachments WHERE message_id = ANY(:ids) RETURNING id"),
            {"ids": ids})).fetchall()
        deleted_msgs = (await db.execute(
            text("DELETE FROM messages WHERE id = ANY(:ids) RETURNING id"),
            {"ids": ids})).fetchall()
        await db.commit()
        print(f"\nDeleted: {len(deleted_msgs)} messages, "
              f"{len(deleted_reads)} read-receipts, {len(deleted_atts)} attachments.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
