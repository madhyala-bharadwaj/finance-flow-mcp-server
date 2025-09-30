from fastmcp import FastMCP
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

# Define paths relative to the script's location
DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

# Create an instance of FastMCP server
server = FastMCP(name="Finance Flow")


def _get_account_id_from_name(conn: sqlite3.Connection, name: str) -> Optional[int]:
    """
    Retrieves the ID of an account from the database using its name.
    The lookup is case-insensitive.

    Args:
        conn: The active sqlite3 database connection.
        name: The name of the account to find.

    Returns:
        The integer ID of the account if found, otherwise None.
    """
    cursor = conn.execute(
        "SELECT id FROM accounts WHERE name = ? COLLATE NOCASE", (name,)
    )
    result = cursor.fetchone()
    return result[0] if result else None


def _calculate_next_date(last_date_str: str, frequency: str) -> str:
    """
    Calculates the next due date for a recurring transaction based on its
    last due date and frequency.

    Args:
        last_date_str: The last due date in 'YYYY-MM-DD' format.
        frequency: The frequency of the transaction ('monthly' or 'weekly').

    Returns:
        The next due date in 'DD-MM-YYYY' format.
    """
    last_date = datetime.strptime(last_date_str, "%d-%m-%Y")
    if frequency == "monthly":
        year, month = (
            (last_date.year, last_date.month + 1)
            if last_date.month < 12
            else (last_date.year + 1, 1)
        )
        next_month_first_day = datetime(year, month, 1)
        # A robust way to get the last day of the next month
        next_month_last_day = (
            next_month_first_day.replace(day=28) + timedelta(days=4)
        ).replace(day=1) - timedelta(days=1)
        target_day = min(last_date.day, next_month_last_day.day)
        return datetime(year, month, target_day).strftime("%d-%m-%Y")
    elif frequency == "weekly":
        return (last_date + timedelta(days=7)).strftime("%d-%m-%Y")
    return ""


def _internal_add_expense(
    c: sqlite3.Connection,
    date: str,
    amount: float,
    category: str,
    account_id: int,
    subcategory: str = "",
    note: str = "",
) -> int:
    """
    Core logic to insert an expense record and update the corresponding account balance.
    This function assumes it is called within an active database transaction.

    Args:
        c: The active sqlite3 database connection.
        date: The date of the expense.
        amount: The monetary value of the expense.
        category: The primary category of the expense.
        account_id: The ID of the account from which the expense was made.
        subcategory: An optional, more detailed category.
        note: An optional note for the expense.

    Returns:
        The ID of the newly inserted expense record.
    """
    cur = c.execute(
        "INSERT INTO expenses (date, amount, category, subcategory, note, account_id) VALUES (?, ?, ?, ?, ?, ?)",
        (date, amount, category, subcategory, note, account_id),
    )
    c.execute(
        "UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, account_id)
    )
    return cur.lastrowid


def _internal_add_income(
    c: sqlite3.Connection,
    date: str,
    amount: float,
    source: str,
    account_id: int,
    note: str = "",
) -> int:
    """
    Core logic to insert an income record and update the corresponding account balance.
    This function assumes it is called within an active database transaction.

    Args:
        c: The active sqlite3 database connection.
        date: The date the income was received.
        amount: The monetary value of the income.
        source: The source of the income (e.g., 'Salary', 'Freelance').
        account_id: The ID of the account to which the income was added.
        note: An optional note for the income.

    Returns:
        The ID of the newly inserted income record.
    """
    cur = c.execute(
        "INSERT INTO income (date, amount, source, note, account_id) VALUES (?, ?, ?, ?, ?)",
        (date, amount, source, note, account_id),
    )
    c.execute(
        "UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, account_id)
    )
    return cur.lastrowid


