flowchart TD
    U[Research request] --> S[Strategy supervisor]
    S --> D[Data agent]
    S --> R[Regime agent]
    D --> J{Fan-in barrier}
    R --> J
    J --> G[Signal agent]
    G --> C[Calibration agent]
    C --> B[Backtest agent]
    B --> X[Diagnostics agent]
    X --> Q{Acceptance gate}
    Q -->|Accepted or iteration budget exhausted| P[Reporting agent]
    Q -->|Recalibrate| C
    P --> E[Completed research package]