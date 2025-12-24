# Installation & Setup

## 📦 Using Standalone Executables (Recommended)

No installation is required. Simply download the executable for your operating system.

1.  Go to the [Releases Page](https://github.com/droltr/Network_Test_Tool/releases).
2.  Download the latest version:
    *   **Windows**: `NetworkTestTool_Windows.exe`
    *   **Linux**: `NetworkTestTool_Linux`
3.  Run the file.

> **Note for Windows Users**: You may need to run as Administrator to use features like "Renew IP" or "Flush DNS".

## 🔧 Running from Source

If you prefer to run the Python code directly:

### Prerequisites
*   Python 3.8 or higher
*   pip (Python package manager)

### Steps

1.  **Clone the repository**
    ```bash
    git clone https://github.com/droltr/Network_Test_Tool.git
    cd Network_Test_Tool
    ```

2.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: If requirements.txt is missing, install: `PyQt5`, `psutil`, `speedtest-cli`)*

3.  **Run the Application**
    ```bash
    python main.py
    ```