def init_database():
    """
    Initializes the database by creating all required tables if they do not exist.
    This function is idempotent and safe to run on every startup.
    """
    with sqlite3.connect(DB_PATH) as c:
        # Enable foreign key support
        c.execute("PRAGMA foreign_keys = ON;")

        # Accounts table
        c.execute("""
            CREATE TABLE IF NOT EXISTS accounts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                type TEXT NOT NULL, -- e.g., 'Bank', 'Cash', 'Credit Card'
                balance REAL NOT NULL DEFAULT 0.0
            )
        """)

        # Expenses table
        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT '',
                account_id INTEGER,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)

        # Income table
        c.execute("""
            CREATE TABLE IF NOT EXISTS income(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                source TEXT NOT NULL,
                note TEXT DEFAULT '',
                account_id INTEGER,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)

        # Budgets table
        c.execute("""
            CREATE TABLE IF NOT EXISTS budgets(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                month_year TEXT NOT NULL, -- Format: YYYY-MM
                UNIQUE(category, month_year)
            )
        """)

        # Recurring Transactions table
        c.execute("""
            CREATE TABLE IF NOT EXISTS recurring_transactions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL, -- 'expense' or 'income'
                amount REAL NOT NULL,
                category_or_source TEXT NOT NULL,
                frequency TEXT NOT NULL,
                next_due_date TEXT NOT NULL,
                note TEXT DEFAULT '',
                subcategory TEXT DEFAULT '',
                account_id INTEGER,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)


init_database()


# --- Account Management Tools ---


@server.tool
def add_account(name: str, account_type: str, initial_balance: float = 0.0) -> dict:
    """
    Adds a new financial account (e.g., Bank, Cash, Credit Card).
    Account names are unique and case-insensitive.

    Args:
        name: The name for the new account (e.g., 'SBI Bank').
        account_type: The type of account (e.g., 'Bank', 'Credit Card', 'Cash').
        initial_balance: The starting balance for the account. Defaults to 0.0.

    Returns:
        A dictionary with the status and ID of the new account, or an error message.
    """
    with sqlite3.connect(DB_PATH) as c:
        try:
            cur = c.execute(
                "INSERT INTO accounts (name, type, balance) VALUES (?, ?, ?)",
                (name, account_type, initial_balance),
            )
            return {"status": "OK", "id": cur.lastrowid}
        except sqlite3.IntegrityError:
            return {
                "status": "Error",
                "message": "An account with that name already exists.",
            }


@server.tool
def list_accounts() -> list[dict]:
    """
    Lists all financial accounts and their current balances, ordered by name.

    Returns:
        A list of dictionaries, where each dictionary represents an account.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute("SELECT * FROM accounts ORDER BY name ASC")
        return [dict(row) for row in cur.fetchall()]


@server.tool
def update_account_name(old_name: str, new_name: str) -> dict:
    """
    Renames an existing financial account.

    Args:
        old_name: The current name of the account to be renamed.
        new_name: The new name for the account.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        try:
            cur = c.execute(
                "UPDATE accounts SET name = ? WHERE name = ? COLLATE NOCASE",
                (new_name, old_name),
            )
            if cur.rowcount == 0:
                return {
                    "status": "Error",
                    "message": f"Account '{old_name}' not found.",
                }
            return {"status": "OK"}
        except sqlite3.IntegrityError:
            return {
                "status": "Error",
                "message": f"An account named '{new_name}' already exists.",
            }


