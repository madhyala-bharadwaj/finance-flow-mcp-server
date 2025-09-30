# Finance Flow MCP Server

## Overview

This is a local MCP (Model Context Protocol) server for personal conversational financial management. It empowers an AI assistant to track expenses, income, budgets, and accounts through natural language, turning complex financial tasks into simple conversations.

The server maintains a local SQLite database to store all financial data, ensuring privacy and full user control.

## Features

- **Full Account Management:** Create, list, rename, and delete bank accounts, credit cards, or cash accounts.
- **Transactional Integrity:** All operations affecting balances (add, update, delete, transfer) are transactional to prevent data corruption.
- **Detailed Expense & Income Tracking:** Log every transaction with categories, subcategories, notes, and the associated account.
- **Powerful Budgeting:** Set monthly budgets for any category and check your spending status at any time.
- **Automated Recurring Transactions:** Set up recurring bills (rent, subscriptions) or income (salary) and have them logged automatically.
- **In-depth Financial Analysis:** Get high-level financial summaries, and drill down into spending habits by category, account, or date range.
- **Keyword Search:** Easily find past transactions with a simple keyword search in your notes.
- **Customizable Categories:** Define your own spending categories and subcategories by editing the `categories.json` file.

## Installation

### Prerequisites

Ensure you have the following installed:

- Python 3.8+

### Setup with uv

1.  **Install uv:**
    If you don't have it already, install `uv` globally using pip:
    ```sh
    pip install uv
    ```

2.  **Clone the Repository:**
    ```sh
    git clone https://github.com/madhyala-bharadwaj/finance-flow-mcp-server.git
    cd finance-flow-mcp-server
    ```

3.  **Initialize Virtual Environment:**
    Create and activate a virtual environment for the project.
    ```sh
    uv init
    ```
    Then activate it:
    - **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`
    - **Linux/macOS:** `source .venv/bin/activate`

4.  **Install Dependencies:**
    With the environment active, install the required packages using `uv`:
    ```sh
    uv add fastmcp pysqlite3
    ```

## Configuration

1.  **Database:** The server will automatically create an `expenses.db` file in the same directory when you run it for the first time. No setup is needed.
2.  **Categories:** You can customize your spending categories and subcategories by editing the `categories.json` file. The server comes with a comprehensive list to get you started.

## Integration with an AI Assistant

To integrate this server with an assistant like Claude, add the following to your `claude_desktop_config.json` (or similar configuration file):

```json
{
  "mcpServers": {
    "finance-flow": {
      "command": "/absolute/path/to/your/python",
      "args": [
        "/absolute/path/to/finance-flow-mcp-server/finance_flow_server.py"
      ]
    }
  }
}
```

### Finding Your Python Path

To find your Python executable path, use the appropriate command for your system:

#### Windows (PowerShell):
```sh
(Get-Command python).Source
```

#### Windows (Command Prompt/Terminal):
```sh
where python
```

#### Linux/macOS (Terminal):
```sh
which python
```

This ensures that your assistant can communicate with the server to manage your finances.

## Usage Examples

Here are some example prompts you can give to your AI assistant once the server is running:

- **Setup:**
  - *"Create a new bank account named 'SBI Bank' with a starting balance of 50,000 rupees."*
  - Add a 'Cash' account with an initial balance of 7,500 rupees.
  - *"Set my 'food' budget for September 2025 to 15,000 rupees."*

- **Logging Transactions:**
  - *"I bought groceries for 2,500 rupees with my SBI Bank account."*
  - *"I received my salary of 70,000 rupees into SBI Bank today."*

- **Automation:**
  - *"Set up a recurring expense for my Netflix subscription: 499 rupees from SBI Bank, charged monthly on the 10th."*
  - *"Please process any due recurring bills."*

- **Querying & Analysis:**
  - *"What are the balances in all my accounts?"*
  - *"How am I doing on my 'food' budget this month?"*
  - *"Show me my total income vs expenses for last month."*

- **Editing & Corrections:**
  - *"The grocery expense was actually 2,450. Please correct it."*
  - *"Please delete the income record for my freelance project."*

## Contributing

1. Fork the repository.
2. Create a new branch:
   ```sh
   git checkout -b feature/add-new-tool
   ```
3. Make your changes and commit them:
   ```sh
   git commit -m "feat: Add a new analysis tool"
   ```
4. Push to your forked repository:
   ```sh
   git push origin feature/add-new-tool
   ```
5. Open a pull request.

## License

This project is licensed under the MIT License. You are free to use, modify, and distribute the software. For more details, see the `LICENSE` file.

## Author

Created by **[madhyala-bharadwaj](https://github.com/madhyala-bharadwaj)**. Contributions welcome!

## Acknowledgments
- Inspired by the open-source MCP ecosystem.
- Built using the `fastmcp` and `sqlite3` library.
