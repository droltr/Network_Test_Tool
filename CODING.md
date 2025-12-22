# Network Test Tool - Coding Guidelines & User Requirements

## Project Overview
Network Test Tool - A comprehensive network diagnostic application built with PyQt5 for Windows.

## User Requirements & Design Decisions

### UI/UX Requirements

#### 1. Theme & Colors
- **Dark Theme**: Professional dark color scheme to prevent eye strain
- **Color Palette**:
  - Primary: `#1e2128` (dark background for header/footer)
  - Secondary: `#282c34` (main background)
  - Accent: `#61afef` (blue - for highlights and active states)
  - Success: `#98c379` (green - for positive status)
  - Warning: `#e5c07b` (yellow - for warnings)
  - Error: `#e06c75` (red - for errors)
  - Text: `#abb2bf` (light gray text)
  - Text Light: `#5c6370` (dimmed text)
  - Border: `#3e4451` (subtle borders)

#### 2. Layout & Structure
- **Window Size**: 1400x900 (minimum 1200x800)
- **Header**: 
  - Title and version on the left
  - Status indicator on the right
  - Clean, minimal design
- **Menu Bar**: 
  - File menu with Exit option (Ctrl+Q)
  - Help menu with About and GitHub Repository
  - Proper styling for dark theme
  - Visible menu items with proper contrast
- **Tabs**: 
  - No emojis, simple text labels
  - Responsive design with minimum width
  - Clear visual feedback for selected/hovered states
- **Footer**: 
  - Copyright on the left
  - Exit button on the right
  - Consistent styling

#### 3. Component Design
- **Spacing**: Consistent 15-20px margins and spacing
- **Buttons**: 35-40px height, rounded corners (6px)
- **Input Fields**: Minimum 35px height, proper focus states
- **Progress Bars**: 25px height, smooth appearance
- **Text Areas**: Minimum 200-300px height for readability
- **Group Boxes**: Subtle borders, clear titles

#### 4. Functionality Requirements
- **Responsive Tabs**: All tabs should be functional and responsive
- **No Duplicate Logs**: 
  - Speed test progress should update every 5% to avoid spam
  - Automated test should filter duplicate consecutive messages
- **Proper Cleanup**: All threads and timers should be cleaned up on close
- **Error Handling**: User-friendly error messages

### Technical Implementation

#### Dependencies
```python
PyQt5>=5.15.0
psutil>=5.9.0
speedtest-cli>=2.1.0
```

#### Project Structure
```
network_tools_Worked/
├── main.py                 # Application entry point
├── gui/
│   ├── main_window.py     # Main window with header, tabs, footer
│   ├── components/        # Individual tab widgets
│   │   ├── network_status.py
│   │   ├── ping_test.py
│   │   ├── port_scanner.py
│   │   ├── speed_test.py
│   │   └── auto_test.py
│   └── styles/
│       └── modern_theme.py # Dark theme stylesheet
├── network/               # Network operations
│   ├── detector.py
│   ├── ping.py
│   ├── scanner.py
│   ├── speed_test.py
│   └── troubleshooter.py
└── utils/                 # Utility functions
    ├── helpers.py
    └── logger.py
```

#### Key Design Patterns
1. **Threading**: All network operations run in QThread to prevent UI freezing
2. **Signal/Slot**: PyQt signals for thread-safe UI updates
3. **Cleanup**: Proper cleanup methods in all widgets
4. **Styling**: Centralized theme system with modern_theme.py

### Future Enhancements
- Export functionality for all test results
- History tracking for tests
- Scheduled network monitoring
- Email notifications for network issues
- Multi-language support

## Development Notes
- Always test on Windows 10/11
- Ensure administrator privileges notice for adapter management
- Keep UI responsive during long operations
- Use proper error handling and user feedback
- Maintain consistent styling across all components

## Last Updated
2024-12-22

## Recent Updates & Specific Instructions (2024-12-22)

### UI/UX Refinements
- **General Style**: Modern, serious, and simple interface with pastel colors (Dark Theme).
- **Header**:
  - Remove version number ("v1.0").
  - Status Indicator: Large round indicator with "Online" (Green) / "Offline" (Red) text.
- **Footer**:
  - Remove "2024 Network Tools" copyright text.
  - Clean layout.
- **Network Status Tab**:
  - **Card Layout**: Display adapters in card format.
  - **Sorting**: Active adapters (connected) must be at the top, inactive ones at the bottom.
  - **Refresh Rate**: Auto-refresh increased to 10 seconds to reduce load.
- **Menu**:
  - "Exit" button moved to the "File" menu.

### Troubleshooter (Automated Test)
- **Scope**:
  - **Remove Speed Test**: Speed test is excluded from the automated troubleshooting sequence.
  - **Active Adapters Only**: Report should only list active network interfaces.
- **Tests**:
  - **Ping**: Ping Gateway, DNS, and External Host (8.8.8.8) **3 times** each.
  - **Traceroute**: Target changed to `1.1.1.1`.

### Stability & Bug Fixes
- **Crash Prevention**: Global exception handler added to catch unhandled errors and prevent application closure.
- **Speed Test**:
  - Fixed `403 Forbidden` error by updating the configuration URL in `speedtest-cli` library.
  - Prevented duplicate log messages during testing.