@server.tool
def delete_account(account_name: str) -> dict:
    """
    Deletes an account, but only if it has no transactions (expenses or income) linked to it.

    Args:
        account_name: The name of the account to delete.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        account_id = _get_account_id_from_name(c, account_name)
        if not account_id:
            return {
                "status": "Error",
                "message": f"Account '{account_name}' not found.",
            }
        if (
            c.execute(
                "SELECT COUNT(*) FROM expenses WHERE account_id = ?", (account_id,)
            ).fetchone()[0]
            > 0
        ):
            return {
                "status": "Error",
                "message": "Account has expenses linked and cannot be deleted.",
            }
        if (
            c.execute(
                "SELECT COUNT(*) FROM income WHERE account_id = ?", (account_id,)
            ).fetchone()[0]
            > 0
        ):
            return {
                "status": "Error",
                "message": "Account has income linked and cannot be deleted.",
            }
        c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        return {"status": "OK"}


@server.tool
def transfer_funds(
    from_account_name: str, to_account_name: str, amount: float, date: str
) -> dict:
    """
    Transfers funds between two accounts. This is recorded as a linked pair of
    an expense from the source account and an income to the destination account.

    Args:
        from_account_name: The name of the account to transfer money from.
        to_account_name: The name of the account to transfer money to.
        amount: The amount of money to transfer.
        date: The date of the transfer in 'YYYY-MM-DD' format.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        from_id = _get_account_id_from_name(c, from_account_name)
        to_id = _get_account_id_from_name(c, to_account_name)
        if not from_id or not to_id:
            return {"status": "Error", "message": "One or both accounts not found."}
        c.execute("BEGIN TRANSACTION;")
        try:
            c.execute(
                "INSERT INTO expenses (date, amount, category, subcategory, note, account_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    date,
                    amount,
                    "finance_fees",
                    "internal_transfer",
                    f"Transfer to {to_account_name}",
                    from_id,
                ),
            )
            c.execute(
                "UPDATE accounts SET balance = balance - ? WHERE id = ?",
                (amount, from_id),
            )
            c.execute(
                "INSERT INTO income (date, amount, source, note, account_id) VALUES (?, ?, ?, ?, ?)",
                (
                    date,
                    amount,
                    "internal_transfer",
                    f"Transfer from {from_account_name}",
                    to_id,
                ),
            )
            c.execute(
                "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                (amount, to_id),
            )
            c.execute("COMMIT;")
            return {"status": "OK"}
        except Exception as e:
            c.execute("ROLLBACK;")
            return {"status": "Error", "message": str(e)}


# --- Expense Management Tools ---


@server.tool
def add_expense(
    date: str,
    amount: float,
    category: str,
    account_name: str,
    subcategory: str = "",
    note: str = "",
) -> dict:
    """
    Adds a new expense entry and updates the corresponding account balance.

    Args:
        date: The date of the expense in 'YYYY-MM-DD' format.
        amount: The monetary value of the expense.
        category: The primary category of the expense.
        account_name: The name of the account from which the expense was made.
        subcategory: An optional, more detailed category.
        note: An optional note for the expense.

    Returns:
        A dictionary with the status and ID of the new expense, or an error message.
    """
    with sqlite3.connect(DB_PATH) as c:
        account_id = _get_account_id_from_name(c, account_name)
        if not account_id:
            return {
                "status": "Error",
                "message": f"Account '{account_name}' not found.",
            }
        c.execute("BEGIN TRANSACTION;")
        try:
            cur = c.execute(
                "INSERT INTO expenses (date, amount, category, subcategory, note, account_id) VALUES (?, ?, ?, ?, ?, ?)",
                (date, amount, category, subcategory, note, account_id),
            )
            c.execute(
                "UPDATE accounts SET balance = balance - ? WHERE id = ?",
                (amount, account_id),
            )
            c.execute("COMMIT;")
            return {"status": "OK", "id": cur.lastrowid}
        except Exception as e:
            c.execute("ROLLBACK;")
            return {"status": "Error", "message": str(e)}


@server.tool
def list_expenses(start_date: str, end_date: str) -> list[dict]:
    """
    Lists all expense entries within an inclusive date range.

    Args:
        start_date: The start of the date range in 'YYYY-MM-DD' format.
        end_date: The end of the date range in 'YYYY-MM-DD' format.

    Returns:
        A list of dictionaries, where each dictionary represents an expense.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            """
            SELECT e.*, a.name as account_name FROM expenses e
            LEFT JOIN accounts a ON e.account_id = a.id
            WHERE e.date BETWEEN ? AND ?
            ORDER BY e.date ASC, e.id ASC
            """,
            (start_date, end_date),
        )
        return [dict(row) for row in cur.fetchall()]


@server.tool
def update_expense(
    expense_id: int,
    date: Optional[str] = None,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    note: Optional[str] = None,
    account_name: Optional[str] = None,
) -> dict:
    """
    Updates one or more fields of an existing expense entry.
    This operation is transactional and correctly adjusts account balances.

    Args:
        expense_id: The ID of the expense to update.
        date: The new date for the expense.
        amount: The new amount for the expense.
        category: The new category for the expense.
        subcategory: The new subcategory for the expense.
        note: The new note for the expense.
        account_name: The new account name for the expense.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        original = c.execute(
            "SELECT amount, account_id FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        if not original:
            return {"status": "Error", "message": "Expense not found."}

        updates = {}
        if date is not None:
            updates["date"] = date
        if amount is not None:
            updates["amount"] = amount
        if category is not None:
            updates["category"] = category
        if subcategory is not None:
            updates["subcategory"] = subcategory
        if note is not None:
            updates["note"] = note
        if account_name is not None:
            new_account_id = _get_account_id_from_name(c, account_name)
            if not new_account_id:
                return {
                    "status": "Error",
                    "message": f"Account '{account_name}' not found.",
                }
            updates["account_id"] = new_account_id

        if not updates:
            return {"status": "Error", "message": "No fields to update provided."}

        c.execute("BEGIN TRANSACTION;")
        try:
            c.execute(
                "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                (original["amount"], original["account_id"]),
            )

            set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
            params = list(updates.values()) + [expense_id]
            c.execute(f"UPDATE expenses SET {set_clause} WHERE id = ?", params)

            new_amount = updates.get("amount", original["amount"])
            new_account_id = updates.get("account_id", original["account_id"])
            c.execute(
                "UPDATE accounts SET balance = balance - ? WHERE id = ?",
                (new_amount, new_account_id),
            )

            c.execute("COMMIT;")
            return {"status": "OK"}
        except Exception as e:
            c.execute("ROLLBACK;")
            return {"status": "Error", "message": str(e)}


@server.tool
def delete_expense(expense_id: int) -> dict:
    """
    Deletes an expense entry and correctly adjusts the associated account balance.

    Args:
        expense_id: The ID of the expense to delete.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        original = c.execute(
            "SELECT amount, account_id FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        if not original:
            return {"status": "Error", "message": "Expense not found."}
        c.execute("BEGIN TRANSACTION;")
        try:
            c.execute(
                "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                (original["amount"], original["account_id"]),
            )
            c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
            c.execute("COMMIT;")
            return {"status": "OK"}
        except Exception as e:
            c.execute("ROLLBACK;")
            return {"status": "Error", "message": str(e)}


# --- Income Management Tools ---


@server.tool
def add_income(
    date: str, amount: float, source: str, account_name: str, note: str = ""
) -> dict:
    """
    Adds a new income entry and updates the corresponding account balance.

    Args:
        date: The date the income was received in 'YYYY-MM-DD' format.
        amount: The monetary value of the income.
        source: The source of the income (e.g., 'Salary', 'Freelance').
        account_name: The name of the account to which the income was added.
        note: An optional note for the income.

    Returns:
        A dictionary with the status and ID of the new income record, or an error message.
    """
    with sqlite3.connect(DB_PATH) as c:
        account_id = _get_account_id_from_name(c, account_name)
        if not account_id:
            return {
                "status": "Error",
                "message": f"Account '{account_name}' not found.",
            }
        c.execute("BEGIN TRANSACTION;")
        try:
            cur = c.execute(
                "INSERT INTO income (date, amount, source, note, account_id) VALUES (?, ?, ?, ?, ?)",
                (date, amount, source, note, account_id),
            )
            income_id = cur.lastrowid
            c.execute(
                "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                (amount, account_id),
            )
            c.execute("COMMIT;")
            return {"status": "OK", "id": income_id}
        except Exception as e:
            c.execute("ROLLBACK;")
            return {"status": "Error", "message": f"Transaction failed: {e}"}


@server.tool
def list_income(start_date: str, end_date: str) -> list[dict]:
    """
    Lists all income entries within an inclusive date range.

    Args:
        start_date: The start of the date range in 'YYYY-MM-DD' format.
        end_date: The end of the date range in 'YYYY-MM-DD' format.

    Returns:
        A list of dictionaries, where each dictionary represents an income record.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            """
            SELECT i.*, a.name as account_name FROM income i
            LEFT JOIN accounts a ON i.account_id = a.id
            WHERE i.date BETWEEN ? AND ?
            ORDER BY i.date ASC, i.id ASC
            """,
            (start_date, end_date),
        )
        return [dict(row) for row in cur.fetchall()]


@server.tool
def update_income(
    income_id: int,
    date: Optional[str] = None,
    amount: Optional[float] = None,
    source: Optional[str] = None,
    note: Optional[str] = None,
    account_name: Optional[str] = None,
) -> dict:
    """
    Updates one or more fields of an existing income entry.
    This operation is transactional and correctly adjusts account balances.

    Args:
        income_id: The ID of the income record to update.
        date: The new date for the income.
        amount: The new amount for the income.
        source: The new source for the income.
        note: The new note for the income.
        account_name: The new account name for the income.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        original = c.execute(
            "SELECT amount, account_id FROM income WHERE id = ?", (income_id,)
        ).fetchone()
        if not original:
            return {"status": "Error", "message": "Income record not found."}

        updates = {}
        if date is not None:
            updates["date"] = date
        if amount is not None:
            updates["amount"] = amount
        if source is not None:
            updates["source"] = source
        if note is not None:
            updates["note"] = note
        if account_name is not None:
            new_account_id = _get_account_id_from_name(c, account_name)
            if not new_account_id:
                return {
                    "status": "Error",
                    "message": f"Account '{account_name}' not found.",
                }
            updates["account_id"] = new_account_id

        if not updates:
            return {"status": "Error", "message": "No fields to update provided."}

        c.execute("BEGIN TRANSACTION;")
        try:
            # Revert the original transaction's effect on the balance
            c.execute(
                "UPDATE accounts SET balance = balance - ? WHERE id = ?",
                (original["amount"], original["account_id"]),
            )

            # Update the income record
            set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
            params = list(updates.values()) + [income_id]
            c.execute(f"UPDATE income SET {set_clause} WHERE id = ?", params)

            # Apply the new transaction's effect on the balance
            new_amount = updates.get("amount", original["amount"])
            new_account_id = updates.get("account_id", original["account_id"])
            c.execute(
                "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                (new_amount, new_account_id),
            )

            c.execute("COMMIT;")
            return {"status": "OK"}
        except Exception as e:
            c.execute("ROLLBACK;")
            return {"status": "Error", "message": str(e)}


@server.tool
def delete_income(income_id: int) -> dict:
    """
    Deletes an income entry and correctly adjusts the associated account balance.

    Args:
        income_id: The ID of the income record to delete.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        income = c.execute(
            "SELECT amount, account_id FROM income WHERE id = ?", (income_id,)
        ).fetchone()
        if not income:
            return {
                "status": "Error",
                "message": f"Income with ID {income_id} not found.",
            }
        c.execute("BEGIN TRANSACTION;")
        try:
            c.execute(
                "UPDATE accounts SET balance = balance - ? WHERE id = ?",
                (income["amount"], income["account_id"]),
            )
            c.execute("DELETE FROM income WHERE id = ?", (income_id,))
            c.execute("COMMIT;")
            return {"status": "OK", "message": f"Income ID {income_id} deleted."}
        except Exception as e:
            c.execute("ROLLBACK;")
            return {"status": "Error", "message": f"Delete failed: {e}"}


@server.tool
def search_transactions(keyword: str, start_date: str, end_date: str) -> dict:
    """
    Searches for a keyword in the 'note' field of both expenses and income
    within an inclusive date range.

    Args:
        keyword: The text to search for.
        start_date: The start of the date range in 'YYYY-MM-DD' format.
        end_date: The end of the date range in 'YYYY-MM-DD' format.

    Returns:
        A dictionary containing two lists: 'expenses' and 'income' with matching records.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        like_pattern = f"%{keyword}%"
        expenses = [
            dict(r)
            for r in c.execute(
                "SELECT e.*, a.name as account_name FROM expenses e JOIN accounts a ON e.account_id = a.id WHERE e.note LIKE ? AND e.date BETWEEN ? AND ?",
                (like_pattern, start_date, end_date),
            )
        ]
        income = [
            dict(r)
            for r in c.execute(
                "SELECT i.*, a.name as account_name FROM income i JOIN accounts a ON i.account_id = a.id WHERE i.note LIKE ? AND i.date BETWEEN ? AND ?",
                (like_pattern, start_date, end_date),
            )
        ]
        return {"expenses": expenses, "income": income}


# --- Recurring Transactions Tools ---


@server.tool
def add_recurring_transaction(
    type: str,
    amount: float,
    category_or_source: str,
    frequency: str,
    start_date: str,
    account_name: str,
    note: str = "",
    subcategory: str = "",
) -> dict:
    """
    Adds a recurring transaction (either 'expense' or 'income') to be processed later.

    Args:
        type: The type of transaction ('expense' or 'income').
        amount: The amount of the transaction.
        category_or_source: The category (for expense) or source (for income).
        frequency: The frequency ('monthly' or 'weekly').
        start_date: The first date the transaction is due, in 'YYYY-MM-DD' format.
        account_name: The name of the account associated with this transaction.
        note: An optional note.
        subcategory: An optional subcategory (for expenses).

    Returns:
        A dictionary with the status and ID of the new recurring transaction.
    """
    if type not in ["expense", "income"]:
        return {"status": "Error", "message": "Type must be 'expense' or 'income'."}
    if frequency not in ["monthly", "weekly"]:
        return {
            "status": "Error",
            "message": "Frequency must be 'monthly' or 'weekly'.",
        }
    with sqlite3.connect(DB_PATH) as c:
        account_id = _get_account_id_from_name(c, account_name)
        if not account_id:
            return {
                "status": "Error",
                "message": f"Account '{account_name}' not found.",
            }
        cur = c.execute(
            """INSERT INTO recurring_transactions 
               (type, amount, category_or_source, frequency, next_due_date, account_id, note, subcategory)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                type,
                amount,
                category_or_source,
                frequency,
                start_date,
                account_id,
                note,
                subcategory,
            ),
        )
        return {"status": "OK", "id": cur.lastrowid}


@server.tool
def list_recurring_transactions() -> list[dict]:
    """
    Lists all configured recurring transactions.

    Returns:
        A list of dictionaries, each representing a recurring transaction.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            """
            SELECT rt.*, a.name as account_name FROM recurring_transactions rt
            LEFT JOIN accounts a ON rt.account_id = a.id
            ORDER BY rt.next_due_date ASC
            """
        )
        return [dict(row) for row in cur.fetchall()]


@server.tool
def update_recurring_transaction(
    transaction_id: int,
    amount: Optional[float] = None,
    next_due_date: Optional[str] = None,
    account_name: Optional[str] = None,
) -> dict:
    """
    Updates the amount, next due date, or account for a recurring transaction.

    Args:
        transaction_id: The ID of the recurring transaction to update.
        amount: The new amount.
        next_due_date: The new next due date in 'YYYY-MM-DD' format.
        account_name: The new account name.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        updates = {}
        if amount is not None:
            updates["amount"] = amount
        if next_due_date is not None:
            updates["next_due_date"] = next_due_date
        if account_name is not None:
            account_id = _get_account_id_from_name(c, account_name)
            if not account_id:
                return {
                    "status": "Error",
                    "message": f"Account '{account_name}' not found.",
                }
            updates["account_id"] = account_id

        if not updates:
            return {"status": "Error", "message": "No fields to update."}

        set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
        params = list(updates.values()) + [transaction_id]
        cur = c.execute(
            f"UPDATE recurring_transactions SET {set_clause} WHERE id = ?", params
        )

        if cur.rowcount == 0:
            return {
                "status": "Error",
                "message": f"Recurring transaction with ID {transaction_id} not found.",
            }
        return {
            "status": "OK",
            "message": f"Recurring transaction ID {transaction_id} updated.",
        }


@server.tool
def delete_recurring_transaction(transaction_id: int) -> dict:
    """
    Deletes a recurring transaction.

    Args:
        transaction_id: The ID of the recurring transaction to delete.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "DELETE FROM recurring_transactions WHERE id = ?", (transaction_id,)
        )
        if cur.rowcount > 0:
            return {"status": "OK", "message": "Recurring transaction deleted."}
        return {"status": "Error", "message": "Recurring transaction not found."}


@server.tool
def process_recurring_transactions() -> dict:
    """
    Checks for and processes any due recurring transactions. It logs them as
    actual expenses/income and updates their next due date. Handles overdue items correctly.

    Returns:
        A dictionary with the status and a count of processed transactions.
    """
    today = datetime.now()
    processed_count = 0
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        due_transactions = c.execute(
            "SELECT rt.*, a.name as account_name FROM recurring_transactions rt JOIN accounts a ON rt.account_id = a.id WHERE rt.next_due_date <= ?",
            (today.strftime("%d-%m-%Y"),),
        ).fetchall()

        for trans in due_transactions:
            next_due_str = trans["next_due_date"]
            while datetime.strptime(next_due_str, "%d-%m-%Y") <= today:
                c.execute("BEGIN TRANSACTION;")
                try:
                    if trans["type"] == "expense":
                        _internal_add_expense(
                            c,
                            next_due_str,
                            trans["amount"],
                            trans["category_or_source"],
                            trans["account_id"],
                            trans["subcategory"],
                            trans["note"],
                        )
                    elif trans["type"] == "income":
                        _internal_add_income(
                            c,
                            next_due_str,
                            trans["amount"],
                            trans["category_or_source"],
                            trans["account_id"],
                            trans["note"],
                        )
                    processed_count += 1
                    c.execute("COMMIT;")
                except Exception:
                    c.execute("ROLLBACK;")

                next_due_str = _calculate_next_date(next_due_str, trans["frequency"])

            c.execute(
                "UPDATE recurring_transactions SET next_due_date = ? WHERE id = ?",
                (next_due_str, trans["id"]),
            )

    return {"status": "OK", "processed_count": processed_count}


# --- Analytical Tools & Others ---


@server.tool
def summarize(
    start_date: str,
    end_date: str,
    category: Optional[str] = None,
    account_name: Optional[str] = None,
) -> list[dict]:
    """
    Summarizes expenses by category within a date range, with optional filters.

    Args:
        start_date: The start of the date range in 'YYYY-MM-DD' format.
        end_date: The end of the date range in 'YYYY-MM-DD' format.
        category: Optional. A specific category to filter by.
        account_name: Optional. A specific account name to filter by.

    Returns:
        A list of dictionaries, each showing a category and its total spending.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        query = "SELECT category, SUM(e.amount) AS total FROM expenses e LEFT JOIN accounts a ON e.account_id = a.id WHERE e.date BETWEEN ? AND ?"
        params = [start_date, end_date]
        if category:
            query += " AND e.category = ?"
            params.append(category)
        if account_name:
            query += " AND a.name = ? COLLATE NOCASE"
            params.append(account_name)
        query += " GROUP BY category ORDER BY total DESC"
        cur = c.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


@server.tool
def get_financial_summary(start_date: str, end_date: str) -> dict:
    """
    Calculates the total income, total expenses, and net savings for a given period.

    Args:
        start_date: The start of the date range in 'YYYY-MM-DD' format.
        end_date: The end of the date range in 'YYYY-MM-DD' format.

    Returns:
        A dictionary containing total_income, total_expenses, and net_savings.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        cur_income = c.execute(
            "SELECT SUM(amount) as total FROM income WHERE date BETWEEN ? AND ?",
            (start_date, end_date),
        )
        total_income = cur_income.fetchone()["total"] or 0.0
        cur_expenses = c.execute(
            "SELECT SUM(amount) as total FROM expenses WHERE date BETWEEN ? AND ?",
            (start_date, end_date),
        )
        total_expenses = cur_expenses.fetchone()["total"] or 0.0
        net_savings = total_income - total_expenses
        return {
            "total_income": round(total_income, 2),
            "total_expenses": round(total_expenses, 2),
            "net_savings": round(net_savings, 2),
        }


@server.tool
def get_top_spenders(start_date: str, end_date: str, count: int = 5) -> list[dict]:
    """Finds the top spending categories within a date range."""
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        query = """
            SELECT category, SUM(amount) as total_spent
            FROM expenses
            WHERE date BETWEEN ? AND ?
            GROUP BY category ORDER BY total_spent DESC LIMIT ?
        """
        cur = c.execute(query, (start_date, end_date, count))
        return [dict(row) for row in cur.fetchall()]


@server.tool
def get_spending_trend(
    category: str, start_date: str, end_date: str, period: str = "monthly"
) -> list[dict]:
    """Shows spending for a category over time, grouped by period ('monthly' or 'yearly')."""
    if period not in ["monthly", "yearly"]:
        return {"status": "Error", "message": "Period must be 'monthly' or 'yearly'."}
    date_format = "%Y-%m" if period == "monthly" else "%Y"
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        query = f"""
            SELECT strftime('{date_format}', date) as period, SUM(amount) as total_spent
            FROM expenses
            WHERE category = ? AND date BETWEEN ? AND ?
            GROUP BY period ORDER BY period ASC
        """
        cur = c.execute(query, (category, start_date, end_date))
        return [dict(row) for row in cur.fetchall()]


@server.tool
def set_budget(category: str, amount: float, month_year: str) -> dict:
    """
    Sets or updates a monthly budget for a specific spending category.

    Args:
        category: The category to set the budget for.
        amount: The budget amount.
        month_year: The month and year for the budget in 'YYYY-MM' format.

    Returns:
        A dictionary indicating the status of the operation.
    """
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            "INSERT OR REPLACE INTO budgets (category, amount, month_year) VALUES (?, ?, ?)",
            (category, amount, month_year),
        )
        return {"status": "OK"}


@server.tool
def get_budget_status(month_year: str, category: Optional[str] = None) -> list[dict]:
    """
    Checks the status of budgets for a given month, showing budget, spent, and remaining amounts.

    Args:
        month_year: The month to check in 'YYYY-MM' format.
        category: Optional. A specific category to check.

    Returns:
        A list of dictionaries, each detailing the status of a budget.
    """
    start_of_month = datetime.strptime(f"{month_year}-01", "%Y-%m-%d")
    end_of_month = (start_of_month.replace(day=28) + timedelta(days=4)).replace(
        day=1
    ) - timedelta(days=1)
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        query = "SELECT b.category, b.amount AS budget, IFNULL(e.total_spent, 0) AS spent, (b.amount - IFNULL(e.total_spent, 0)) as remaining FROM budgets b LEFT JOIN (SELECT category, SUM(amount) AS total_spent FROM expenses WHERE date BETWEEN ? AND ? GROUP BY category) e ON b.category = e.category WHERE b.month_year = ?"
        params = [
            start_of_month.strftime("%Y-%m-%d"),
            end_of_month.strftime("%Y-%m-%d"),
            month_year,
        ]
        if category:
            query += " AND b.category = ?"
            params.append(category)
        return [dict(row) for row in c.execute(query, params)]


@server.resource("expense://categories", mime_type="application/json")
def categories():
    """
    Provides the defined expense categories and subcategories as a JSON resource.
    """
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    server.run()

